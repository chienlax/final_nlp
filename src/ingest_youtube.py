#!/usr/bin/env python3
"""
YouTube Ingestion Pipeline Orchestrator.

Simplified pipeline for YouTube videos WITH transcripts only.
Detects subtitle type (manual vs auto-generated) and requires transcripts.

Usage:
    python ingest_youtube.py <url1> <url2> ...

Pipeline Steps:
    1. Download audio as 16kHz mono WAV (2-60 min filter)
    2. Download transcripts with subtitle type detection
    3. Reject videos without transcripts
    4. Calculate linguistic metrics (CS ratio)
    5. Insert records into samples table with transcript revisions

Schema Version: 3.0 (Simplified YouTube-only pipeline)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils.video_downloading_utils import (
    download_channels,
    save_jsonl,
    METADATA_FILE,
    OUTPUT_DIR,
)
from utils.transcript_downloading_utils import (
    download_transcripts_from_metadata,
    TEXT_OUTPUT_DIR,
)
from utils.data_utils import (
    get_or_create_source,
    insert_sample,
    insert_transcript_revision,
    sample_exists,
    calculate_cs_ratio,
)


def map_subtitle_type(youtube_subtitle_type: str) -> str:
    """
    Map YouTube subtitle type to database enum value.

    Args:
        youtube_subtitle_type: 'Manual', 'Auto-generated', 'Not Available', 'Error'

    Returns:
        Database enum value: 'manual', 'auto_generated', 'none'
    """
    mapping = {
        'Manual': 'manual',
        'Auto-generated': 'auto_generated',
        'Not Available': 'none',
        'Error': 'none'
    }
    return mapping.get(youtube_subtitle_type, 'none')


def get_pipeline_type(subtitle_type: str) -> str:
    """
    Determine pipeline type based on subtitle type.

    Args:
        subtitle_type: Database subtitle type enum value.

    Returns:
        Pipeline type for source_type enum.
    """
    if subtitle_type == 'manual':
        return 'youtube_manual_transcript'
    elif subtitle_type == 'auto_generated':
        return 'youtube_auto_transcript'
    else:
        return 'manual_upload'  # Should not happen, we reject these


def ingest_to_database(
    metadata_entries: List[Dict[str, Any]],
    require_transcript: bool = True,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Ingest metadata entries into the samples table (v3 schema).

    Args:
        metadata_entries: List of metadata dictionaries from metadata.jsonl.
        require_transcript: If True, skip videos without transcripts.
        dry_run: If True, simulate without database writes.

    Returns:
        Dictionary with counts: {'inserted': N, 'skipped': M, 'rejected': K, 'failed': L}
    """
    stats = {'inserted': 0, 'skipped': 0, 'rejected': 0, 'failed': 0}

    if dry_run:
        print("\n[DRY RUN MODE - No database changes will be made]")

    print(f"\nIngesting {len(metadata_entries)} entries to database...")

    for entry in metadata_entries:
        video_id = entry.get('id')
        audio_file_path = entry.get('file_path')

        if not audio_file_path:
            print(f"[SKIP] No file_path for entry: {video_id}")
            stats['skipped'] += 1
            continue

        # Get subtitle type
        youtube_subtitle_type = entry.get('subtitle_type', 'Not Available')
        subtitle_type = map_subtitle_type(youtube_subtitle_type)

        # Check if transcript is required
        if require_transcript and subtitle_type == 'none':
            print(f"[REJECT] {video_id}: No transcript available")
            stats['rejected'] += 1
            continue

        # Check if already in database
        if sample_exists(audio_file_path=audio_file_path, external_id=video_id):
            print(f"[EXISTS] {audio_file_path}")
            stats['skipped'] += 1
            continue

        # Get transcript content
        transcript_raw: Optional[str] = None
        text_file_path: Optional[str] = None
        transcript_file = entry.get('transcript_file')

        if transcript_file:
            transcript_path = Path(transcript_file)
            if transcript_path.exists():
                # Load JSON transcript
                try:
                    with open(transcript_path, 'r', encoding='utf-8') as f:
                        transcript_data = json.load(f)
                    transcript_raw = transcript_data.get('full_text', '')
                    text_file_path = str(transcript_file)
                except Exception as e:
                    print(f"[WARNING] Could not load transcript for {video_id}: {e}")
                    transcript_raw = transcript_path.read_text(encoding='utf-8')

        # Double-check transcript requirement
        if require_transcript and not transcript_raw:
            print(f"[REJECT] {video_id}: Transcript file missing or empty")
            stats['rejected'] += 1
            continue

        # Determine pipeline type
        pipeline_type = get_pipeline_type(subtitle_type)

        # Calculate CS ratio if transcript available
        cs_ratio: Optional[float] = None
        if transcript_raw:
            cs_ratio = calculate_cs_ratio(transcript_raw)

        # Build metadata dictionaries
        source_metadata = {
            'url': entry.get('url'),
            'channel_id': entry.get('channel_id'),
            'upload_date': entry.get('upload_date'),
            'title': entry.get('title'),
            'youtube_subtitle_type': youtube_subtitle_type,
            'captured_at': entry.get('captured_at'),
        }

        acoustic_metadata = entry.get('acoustic_meta', {
            'sample_rate': 16000,
            'channels': 1,
            'format': 'wav',
        })
        acoustic_metadata['duration'] = entry.get('duration')

        try:
            if dry_run:
                # Dry run - just print what would happen
                print(f"[DRY RUN] Would insert: {video_id}")
                print(f"  - Pipeline: {pipeline_type}")
                print(f"  - Subtitle: {subtitle_type}")
                print(f"  - Audio: {audio_file_path}")
                print(f"  - Transcript: {'Yes' if transcript_raw else 'No'}")
                print(f"  - CS Ratio: {cs_ratio:.2%}" if cs_ratio else "  - CS Ratio: N/A")
                print(f"  - Duration: {entry.get('duration', 'Unknown')}s")
                stats['inserted'] += 1
                continue

            # Step 1: Get or create source (YouTube channel)
            channel_id = entry.get('channel_id', 'unknown')
            source_id = get_or_create_source(
                source_type=pipeline_type,
                external_id=channel_id,
                url=entry.get('url'),
                metadata={'channel_id': channel_id}
            )

            # Step 2: Insert sample
            sample_id = insert_sample(
                audio_file_path=audio_file_path,
                external_id=video_id,
                subtitle_type=subtitle_type,
                pipeline_type=pipeline_type,
                source_id=source_id,
                text_file_path=text_file_path,
                subtitle_language=entry.get('transcript_language'),
                duration_seconds=entry.get('duration'),
                cs_ratio=cs_ratio,
                source_metadata=source_metadata,
                acoustic_metadata=acoustic_metadata
            )

            # Step 3: Insert transcript revision if available
            if transcript_raw:
                revision_source = (
                    'youtube_manual' if subtitle_type == 'manual'
                    else 'youtube_auto'
                )
                insert_transcript_revision(
                    sample_id=sample_id,
                    transcript_text=transcript_raw,
                    revision_type='youtube_raw',
                    revision_source=revision_source
                )

            print(f"[INSERTED] {video_id} -> {sample_id}")
            print(f"  - Type: {subtitle_type}, CS: {cs_ratio:.2%}" if cs_ratio else f"  - Type: {subtitle_type}")
            stats['inserted'] += 1

        except Exception as e:
            print(f"[ERROR] {video_id}: {e}")
            stats['failed'] += 1

    return stats


def run_pipeline(
    urls: List[str],
    skip_download: bool = False,
    require_transcript: bool = True,
    dry_run: bool = False
) -> None:
    """
    Run the full YouTube ingestion pipeline (v3).

    Args:
        urls: List of YouTube channel or video URLs.
        skip_download: If True, skip download and use existing metadata.
        require_transcript: If True, reject videos without transcripts.
        dry_run: If True, simulate without database writes.
    """
    print("=" * 60)
    print("YouTube Ingestion Pipeline v3 (YouTube-only with transcripts)")
    if dry_run:
        print("[DRY RUN MODE]")
    if require_transcript:
        print("[TRANSCRIPT REQUIRED]")
    print("=" * 60)

    # Step 1: Download audio
    if not skip_download:
        print("\n[STEP 1/4] Downloading audio files...")
        print(f"Output directory: {OUTPUT_DIR.absolute()}")
        download_channels(urls)
        save_jsonl(append=True)
    else:
        print("\n[STEP 1/4] Skipping download (using existing metadata)")

    # Step 2: Download transcripts
    print("\n[STEP 2/4] Downloading transcripts...")
    print(f"Output directory: {TEXT_OUTPUT_DIR.absolute()}")
    metadata_entries = download_transcripts_from_metadata()

    if not metadata_entries:
        print("\nNo metadata found. Exiting.")
        return

    # Step 3: Filter and calculate metrics
    print("\n[STEP 3/4] Filtering and calculating metrics...")

    # Count by subtitle type
    subtitle_counts = {'Manual': 0, 'Auto-generated': 0, 'Not Available': 0, 'Error': 0}
    for entry in metadata_entries:
        st = entry.get('subtitle_type', 'Not Available')
        subtitle_counts[st] = subtitle_counts.get(st, 0) + 1

    print(f"  Subtitle types found:")
    for st, count in subtitle_counts.items():
        print(f"    - {st}: {count}")

    if require_transcript:
        valid_entries = [
            e for e in metadata_entries
            if e.get('subtitle_type') in ('Manual', 'Auto-generated')
        ]
        print(f"  Valid entries with transcripts: {len(valid_entries)}/{len(metadata_entries)}")
    else:
        valid_entries = metadata_entries

    # Calculate CS ratios
    for entry in valid_entries:
        transcript_file = entry.get('transcript_file')
        if transcript_file:
            transcript_path = Path(transcript_file)
            if transcript_path.exists():
                try:
                    with open(transcript_path, 'r', encoding='utf-8') as f:
                        transcript_data = json.load(f)
                    text = transcript_data.get('full_text', '')
                    cs_ratio = calculate_cs_ratio(text)
                    entry['cs_ratio'] = cs_ratio
                    print(f"  {entry['id']}: CS ratio = {cs_ratio:.2%}")
                except Exception:
                    pass

    # Step 4: Insert into database
    print("\n[STEP 4/4] Ingesting to database...")
    try:
        stats = ingest_to_database(
            metadata_entries,
            require_transcript=require_transcript,
            dry_run=dry_run
        )
        print(f"\nDatabase ingestion {'simulation' if dry_run else 'complete'}:")
        print(f"  - {'Would insert' if dry_run else 'Inserted'}: {stats['inserted']}")
        print(f"  - Skipped (exists): {stats['skipped']}")
        print(f"  - Rejected (no transcript): {stats['rejected']}")
        print(f"  - Failed: {stats['failed']}")
    except ConnectionError as e:
        print(f"\nDatabase connection failed: {e}")
        print("Data saved to metadata.jsonl for later ingestion.")

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print("=" * 60)


def main() -> None:
    """Parse arguments and run the pipeline."""
    parser = argparse.ArgumentParser(
        description="YouTube Ingestion Pipeline v3 (Transcripts Required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Download from a channel
    python ingest_youtube_v3.py https://www.youtube.com/@SomeChannel

    # Download specific videos
    python ingest_youtube_v3.py https://youtu.be/VIDEO_ID_1 https://youtu.be/VIDEO_ID_2

    # Re-ingest existing metadata (skip download)
    python ingest_youtube_v3.py --skip-download

    # Allow videos without transcripts (not recommended)
    python ingest_youtube_v3.py --skip-download --no-require-transcript
        """
    )
    parser.add_argument(
        'urls',
        nargs='*',
        help='YouTube channel or video URLs to download'
    )
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Skip download step and use existing metadata.jsonl'
    )
    parser.add_argument(
        '--no-require-transcript',
        action='store_true',
        help='Allow videos without transcripts (not recommended)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate ingestion without database writes'
    )

    args = parser.parse_args()

    if not args.urls and not args.skip_download:
        parser.print_help()
        print("\nError: Provide URLs or use --skip-download flag.")
        sys.exit(1)

    run_pipeline(
        args.urls,
        skip_download=args.skip_download,
        require_transcript=not args.no_require_transcript,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

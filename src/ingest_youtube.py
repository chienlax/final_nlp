#!/usr/bin/env python3
"""
YouTube Ingestion Pipeline Orchestrator.

Combines video download, transcript download, and database insertion
into a single workflow for the speech translation pipeline.

Usage:
    python ingest_youtube.py <url1> <url2> ...

Pipeline Steps:
    1. Download audio as 16kHz mono WAV (2-60 min filter)
    2. Download transcripts with subtitle type detection
    3. Calculate linguistic metrics (CS ratio)
    4. Insert records into samples table with transcript revisions

Schema Version: 2.0 (Multi-table design)
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils.video_downloading_utils import (
    download_channels,
    save_jsonl,
    downloaded_videos_log,
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


def ingest_to_database(metadata_entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Ingest metadata entries into the samples table.

    Creates source records, sample records, and transcript revisions
    following the new multi-table schema.

    Args:
        metadata_entries: List of metadata dictionaries from metadata.jsonl.

    Returns:
        Dictionary with counts: {'inserted': N, 'skipped': M, 'failed': K}
    """
    stats = {'inserted': 0, 'skipped': 0, 'failed': 0}

    print(f"\nIngesting {len(metadata_entries)} entries to database...")

    for entry in metadata_entries:
        video_id = entry.get('id')
        audio_file_path = entry.get('file_path')

        if not audio_file_path:
            print(f"[SKIP] No file_path for entry: {video_id}")
            stats['skipped'] += 1
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
                transcript_raw = transcript_path.read_text(encoding='utf-8')
                text_file_path = str(transcript_file)

        # Determine pipeline type based on transcript availability
        has_transcript = transcript_raw is not None
        subtitle_type = entry.get('subtitle_type', 'Unknown')
        pipeline_type = (
            'youtube_with_transcript' if has_transcript
            else 'youtube_without_transcript'
        )

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
            'subtitle_type': subtitle_type,
            'captured_at': entry.get('captured_at'),
        }

        acoustic_metadata = entry.get('acoustic_meta', {
            'sample_rate': 16000,
            'channels': 1,
            'format': 'wav',
        })
        acoustic_metadata['duration'] = entry.get('duration')

        linguistic_metadata = {
            'language_tags': entry.get('language_tags', ['vi', 'en']),
            'transcript_language': entry.get('transcript_language'),
        }

        try:
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
                content_type='audio_primary',
                pipeline_type=pipeline_type,
                audio_file_path=audio_file_path,
                text_file_path=text_file_path,
                external_id=video_id,
                source_id=source_id,
                duration_seconds=entry.get('duration'),
                cs_ratio=cs_ratio,
                source_metadata=source_metadata,
                acoustic_metadata=acoustic_metadata,
                linguistic_metadata=linguistic_metadata
            )

            # Step 3: Insert transcript revision if available
            if transcript_raw:
                revision_source = (
                    'youtube_manual' if subtitle_type == 'Manual'
                    else 'youtube_auto'
                )
                insert_transcript_revision(
                    sample_id=sample_id,
                    transcript_text=transcript_raw,
                    revision_type='raw',
                    revision_source=revision_source
                )

            print(f"[INSERTED] {video_id} -> {sample_id}")
            stats['inserted'] += 1

        except Exception as e:
            print(f"[ERROR] {video_id}: {e}")
            stats['failed'] += 1

    return stats


def run_pipeline(urls: List[str], skip_download: bool = False) -> None:
    """
    Run the full YouTube ingestion pipeline.

    Args:
        urls: List of YouTube channel or video URLs.
        skip_download: If True, skip download and use existing metadata.
    """
    print("=" * 60)
    print("YouTube Ingestion Pipeline")
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

    # Step 3: Calculate linguistic metrics
    print("\n[STEP 3/4] Calculating linguistic metrics...")
    for entry in metadata_entries:
        transcript_file = entry.get('transcript_file')
        if transcript_file:
            transcript_path = Path(transcript_file)
            if transcript_path.exists():
                text = transcript_path.read_text(encoding='utf-8')
                cs_ratio = calculate_cs_ratio(text)
                entry['cs_ratio'] = cs_ratio
                print(f"  {entry['id']}: CS ratio = {cs_ratio:.2f}")

    # Step 4: Insert into database
    print("\n[STEP 4/4] Ingesting to database...")
    try:
        stats = ingest_to_database(metadata_entries)
        print(f"\nDatabase ingestion complete:")
        print(f"  - Inserted: {stats['inserted']}")
        print(f"  - Skipped: {stats['skipped']}")
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
        description="YouTube Ingestion Pipeline for Speech Translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Download from a channel
    python ingest_youtube.py https://www.youtube.com/@SomeChannel

    # Download specific videos
    python ingest_youtube.py https://youtu.be/VIDEO_ID_1 https://youtu.be/VIDEO_ID_2

    # Re-ingest existing metadata (skip download)
    python ingest_youtube.py --skip-download
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

    args = parser.parse_args()

    if not args.urls and not args.skip_download:
        parser.print_help()
        print("\nError: Provide URLs or use --skip-download flag.")
        sys.exit(1)

    run_pipeline(args.urls, skip_download=args.skip_download)


if __name__ == "__main__":
    main()

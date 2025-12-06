#!/usr/bin/env python3
"""
YouTube Ingestion Pipeline Orchestrator (SQLite Version).

Simplified pipeline for YouTube videos. Downloads audio and inserts 
records into the SQLite database.

Usage:
    python ingest_youtube.py <url1> <url2> ...

Pipeline Steps:
    1. Download audio as 16kHz mono WAV (2-60 min filter)
    2. Insert video records into SQLite database
    3. Videos are ready for Gemini processing

Schema Version: 4.0 (SQLite-based simplified pipeline)

Changes:
    - Replaced PostgreSQL with SQLite
    - Removed transcript download step (Gemini handles transcription)
    - Simplified metadata handling
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from db import get_connection, init_database, insert_video
from utils.video_downloading_utils import (
    download_channels,
    save_jsonl,
    METADATA_FILE,
    OUTPUT_DIR,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "lab_data.db"


def video_exists(db_path: Path, video_id: str) -> bool:
    """
    Check if a video already exists in the database.
    
    Args:
        db_path: Path to SQLite database.
        video_id: YouTube video ID.
        
    Returns:
        True if video exists, False otherwise.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def ingest_to_database(
    metadata_entries: List[Dict[str, Any]],
    db_path: Path,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Ingest metadata entries into the SQLite videos table.

    Args:
        metadata_entries: List of metadata dictionaries from metadata.jsonl.
        db_path: Path to SQLite database.
        dry_run: If True, simulate without database writes.

    Returns:
        Dictionary with counts: {'inserted': N, 'skipped': M, 'failed': L}
    """
    stats = {'inserted': 0, 'skipped': 0, 'failed': 0}

    if dry_run:
        logger.info("[DRY RUN MODE - No database changes will be made]")

    logger.info(f"Ingesting {len(metadata_entries)} entries to database...")

    # Initialize database if needed
    if not dry_run:
        init_database(db_path)

    for entry in metadata_entries:
        video_id = entry.get('id')
        audio_file_path = entry.get('file_path')

        if not audio_file_path:
            logger.warning(f"[SKIP] No file_path for entry: {video_id}")
            stats['skipped'] += 1
            continue

        # Check if audio file exists
        if not Path(audio_file_path).exists():
            logger.warning(f"[SKIP] Audio file not found: {audio_file_path}")
            stats['skipped'] += 1
            continue

        # Check if already in database
        if not dry_run and video_exists(db_path, video_id):
            logger.info(f"[EXISTS] {video_id}")
            stats['skipped'] += 1
            continue

        # Extract metadata
        url = entry.get('url', '')
        title = entry.get('title', '')
        channel_name = entry.get('channel_name', '')
        duration = entry.get('duration', 0)

        try:
            if dry_run:
                logger.info(f"[DRY RUN] Would insert: {video_id}")
                logger.info(f"  - Title: {title}")
                logger.info(f"  - Channel: {channel_name}")
                logger.info(f"  - Duration: {duration}s")
                logger.info(f"  - Audio: {audio_file_path}")
                stats['inserted'] += 1
                continue

            # Insert video record
            insert_video(
                db_path=db_path,
                video_id=video_id,
                url=url,
                title=title,
                channel_name=channel_name,
                duration_seconds=duration,
                audio_path=audio_file_path,
                source_type="youtube"
            )

            logger.info(f"[INSERTED] {video_id}: {title[:50]}...")
            stats['inserted'] += 1

        except Exception as e:
            logger.error(f"[ERROR] {video_id}: {e}")
            stats['failed'] += 1

    return stats


def run_pipeline(
    urls: List[str],
    db_path: Path,
    skip_download: bool = False,
    dry_run: bool = False,
    download_transcript: bool = False
) -> None:
    """
    Run the full YouTube ingestion pipeline.

    Args:
        urls: List of YouTube channel or video URLs.
        db_path: Path to SQLite database.
        skip_download: If True, skip download and use existing metadata.
        dry_run: If True, simulate without database writes.
        download_transcript: If True, attempt to download subtitles.
    """
    logger.info("=" * 60)
    logger.info("YouTube Ingestion Pipeline v4 (SQLite)")
    if dry_run:
        logger.info("[DRY RUN MODE]")
    logger.info("=" * 60)

    # Step 1: Download audio
    if not skip_download:
        logger.info("\n[STEP 1/2] Downloading audio files...")
        logger.info(f"Output directory: {OUTPUT_DIR.absolute()}")
        download_channels(urls, download_transcript=download_transcript)
        save_jsonl(append=True)
    else:
        logger.info("\n[STEP 1/2] Skipping download (using existing metadata)")

    # Load metadata
    metadata_entries: List[Dict[str, Any]] = []
    if METADATA_FILE.exists():
        with open(METADATA_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        metadata_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    if not metadata_entries:
        logger.info("\nNo metadata found. Exiting.")
        return

    logger.info(f"\nLoaded {len(metadata_entries)} entries from metadata")

    # Step 2: Insert into database
    logger.info("\n[STEP 2/2] Ingesting to database...")
    stats = ingest_to_database(
        metadata_entries,
        db_path=db_path,
        dry_run=dry_run
    )

    logger.info(f"\nDatabase ingestion {'simulation' if dry_run else 'complete'}:")
    logger.info(f"  - {'Would insert' if dry_run else 'Inserted'}: {stats['inserted']}")
    logger.info(f"  - Skipped (exists or missing): {stats['skipped']}")
    logger.info(f"  - Failed: {stats['failed']}")

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline complete!")
    logger.info("=" * 60)
    logger.info("\nNext steps:")
    logger.info("  1. Run denoising: python src/preprocessing/denoise_audio.py")
    logger.info("  2. Run Gemini processing: python src/preprocessing/gemini_process_v2.py")
    logger.info("  3. Review in Streamlit: streamlit run src/review_app.py")


def main() -> None:
    """Parse arguments and run the pipeline."""
    parser = argparse.ArgumentParser(
        description="YouTube Ingestion Pipeline v4 (SQLite)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Download from a channel
    python ingest_youtube.py https://www.youtube.com/@SomeChannel

    # Download specific videos
    python ingest_youtube.py https://youtu.be/VIDEO_ID_1 https://youtu.be/VIDEO_ID_2

    # Re-ingest existing metadata (skip download)
    python ingest_youtube.py --skip-download

    # Dry run to see what would be ingested
    python ingest_youtube.py --skip-download --dry-run
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
        '--db',
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f'Path to SQLite database (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate ingestion without database writes'
    )
    parser.add_argument(
        '--download-transcript',
        action='store_true',
        help='Download manual Vietnamese subtitles if available'
    )

    args = parser.parse_args()

    if not args.urls and not args.skip_download:
        parser.print_help()
        logger.error("\nError: Provide URLs or use --skip-download flag.")
        sys.exit(1)

    run_pipeline(
        urls=args.urls,
        db_path=args.db,
        skip_download=args.skip_download,
        dry_run=args.dry_run,
        download_transcript=args.download_transcript
    )


if __name__ == "__main__":
    main()

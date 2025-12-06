#!/usr/bin/env python3
"""
Export reviewed segments to HuggingFace-compatible dataset format.

Reads approved segments from SQLite, cuts raw audio into 2-25s WAV chunks,
and generates a manifest TSV file.

Changes:
    - Created new export script for simplified SQLite-based pipeline
    - Replaces old export_reviewed.py that used PostgreSQL
    - Output format: audio chunks + manifest.tsv
"""

import argparse
import csv
import logging
import shutil
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

from db import get_connection, compute_duration_ms, validate_video_for_export

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000  # 16kHz mono
MIN_DURATION_MS = 2000  # 2 seconds
MAX_DURATION_MS = 25000  # 25 seconds

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "lab_data.db"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "export"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

class ExportSegment:
    """Container for segment data during export."""
    
    def __init__(
        self,
        segment_id: int,
        video_id: str,
        start_ms: int,
        end_ms: int,
        transcript_reviewed: str,
        translation_reviewed: str,
        audio_path: str
    ) -> None:
        self.segment_id = segment_id
        self.video_id = video_id
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.transcript = transcript_reviewed
        self.translation = translation_reviewed
        self.audio_path = Path(audio_path)
    
    @property
    def duration_ms(self) -> int:
        """Compute duration in milliseconds."""
        return compute_duration_ms(self.start_ms, self.end_ms)
    
    @property
    def output_filename(self) -> str:
        """Generate output filename for the audio chunk."""
        return f"{self.video_id}_{self.segment_id:06d}.wav"


# ---------------------------------------------------------------------------
# Database Functions
# ---------------------------------------------------------------------------

def fetch_approved_segments(
    db_path: Path,
    video_id: Optional[str] = None
) -> list[ExportSegment]:
    """
    Fetch all approved (reviewed, not rejected) segments from the database.
    
    Args:
        db_path: Path to SQLite database.
        video_id: Optional video ID to filter by.
        
    Returns:
        List of ExportSegment objects.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            s.segment_id,
            s.video_id,
            s.start_ms,
            s.end_ms,
            COALESCE(s.transcript_reviewed, s.transcript) as transcript,
            COALESCE(s.translation_reviewed, s.translation) as translation,
            v.audio_path
        FROM segments s
        JOIN videos v ON s.video_id = v.video_id
        WHERE s.is_rejected = 0
    """
    
    params: list = []
    if video_id:
        query += " AND s.video_id = ?"
        params.append(video_id)
    
    query += " ORDER BY s.video_id, s.start_ms"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    segments = []
    for row in rows:
        seg = ExportSegment(
            segment_id=row[0],
            video_id=row[1],
            start_ms=row[2],
            end_ms=row[3],
            transcript_reviewed=row[4],
            translation_reviewed=row[5],
            audio_path=row[6]
        )
        segments.append(seg)
    
    return segments


def mark_video_exported(db_path: Path, video_id: str) -> None:
    """
    Update video processing_state to 'exported'.
    
    Args:
        db_path: Path to SQLite database.
        video_id: Video ID to update.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE videos SET processing_state = ? WHERE video_id = ?",
        ("exported", video_id)
    )
    
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Audio Processing
# ---------------------------------------------------------------------------

def cut_audio_segment(
    audio: AudioSegment,
    segment: ExportSegment,
    output_path: Path
) -> bool:
    """
    Cut a segment from the audio and save to output path.
    
    Args:
        audio: Loaded AudioSegment.
        segment: ExportSegment with start/end times.
        output_path: Path to save the cut audio.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        # Validate duration
        duration_ms = segment.duration_ms
        
        if duration_ms < MIN_DURATION_MS:
            logger.warning(
                f"Segment {segment.segment_id} too short: {duration_ms}ms < {MIN_DURATION_MS}ms"
            )
            return False
        
        if duration_ms > MAX_DURATION_MS:
            logger.warning(
                f"Segment {segment.segment_id} too long: {duration_ms}ms > {MAX_DURATION_MS}ms"
            )
            return False
        
        # Cut the segment
        audio_chunk = audio[segment.start_ms:segment.end_ms]
        
        # Ensure correct format (16kHz mono)
        audio_chunk = audio_chunk.set_frame_rate(SAMPLE_RATE)
        audio_chunk = audio_chunk.set_channels(1)
        
        # Export
        audio_chunk.export(
            output_path,
            format="wav",
            parameters=["-acodec", "pcm_s16le"]
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to cut segment {segment.segment_id}: {e}")
        return False


def load_audio_file(audio_path: Path) -> Optional[AudioSegment]:
    """
    Load an audio file, with error handling.
    
    Args:
        audio_path: Path to audio file.
        
    Returns:
        AudioSegment or None if loading fails.
    """
    try:
        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            return None
        
        return AudioSegment.from_file(audio_path)
        
    except Exception as e:
        logger.error(f"Failed to load audio {audio_path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Manifest Generation
# ---------------------------------------------------------------------------

def generate_manifest(
    segments: list[tuple[ExportSegment, Path]],
    output_dir: Path
) -> Path:
    """
    Generate manifest TSV file for HuggingFace datasets.
    
    Format:
        audio_path | transcript | translation | duration_ms
    
    Args:
        segments: List of (ExportSegment, output_audio_path) tuples.
        output_dir: Directory to save manifest.
        
    Returns:
        Path to the manifest file.
    """
    manifest_path = output_dir / "manifest.tsv"
    
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        
        # Header
        writer.writerow(["audio_path", "transcript", "translation", "duration_ms"])
        
        # Data rows
        for segment, audio_path in segments:
            # Use relative path from manifest location
            relative_audio = audio_path.relative_to(output_dir)
            
            writer.writerow([
                str(relative_audio),
                segment.transcript,
                segment.translation,
                segment.duration_ms
            ])
    
    return manifest_path


# ---------------------------------------------------------------------------
# Main Export Logic
# ---------------------------------------------------------------------------

def export_segments(
    db_path: Path,
    output_dir: Path,
    video_id: Optional[str] = None,
    overwrite: bool = False
) -> dict:
    """
    Export approved segments to audio files and manifest.
    
    Args:
        db_path: Path to SQLite database.
        output_dir: Directory for exported files.
        video_id: Optional video ID to filter export.
        overwrite: Whether to overwrite existing exports.
        
    Returns:
        Dictionary with export statistics.
    """
    stats = {
        "total_segments": 0,
        "exported": 0,
        "skipped_short": 0,
        "skipped_long": 0,
        "failed": 0,
        "videos_processed": set(),
        "validation_errors": []
    }
    
    # Validate video if specific video_id provided
    if video_id:
        logger.info(f"Validating video {video_id} before export...")
        validation = validate_video_for_export(video_id, db_path)
        
        if not validation['is_valid']:
            logger.error(f"Validation failed for video {video_id}:")
            for error in validation['errors']:
                logger.error(f"  - {error}")
            
            stats["validation_errors"] = validation['errors']
            return stats
        
        logger.info(f"✓ Video {video_id} passed validation")
    
    # Create output directories
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle overwrite
    if overwrite and output_dir.exists():
        logger.info(f"Overwriting existing export at {output_dir}")
        for item in audio_dir.iterdir():
            if item.is_file():
                item.unlink()
    
    # Fetch segments
    segments = fetch_approved_segments(db_path, video_id)
    stats["total_segments"] = len(segments)
    
    if not segments:
        logger.info("No approved segments found for export.")
        return stats
    
    logger.info(f"Found {len(segments)} approved segments to export")
    
    # Group by audio file to minimize loading
    audio_cache: dict[Path, AudioSegment] = {}
    exported_segments: list[tuple[ExportSegment, Path]] = []
    
    for segment in segments:
        # Load audio if not cached
        if segment.audio_path not in audio_cache:
            audio = load_audio_file(segment.audio_path)
            if audio is None:
                stats["failed"] += 1
                continue
            audio_cache[segment.audio_path] = audio
        
        audio = audio_cache[segment.audio_path]
        
        # Determine output path
        output_path = audio_dir / segment.output_filename
        
        # Skip if exists and not overwriting
        if output_path.exists() and not overwrite:
            logger.debug(f"Skipping existing: {output_path}")
            continue
        
        # Cut and save
        duration_ms = segment.duration_ms
        
        if duration_ms < MIN_DURATION_MS:
            stats["skipped_short"] += 1
            continue
        
        if duration_ms > MAX_DURATION_MS:
            stats["skipped_long"] += 1
            continue
        
        success = cut_audio_segment(audio, segment, output_path)
        
        if success:
            stats["exported"] += 1
            stats["videos_processed"].add(segment.video_id)
            exported_segments.append((segment, output_path))
        else:
            stats["failed"] += 1
    
    # Generate manifest
    if exported_segments:
        manifest_path = generate_manifest(exported_segments, output_dir)
        logger.info(f"Generated manifest: {manifest_path}")
    
    # Update video states
    for vid in stats["videos_processed"]:
        mark_video_exported(db_path, vid)
    
    # Convert set to count for JSON serialization
    stats["videos_processed"] = len(stats["videos_processed"])
    
    return stats


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export reviewed segments to HuggingFace dataset format."
    )
    
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})"
    )
    
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for export (default: {DEFAULT_OUTPUT_DIR})"
    )
    
    parser.add_argument(
        "--video-id",
        type=str,
        default=None,
        help="Export segments for a specific video only"
    )
    
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing exported files"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    return parser.parse_args()


def main() -> None:
    """Main entry point for export script."""
    args = parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting export...")
    logger.info(f"  Database: {args.db}")
    logger.info(f"  Output: {args.output}")
    
    if args.video_id:
        logger.info(f"  Video filter: {args.video_id}")
    
    # Run export
    stats = export_segments(
        db_path=args.db,
        output_dir=args.output,
        video_id=args.video_id,
        overwrite=args.overwrite
    )
    
    # Print summary
    logger.info("=" * 50)
    logger.info("Export Complete!")
    logger.info(f"  Total segments: {stats['total_segments']}")
    logger.info(f"  Exported: {stats['exported']}")
    logger.info(f"  Skipped (too short): {stats['skipped_short']}")
    logger.info(f"  Skipped (too long): {stats['skipped_long']}")
    logger.info(f"  Failed: {stats['failed']}")
    logger.info(f"  Videos processed: {stats['videos_processed']}")


if __name__ == "__main__":
    main()

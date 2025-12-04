#!/usr/bin/env python3
"""
DeepFilterNet Noise Removal Script (SQLite Version).

Removes background noise from audio files using DeepFilterNet.
Does NOT enhance or upscale audio - only removes noise.

Pipeline Stage: ingested → denoised

Usage:
    python denoise_audio.py --video-id <id>
    python denoise_audio.py --all

Changes:
    - Simplified for SQLite-based pipeline
    - Denoises full audio files (not segments)
    - Updates processing_state in videos table

Requirements:
    - deepfilternet package (pip install deepfilternet)
    - GPU recommended for faster processing
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

SAMPLE_RATE = 16000  # 16kHz as per project standard
AUDIO_FORMAT = "wav"
DEEPFILTER_MODEL = "DeepFilterNet3"

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lab_data.db"
DENOISED_DIR = Path(__file__).parent.parent.parent / "data" / "denoised"


# =============================================================================
# DENOISING FUNCTIONS
# =============================================================================

def load_deepfilter_model() -> tuple:
    """
    Load DeepFilterNet model.

    Returns:
        Tuple of (model, df_state).

    Raises:
        ImportError: If deepfilternet is not installed.
    """
    try:
        from df.enhance import init_df
    except ImportError as e:
        raise ImportError(
            "deepfilternet is required. Install with: pip install deepfilternet"
        ) from e

    logger.info(f"Loading DeepFilterNet model: {DEEPFILTER_MODEL}")
    model, df_state, _ = init_df()
    logger.info("Model loaded successfully!")

    return model, df_state


def denoise_audio_file(
    input_path: Path,
    output_path: Path,
    model: Any,
    df_state: Any
) -> Dict[str, Any]:
    """
    Denoise a single audio file using DeepFilterNet.

    Args:
        input_path: Path to input audio file.
        output_path: Path for denoised output.
        model: DeepFilterNet model.
        df_state: DeepFilterNet state.

    Returns:
        Dictionary with processing metadata.

    Raises:
        FileNotFoundError: If input file doesn't exist.
        RuntimeError: If denoising fails.
    """
    from df.enhance import enhance, load_audio, save_audio

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    # Load audio
    audio, sr = load_audio(str(input_path), sr=SAMPLE_RATE)
    input_duration = len(audio) / sr

    # Apply denoising
    enhanced_audio = enhance(model, df_state, audio)

    # Save output
    save_audio(str(output_path), enhanced_audio, sr=SAMPLE_RATE)

    processing_time = time.time() - start_time

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "sample_rate": SAMPLE_RATE,
        "duration_seconds": round(input_duration, 2),
        "processing_time_seconds": round(processing_time, 2),
        "model": DEEPFILTER_MODEL,
        "realtime_factor": round(input_duration / processing_time, 2) if processing_time > 0 else 0
    }


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_videos_for_denoising(db_path: Path) -> List[Dict[str, Any]]:
    """
    Get videos ready for denoising (state = 'ingested').

    Args:
        db_path: Path to SQLite database.

    Returns:
        List of video dictionaries.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT video_id, url, title, audio_path, duration_seconds
        FROM videos
        WHERE processing_state = 'ingested'
        ORDER BY created_at ASC
    """)
    
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(zip(columns, row)) for row in rows]


def get_video_by_id(db_path: Path, video_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific video by ID.

    Args:
        db_path: Path to SQLite database.
        video_id: Video ID to fetch.

    Returns:
        Video dictionary or None.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT video_id, url, title, audio_path, duration_seconds, processing_state
        FROM videos
        WHERE video_id = ?
    """, (video_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    columns = ["video_id", "url", "title", "audio_path", "duration_seconds", "processing_state"]
    return dict(zip(columns, row))


def update_video_denoised(
    db_path: Path,
    video_id: str,
    denoised_path: str
) -> None:
    """
    Update video with denoised audio path and transition state.

    Args:
        db_path: Path to SQLite database.
        video_id: Video ID to update.
        denoised_path: Path to denoised audio file.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Update audio_path to denoised version and change state
    cursor.execute("""
        UPDATE videos
        SET audio_path = ?,
            processing_state = 'denoised',
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
    """, (denoised_path, video_id))
    
    conn.commit()
    conn.close()


# =============================================================================
# PROCESSING FUNCTIONS
# =============================================================================

def process_video(
    video: Dict[str, Any],
    model: Any,
    df_state: Any,
    db_path: Path,
    output_dir: Path
) -> bool:
    """
    Process a single video for denoising.

    Args:
        video: Video dictionary from database.
        model: DeepFilterNet model.
        df_state: DeepFilterNet state.
        db_path: Path to SQLite database.
        output_dir: Directory for denoised output.

    Returns:
        True if successful, False otherwise.
    """
    video_id = video["video_id"]
    audio_path = Path(video["audio_path"])
    
    logger.info(f"Processing: {video_id}")
    logger.info(f"  Title: {video.get('title', 'Unknown')[:50]}")
    logger.info(f"  Input: {audio_path}")
    
    # Build output path
    output_path = output_dir / f"{video_id}_denoised.wav"
    
    try:
        result = denoise_audio_file(audio_path, output_path, model, df_state)
        
        logger.info(f"  Duration: {result['duration_seconds']}s")
        logger.info(f"  Processing: {result['processing_time_seconds']}s ({result['realtime_factor']}x realtime)")
        logger.info(f"  Output: {output_path}")
        
        # Update database
        update_video_denoised(db_path, video_id, str(output_path))
        
        logger.info(f"  ✓ Denoising complete!")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Failed: {e}")
        return False


def run_batch_denoising(
    db_path: Path,
    output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, int]:
    """
    Run denoising on all pending videos.

    Args:
        db_path: Path to SQLite database.
        output_dir: Directory for denoised output.
        limit: Maximum number of videos to process.

    Returns:
        Dictionary with processing statistics.
    """
    stats = {"processed": 0, "failed": 0, "skipped": 0}
    
    # Get videos to process
    videos = get_videos_for_denoising(db_path)
    
    if limit:
        videos = videos[:limit]
    
    if not videos:
        logger.info("No videos pending denoising.")
        return stats
    
    logger.info(f"Found {len(videos)} videos to denoise")
    
    # Load model once
    try:
        model, df_state = load_deepfilter_model()
    except ImportError as e:
        logger.error(f"Cannot load DeepFilterNet: {e}")
        logger.error("Install with: pip install deepfilternet")
        return stats
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each video
    for i, video in enumerate(videos, 1):
        logger.info(f"\n[{i}/{len(videos)}] {'=' * 40}")
        
        success = process_video(video, model, df_state, db_path, output_dir)
        
        if success:
            stats["processed"] += 1
        else:
            stats["failed"] += 1
    
    return stats


# =============================================================================
# CLI INTERFACE
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Denoise audio files using DeepFilterNet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Denoise all pending videos
    python denoise_audio.py --all
    
    # Denoise a specific video
    python denoise_audio.py --video-id VIDEO_ID
    
    # Process with limit
    python denoise_audio.py --all --limit 5
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--video-id',
        type=str,
        help='Denoise a specific video by ID'
    )
    group.add_argument(
        '--all',
        action='store_true',
        help='Denoise all pending videos'
    )
    
    parser.add_argument(
        '--db',
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f'Path to SQLite database (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=DENOISED_DIR,
        help=f'Output directory for denoised audio (default: {DENOISED_DIR})'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of videos to process (with --all)'
    )
    
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    
    logger.info("=" * 60)
    logger.info("DeepFilterNet Audio Denoising")
    logger.info("=" * 60)
    
    if args.video_id:
        # Process single video
        video = get_video_by_id(args.db, args.video_id)
        
        if not video:
            logger.error(f"Video not found: {args.video_id}")
            sys.exit(1)
        
        if video["processing_state"] != "ingested":
            logger.warning(f"Video state is '{video['processing_state']}', not 'ingested'")
            logger.warning("Proceeding anyway...")
        
        try:
            model, df_state = load_deepfilter_model()
        except ImportError as e:
            logger.error(f"Cannot load DeepFilterNet: {e}")
            sys.exit(1)
        
        args.output.mkdir(parents=True, exist_ok=True)
        success = process_video(video, model, df_state, args.db, args.output)
        sys.exit(0 if success else 1)
    
    else:
        # Batch processing
        stats = run_batch_denoising(args.db, args.output, args.limit)
        
        logger.info("\n" + "=" * 60)
        logger.info("Denoising Complete!")
        logger.info(f"  Processed: {stats['processed']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info("=" * 60)
        
        logger.info("\nNext step: Run Gemini processing")
        logger.info("  python src/preprocessing/gemini_process_v2.py --all")


if __name__ == "__main__":
    main()

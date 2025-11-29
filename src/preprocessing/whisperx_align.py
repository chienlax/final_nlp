#!/usr/bin/env python3
"""
WhisperX Alignment Script.

Aligns verified transcripts with audio using WhisperX's forced alignment.
Produces word-level timestamps for accurate segmentation.

Uses Vietnamese alignment model: nguyenvulebinh/wav2vec2-base-vi-vlsp2020

Pipeline Stage: TRANSCRIPT_VERIFIED → ALIGNED

Usage:
    python whisperx_align.py --sample-id <uuid>
    python whisperx_align.py --batch --limit 10

Requirements:
    - CUDA-enabled GPU (recommended)
    - whisperx package installed
    - Audio file in 16kHz mono WAV format
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import Json, RealDictCursor

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.data_utils import get_pg_connection, log_processing


# =============================================================================
# CONFIGURATION
# =============================================================================

# WhisperX alignment model for Vietnamese
VIETNAMESE_ALIGNMENT_MODEL = "nguyenvulebinh/wav2vec2-base-vi-vlsp2020"

# Audio processing settings
SAMPLE_RATE = 16000
DEVICE = "cuda"  # "cuda" or "cpu"
COMPUTE_TYPE = "float16"  # "float16" for GPU, "int8" for CPU


# =============================================================================
# WHISPERX FUNCTIONS
# =============================================================================

def load_whisperx_model() -> Tuple[Any, Any]:
    """
    Load WhisperX model and alignment model.

    Returns:
        Tuple of (whisper_model, alignment_model_info).

    Raises:
        ImportError: If whisperx is not installed.
        RuntimeError: If CUDA is required but not available.
    """
    try:
        import torch
        import whisperx
    except ImportError as e:
        raise ImportError(
            "whisperx is required. Install with: pip install whisperx"
        ) from e

    # Check CUDA availability
    if DEVICE == "cuda" and not torch.cuda.is_available():
        print("[WARNING] CUDA not available, falling back to CPU")
        device = "cpu"
        compute_type = "int8"
    else:
        device = DEVICE
        compute_type = COMPUTE_TYPE

    print(f"[INFO] Loading WhisperX on device: {device}")

    # Load base Whisper model (for alignment, we use small for efficiency)
    # We're doing alignment, not transcription, so small is sufficient
    model = whisperx.load_model(
        "small",
        device=device,
        compute_type=compute_type,
        language="vi"
    )

    # Load alignment model
    print(f"[INFO] Loading Vietnamese alignment model: {VIETNAMESE_ALIGNMENT_MODEL}")
    align_model, align_metadata = whisperx.load_align_model(
        language_code="vi",
        device=device,
        model_name=VIETNAMESE_ALIGNMENT_MODEL
    )

    return model, (align_model, align_metadata)


def align_transcript(
    audio_path: Path,
    transcript_text: str,
    whisper_model: Any,
    align_info: Tuple[Any, Any]
) -> Dict[str, Any]:
    """
    Align transcript with audio using WhisperX.

    Args:
        audio_path: Path to the audio file (16kHz mono WAV).
        transcript_text: The verified transcript text.
        whisper_model: Loaded WhisperX model.
        align_info: Tuple of (alignment_model, alignment_metadata).

    Returns:
        Dictionary containing:
        - word_timestamps: List of {word, start, end, score}
        - sentence_timestamps: List of {text, start, end, words}
        - alignment_metadata: Processing metadata

    Raises:
        FileNotFoundError: If audio file doesn't exist.
        RuntimeError: If alignment fails.
    """
    import whisperx

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    align_model, align_metadata = align_info
    device = DEVICE if __import__("torch").cuda.is_available() else "cpu"

    # Load audio
    print(f"[INFO] Loading audio: {audio_path}")
    audio = whisperx.load_audio(str(audio_path))

    # Create transcript segments for alignment
    # WhisperX expects segments format from transcription
    # We'll create a single segment with the full transcript
    segments = [{"text": transcript_text, "start": 0.0, "end": len(audio) / SAMPLE_RATE}]

    # Align with audio
    print("[INFO] Running forced alignment...")
    start_time = time.time()

    result = whisperx.align(
        segments,
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False
    )

    alignment_time = time.time() - start_time
    print(f"[INFO] Alignment completed in {alignment_time:.2f}s")

    # Extract word-level timestamps
    word_timestamps = []
    sentence_timestamps = []

    for segment in result.get("segments", []):
        words_in_segment = []

        for word_info in segment.get("words", []):
            word_data = {
                "word": word_info.get("word", ""),
                "start": round(word_info.get("start", 0.0), 3),
                "end": round(word_info.get("end", 0.0), 3),
                "score": round(word_info.get("score", 0.0), 4)
            }
            word_timestamps.append(word_data)
            words_in_segment.append(word_data)

        sentence_timestamps.append({
            "text": segment.get("text", ""),
            "start": round(segment.get("start", 0.0), 3),
            "end": round(segment.get("end", 0.0), 3),
            "words": words_in_segment
        })

    return {
        "word_timestamps": word_timestamps,
        "sentence_timestamps": sentence_timestamps,
        "alignment_metadata": {
            "model": VIETNAMESE_ALIGNMENT_MODEL,
            "device": device,
            "alignment_time_seconds": round(alignment_time, 2),
            "audio_duration_seconds": round(len(audio) / SAMPLE_RATE, 2),
            "word_count": len(word_timestamps),
            "segment_count": len(sentence_timestamps)
        }
    }


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_alignment(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for alignment (TRANSCRIPT_VERIFIED state).

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries with transcript info.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.audio_file_path,
                    s.duration_seconds,
                    tr.revision_id AS transcript_revision_id,
                    tr.transcript_text
                FROM samples s
                JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                WHERE s.processing_state = 'TRANSCRIPT_VERIFIED'
                  AND s.is_deleted = FALSE
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def save_alignment_results(
    sample_id: str,
    transcript_revision_id: str,
    alignment_result: Dict[str, Any],
    executor: str = "whisperx_align"
) -> str:
    """
    Save alignment results to database.

    Creates a new transcript revision with word/sentence timestamps
    and transitions sample to ALIGNED state.

    Args:
        sample_id: UUID of the sample.
        transcript_revision_id: UUID of source transcript revision.
        alignment_result: Alignment result dictionary.
        executor: Name of the executor for logging.

    Returns:
        UUID of the new transcript revision.

    Raises:
        Exception: If save fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            # Get transcript text from source revision
            cur.execute(
                "SELECT transcript_text FROM transcript_revisions WHERE revision_id = %s",
                (transcript_revision_id,)
            )
            transcript_text = cur.fetchone()[0]

            # Insert new transcript revision with alignment data
            cur.execute(
                """
                SELECT add_transcript_revision(
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    sample_id,
                    transcript_text,
                    'whisperx_aligned',
                    VIETNAMESE_ALIGNMENT_MODEL,
                    Json(alignment_result["word_timestamps"]),
                    Json(alignment_result["sentence_timestamps"]),
                    executor
                )
            )
            new_revision_id = cur.fetchone()[0]

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'ALIGNED'::processing_state, %s)",
                (sample_id, executor)
            )

            # Update processing metadata
            cur.execute(
                """
                UPDATE samples 
                SET processing_metadata = processing_metadata || %s
                WHERE sample_id = %s
                """,
                (
                    Json({"whisperx": alignment_result["alignment_metadata"]}),
                    sample_id
                )
            )

            conn.commit()
            return str(new_revision_id)

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to save alignment results: {e}")
    finally:
        conn.close()


def process_sample(
    sample: Dict[str, Any],
    whisper_model: Any,
    align_info: Tuple[Any, Any],
    data_root: Path
) -> bool:
    """
    Process a single sample for alignment.

    Args:
        sample: Sample dictionary from database.
        whisper_model: Loaded WhisperX model.
        align_info: Alignment model info.
        data_root: Root directory for data files.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = sample["sample_id"]
    external_id = sample["external_id"]
    audio_path = data_root / sample["audio_file_path"]

    print(f"\n{'='*60}")
    print(f"Processing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Audio: {audio_path}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        # Run alignment
        alignment_result = align_transcript(
            audio_path=audio_path,
            transcript_text=sample["transcript_text"],
            whisper_model=whisper_model,
            align_info=align_info
        )

        # Save results
        revision_id = save_alignment_results(
            sample_id=str(sample_id),
            transcript_revision_id=str(sample["transcript_revision_id"]),
            alignment_result=alignment_result
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log success
        log_processing(
            operation="whisperx_alignment",
            success=True,
            sample_id=str(sample_id),
            previous_state="TRANSCRIPT_VERIFIED",
            new_state="ALIGNED",
            executor="whisperx_align",
            execution_time_ms=execution_time_ms,
            input_params={"audio_path": str(audio_path)},
            output_summary={
                "revision_id": revision_id,
                "word_count": alignment_result["alignment_metadata"]["word_count"],
                "segment_count": alignment_result["alignment_metadata"]["segment_count"]
            }
        )

        print(f"[SUCCESS] Aligned {external_id}")
        print(f"  Words: {alignment_result['alignment_metadata']['word_count']}")
        print(f"  Segments: {alignment_result['alignment_metadata']['segment_count']}")
        print(f"  Time: {execution_time_ms/1000:.2f}s")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="whisperx_alignment",
            success=False,
            sample_id=str(sample_id),
            previous_state="TRANSCRIPT_VERIFIED",
            executor="whisperx_align",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to align {external_id}: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for WhisperX alignment."""
    parser = argparse.ArgumentParser(
        description="Align transcripts with audio using WhisperX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Align a specific sample
    python whisperx_align.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of samples
    python whisperx_align.py --batch --limit 10

    # Specify data root
    python whisperx_align.py --batch --data-root /app/data
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to align"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in TRANSCRIPT_VERIFIED state"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of samples to process in batch mode (default: 10)"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/app/data"),
        help="Root directory for data files (default: /app/data)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making changes"
    )

    args = parser.parse_args()

    if not args.sample_id and not args.batch:
        parser.print_help()
        print("\nError: Specify --sample-id or --batch")
        sys.exit(1)

    # Resolve data root
    data_root = args.data_root
    if not data_root.exists():
        # Try relative path from script location
        data_root = Path(__file__).parent.parent.parent / "data"

    print(f"Data root: {data_root.absolute()}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_alignment(limit=args.limit)
        print(f"Found {len(samples)} samples ready for alignment:")
        for s in samples:
            print(f"  - {s['external_id']}: {s['duration_seconds']:.1f}s")
        return

    # Load models
    print("\n[INFO] Loading WhisperX models...")
    whisper_model, align_info = load_whisperx_model()

    # Process samples
    if args.sample_id:
        # Single sample mode
        conn = get_pg_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        s.sample_id,
                        s.external_id,
                        s.audio_file_path,
                        s.duration_seconds,
                        tr.revision_id AS transcript_revision_id,
                        tr.transcript_text
                    FROM samples s
                    JOIN transcript_revisions tr 
                        ON s.sample_id = tr.sample_id 
                        AND tr.version = s.current_transcript_version
                    WHERE s.sample_id = %s
                    """,
                    (args.sample_id,)
                )
                sample = cur.fetchone()
                if sample:
                    process_sample(dict(sample), whisper_model, align_info, data_root)
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_alignment(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(sample, whisper_model, align_info, data_root):
                success_count += 1
            else:
                fail_count += 1

        print(f"\n{'='*60}")
        print(f"Batch processing complete")
        print(f"  Success: {success_count}")
        print(f"  Failed: {fail_count}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

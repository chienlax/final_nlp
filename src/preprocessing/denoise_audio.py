#!/usr/bin/env python3
"""
DeepFilterNet Noise Removal Script.

Removes background noise from audio segments using DeepFilterNet.
Does NOT enhance or upscale audio - only removes noise.

Pipeline Stage: TRANSLATION_REVIEW (verified) → DENOISED

Usage:
    python denoise_audio.py --sample-id <uuid>
    python denoise_audio.py --batch --limit 10

Requirements:
    - deepfilternet package (pip install deepfilternet)
    - GPU recommended for faster processing
"""

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.data_utils import get_pg_connection, log_processing


# =============================================================================
# CONFIGURATION
# =============================================================================

# Audio settings (must match pipeline standard)
SAMPLE_RATE = 16000
AUDIO_FORMAT = "wav"

# DeepFilterNet settings
# Using DeepFilterNet3 (DF3) model - best quality/speed balance
DEEPFILTER_MODEL = "DeepFilterNet3"


# =============================================================================
# DENOISING FUNCTIONS
# =============================================================================

def load_deepfilter_model() -> Any:
    """
    Load DeepFilterNet model.

    Returns:
        DeepFilterNet model and df_state.

    Raises:
        ImportError: If deepfilternet is not installed.
    """
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio
    except ImportError as e:
        raise ImportError(
            "deepfilternet is required. Install with: pip install deepfilternet"
        ) from e

    print(f"[INFO] Loading DeepFilterNet model: {DEEPFILTER_MODEL}")
    model, df_state, _ = init_df()

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


def denoise_segments(
    segments: List[Dict[str, Any]],
    data_root: Path,
    output_root: Path,
    model: Any,
    df_state: Any
) -> List[Dict[str, Any]]:
    """
    Denoise all segments for a sample.

    Args:
        segments: List of segment dicts with audio_file_path.
        data_root: Root directory for input data.
        output_root: Root directory for denoised output.
        model: DeepFilterNet model.
        df_state: DeepFilterNet state.

    Returns:
        List of results for each segment.
    """
    results = []

    for segment in segments:
        segment_id = str(segment["segment_id"])
        input_path = data_root / segment["audio_file_path"]

        # Build output path (maintain same structure)
        relative_path = Path(segment["audio_file_path"])
        output_path = output_root / relative_path

        try:
            result = denoise_audio_file(input_path, output_path, model, df_state)
            result["segment_id"] = segment_id
            result["segment_index"] = segment.get("segment_index")
            result["success"] = True
            results.append(result)

            print(f"  Segment {segment.get('segment_index', '?')}: "
                  f"{result['duration_seconds']}s -> {result['processing_time_seconds']}s "
                  f"({result['realtime_factor']}x realtime)")

        except Exception as e:
            results.append({
                "segment_id": segment_id,
                "segment_index": segment.get("segment_index"),
                "success": False,
                "error": str(e)
            })
            print(f"  Segment {segment.get('segment_index', '?')}: FAILED - {e}")

    return results


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_denoising(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for denoising (translations reviewed).

    We denoise after translation review but before final state.
    State should be after TRANSLATION_REVIEW is complete.

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries with segment info.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get samples where translation has been reviewed
            # In this schema, we'll check for samples in TRANSLATION_REVIEW state
            # that have verified translations
            cur.execute(
                """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.audio_file_path,
                    s.duration_seconds,
                    (
                        SELECT json_agg(
                            json_build_object(
                                'segment_id', seg.segment_id,
                                'segment_index', seg.segment_index,
                                'audio_file_path', seg.audio_file_path,
                                'duration_ms', seg.duration_ms
                            ) ORDER BY seg.segment_index
                        )
                        FROM segments seg
                        WHERE seg.sample_id = s.sample_id
                          AND seg.is_verified = TRUE
                    ) AS segments
                FROM samples s
                WHERE s.processing_state = 'TRANSLATION_REVIEW'
                  AND s.is_deleted = FALSE
                  AND EXISTS (
                      SELECT 1 FROM segment_translations st
                      JOIN segments seg ON st.segment_id = seg.segment_id
                      WHERE seg.sample_id = s.sample_id
                        AND st.is_verified = TRUE
                  )
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_segment_paths(
    segment_results: List[Dict[str, Any]],
    executor: str = "denoise_audio"
) -> None:
    """
    Update segment audio paths after denoising.

    Note: In practice, you might want to keep both original and denoised paths.
    For now, we'll add a 'denoised_audio_path' or update the main path.

    Args:
        segment_results: List of denoising results.
        executor: Name of executor for logging.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            for result in segment_results:
                if not result.get("success"):
                    continue

                segment_id = result["segment_id"]
                denoised_path = result["output_path"]

                # Update segment with denoised path
                # Option 1: Replace audio_file_path
                # Option 2: Add to metadata (we'll use metadata approach)
                cur.execute(
                    """
                    UPDATE segments
                    SET audio_file_path = %s,
                        updated_at = NOW()
                    WHERE segment_id = %s
                    """,
                    (denoised_path, segment_id)
                )

            conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to update segment paths: {e}")
    finally:
        conn.close()


def transition_to_denoised(
    sample_id: str,
    denoising_metadata: Dict[str, Any],
    executor: str = "denoise_audio"
) -> None:
    """
    Transition sample to DENOISED state.

    Args:
        sample_id: UUID of the sample.
        denoising_metadata: Denoising processing metadata.
        executor: Name of executor for logging.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            # Update processing metadata
            cur.execute(
                """
                UPDATE samples 
                SET processing_metadata = processing_metadata || %s
                WHERE sample_id = %s
                """,
                (Json({"deepfilternet": denoising_metadata}), sample_id)
            )

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'DENOISED'::processing_state, %s)",
                (sample_id, executor)
            )

            conn.commit()

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to transition state: {e}")
    finally:
        conn.close()


def process_sample(
    sample: Dict[str, Any],
    model: Any,
    df_state: Any,
    data_root: Path,
    output_root: Path
) -> bool:
    """
    Process a single sample for denoising.

    Args:
        sample: Sample dictionary from database.
        model: DeepFilterNet model.
        df_state: DeepFilterNet state.
        data_root: Root directory for input data.
        output_root: Root directory for denoised output.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    segments = sample.get("segments") or []

    print(f"\n{'='*60}")
    print(f"Processing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Segments: {len(segments)}")
    print(f"{'='*60}")

    if not segments:
        print(f"[SKIP] No verified segments found")
        return False

    start_time = time.time()

    try:
        # Denoise all segments
        print(f"[INFO] Denoising {len(segments)} segments...")
        results = denoise_segments(
            segments=segments,
            data_root=data_root,
            output_root=output_root,
            model=model,
            df_state=df_state
        )

        # Check results
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]

        if not successful:
            raise ValueError(f"All {len(results)} segments failed to denoise")

        if failed:
            print(f"[WARNING] {len(failed)} segments failed")

        # Update database
        print(f"[INFO] Updating segment paths in database...")
        update_segment_paths(successful)

        # Calculate aggregate stats
        total_audio_duration = sum(r.get("duration_seconds", 0) for r in successful)
        total_processing_time = sum(r.get("processing_time_seconds", 0) for r in successful)
        avg_realtime = total_audio_duration / total_processing_time if total_processing_time > 0 else 0

        denoising_metadata = {
            "model": DEEPFILTER_MODEL,
            "segments_processed": len(successful),
            "segments_failed": len(failed),
            "total_audio_duration_seconds": round(total_audio_duration, 2),
            "total_processing_time_seconds": round(total_processing_time, 2),
            "average_realtime_factor": round(avg_realtime, 2)
        }

        # Transition state
        print(f"[INFO] Transitioning to DENOISED state...")
        transition_to_denoised(sample_id, denoising_metadata)

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log success
        log_processing(
            operation="deepfilternet_denoising",
            success=True,
            sample_id=sample_id,
            previous_state="TRANSLATION_REVIEW",
            new_state="DENOISED",
            executor="denoise_audio",
            execution_time_ms=execution_time_ms,
            input_params={
                "segment_count": len(segments),
                "model": DEEPFILTER_MODEL
            },
            output_summary=denoising_metadata
        )

        print(f"[SUCCESS] Denoised {external_id}")
        print(f"  Segments: {len(successful)}/{len(segments)}")
        print(f"  Audio: {total_audio_duration:.1f}s")
        print(f"  Processing: {total_processing_time:.1f}s ({avg_realtime:.1f}x realtime)")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="deepfilternet_denoising",
            success=False,
            sample_id=sample_id,
            previous_state="TRANSLATION_REVIEW",
            executor="denoise_audio",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to denoise {external_id}: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for denoising."""
    parser = argparse.ArgumentParser(
        description="Remove background noise from audio using DeepFilterNet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Denoise a specific sample
    python denoise_audio.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of samples
    python denoise_audio.py --batch --limit 10

    # Specify directories
    python denoise_audio.py --batch --data-root /app/data --output-root /app/data/denoised
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to denoise"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples with verified translations"
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
        help="Root directory for input data files (default: /app/data)"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for denoised output (default: same as data-root)"
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

    # Resolve paths
    data_root = args.data_root
    if not data_root.exists():
        data_root = Path(__file__).parent.parent.parent / "data"

    output_root = args.output_root or data_root
    if not output_root.exists():
        output_root.mkdir(parents=True, exist_ok=True)

    print(f"Data root: {data_root.absolute()}")
    print(f"Output root: {output_root.absolute()}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_denoising(limit=args.limit)
        print(f"Found {len(samples)} samples ready for denoising:")
        for s in samples:
            segment_count = len(s.get("segments") or [])
            print(f"  - {s['external_id']}: {s['duration_seconds']:.1f}s, {segment_count} segments")
        return

    # Load model
    print("\n[INFO] Loading DeepFilterNet model...")
    model, df_state = load_deepfilter_model()

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
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'segment_id', seg.segment_id,
                                    'segment_index', seg.segment_index,
                                    'audio_file_path', seg.audio_file_path,
                                    'duration_ms', seg.duration_ms
                                ) ORDER BY seg.segment_index
                            )
                            FROM segments seg
                            WHERE seg.sample_id = s.sample_id
                        ) AS segments
                    FROM samples s
                    WHERE s.sample_id = %s
                    """,
                    (args.sample_id,)
                )
                sample = cur.fetchone()
                if sample:
                    process_sample(dict(sample), model, df_state, data_root, output_root)
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_denoising(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(sample, model, df_state, data_root, output_root):
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

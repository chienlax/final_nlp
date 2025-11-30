#!/usr/bin/env python3
"""
Prepare Review Audio Script (v2 - Sample-level review).

Pre-cuts sentence audio files for Label Studio unified review workflow.
No chunking - loads entire sample with all sentences for review.

Pipeline Stage: TRANSLATED → REVIEW_PREPARED

Workflow:
1. Load sentence timestamps from transcript_revisions
2. Pre-cut sentence audio to data/review/{sample_id}/sentences/
3. Initialize sentence_reviews records with sentence_audio_path
4. Transition sample to REVIEW_PREPARED state

Usage:
    python prepare_review_audio.py --sample-id <uuid>
    python prepare_review_audio.py --batch --limit 10

Requirements:
    - pydub for audio slicing
    - Audio file in 16kHz mono WAV format
    - Gemini processing complete (sentence_timestamps in transcript_revisions)
"""

import argparse
import json
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

SAMPLE_RATE = 16000
AUDIO_FORMAT = "wav"
AUDIO_PADDING_MS = 200  # 0.2s padding before and after each sentence


# =============================================================================
# AUDIO FUNCTIONS
# =============================================================================

def load_audio(audio_path: Path) -> Any:
    """
    Load audio file using pydub.

    Args:
        audio_path: Path to audio file.

    Returns:
        AudioSegment object.

    Raises:
        ImportError: If pydub is not installed.
        FileNotFoundError: If audio file doesn't exist.
    """
    try:
        from pydub import AudioSegment
    except ImportError as e:
        raise ImportError(
            "pydub is required. Install with: pip install pydub"
        ) from e

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    return AudioSegment.from_wav(str(audio_path))


def cut_sentence_audio(
    audio: Any,
    start_ms: int,
    end_ms: int,
    output_path: Path,
    padding_ms: int = AUDIO_PADDING_MS
) -> Dict[str, Any]:
    """
    Cut a sentence from audio with padding.

    Args:
        audio: AudioSegment object.
        start_ms: Start time in milliseconds.
        end_ms: End time in milliseconds.
        output_path: Path to save the sentence audio.
        padding_ms: Padding to add before and after.

    Returns:
        Dictionary with result info.
    """
    audio_duration_ms = len(audio)

    # Add padding
    padded_start = max(0, start_ms - padding_ms)
    padded_end = min(audio_duration_ms, end_ms + padding_ms)

    # Cut the segment
    segment = audio[padded_start:padded_end]

    # Export
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment.export(str(output_path), format=AUDIO_FORMAT)

    return {
        "success": True,
        "output_path": str(output_path),
        "original_start_ms": start_ms,
        "original_end_ms": end_ms,
        "padded_start_ms": padded_start,
        "padded_end_ms": padded_end,
        "duration_ms": padded_end - padded_start,
        "file_size_bytes": output_path.stat().st_size
    }


def prepare_sentence_audio_files(
    audio: Any,
    sentences: List[Dict[str, Any]],
    output_dir: Path,
    padding_ms: int = AUDIO_PADDING_MS
) -> List[Dict[str, Any]]:
    """
    Pre-cut all sentence audio files for a sample.

    Args:
        audio: Loaded AudioSegment object.
        sentences: List of sentence dictionaries with start/end times.
        output_dir: Directory to save sentence audio files.
        padding_ms: Padding to add before and after each sentence.

    Returns:
        List of result dictionaries for each sentence.
    """
    results = []
    sentences_dir = output_dir / "sentences"
    sentences_dir.mkdir(parents=True, exist_ok=True)

    for idx, sentence in enumerate(sentences):
        start_ms = int(sentence.get("start", 0) * 1000)
        end_ms = int(sentence.get("end", 0) * 1000)

        if end_ms <= start_ms:
            results.append({
                "success": False,
                "sentence_idx": idx,
                "error": "Invalid time range"
            })
            continue

        output_path = sentences_dir / f"{idx:04d}.wav"

        try:
            result = cut_sentence_audio(
                audio=audio,
                start_ms=start_ms,
                end_ms=end_ms,
                output_path=output_path,
                padding_ms=padding_ms
            )
            result["sentence_idx"] = idx
            results.append(result)

            if (idx + 1) % 50 == 0 or idx == 0:
                print(f"  Processed {idx + 1}/{len(sentences)} sentences...")

        except Exception as e:
            results.append({
                "success": False,
                "sentence_idx": idx,
                "error": str(e)
            })

    return results


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_review_prep(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for review preparation (in TRANSLATED state).

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries.
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
                    s.source_metadata->>'title' AS video_title,
                    COALESCE(src.channel_name, src.name) AS channel_name,
                    tr.revision_id AS transcript_revision_id,
                    tr.sentence_timestamps
                FROM samples s
                LEFT JOIN sources src ON s.source_id = src.source_id
                JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                WHERE s.processing_state = 'TRANSLATED'
                  AND s.is_deleted = FALSE
                  AND tr.sentence_timestamps IS NOT NULL
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    finally:
        conn.close()


def init_sentence_reviews(
    sample_id: str,
    sentences: List[Dict[str, Any]],
    review_dir: Path
) -> int:
    """
    Initialize sentence_reviews records for all sentences in a sample.

    Args:
        sample_id: UUID of the sample.
        sentences: List of sentence dictionaries.
        review_dir: Path to review audio directory.

    Returns:
        Number of sentence reviews created.
    """
    conn = get_pg_connection()
    count = 0

    try:
        with conn.cursor() as cur:
            # Delete existing reviews for this sample (re-preparation)
            cur.execute(
                "DELETE FROM sentence_reviews WHERE sample_id = %s",
                (sample_id,)
            )

            for idx, sentence in enumerate(sentences):
                # Build sentence audio path (relative)
                sentence_audio_path = f"review/{sample_id}/sentences/{idx:04d}.wav"

                cur.execute(
                    """
                    INSERT INTO sentence_reviews (
                        sample_id, sentence_idx,
                        original_start_ms, original_end_ms,
                        original_transcript, original_translation,
                        sentence_audio_path
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        sample_id,
                        idx,
                        int(sentence["start"] * 1000),
                        int(sentence["end"] * 1000),
                        sentence.get("text", ""),
                        sentence.get("translation", ""),
                        sentence_audio_path
                    )
                )
                count += 1

            conn.commit()
            return count

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to initialize sentence reviews: {e}")
    finally:
        conn.close()


def transition_to_review_prepared(
    sample_id: str,
    prep_metadata: Dict[str, Any],
    executor: str = "prepare_review_audio"
) -> None:
    """
    Transition sample to REVIEW_PREPARED state.

    Args:
        sample_id: UUID of the sample.
        prep_metadata: Preparation metadata.
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
                (Json({"review_prep": prep_metadata}), sample_id)
            )

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'REVIEW_PREPARED'::processing_state, %s)",
                (sample_id, executor)
            )

            conn.commit()

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to transition state: {e}")
    finally:
        conn.close()


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_sample(
    sample: Dict[str, Any],
    data_root: Path,
    review_root: Path
) -> bool:
    """
    Process a single sample for review preparation.

    Args:
        sample: Sample dictionary from database.
        data_root: Root directory for input audio files.
        review_root: Root directory for review audio output.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    video_title = sample.get("video_title", external_id)

    # Handle audio_file_path: strip leading 'data/' if present
    audio_file_path = sample["audio_file_path"]
    if audio_file_path.startswith("data/"):
        audio_file_path = audio_file_path[5:]
    audio_path = data_root / audio_file_path

    sentence_timestamps = sample["sentence_timestamps"]

    print(f"\n{'='*60}")
    print(f"Processing: {video_title[:50]}...")
    print(f"Sample ID: {sample_id}")
    print(f"External ID: {external_id}")
    print(f"Audio: {audio_path}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        # Parse sentence timestamps
        if isinstance(sentence_timestamps, str):
            sentence_timestamps = json.loads(sentence_timestamps)

        if not sentence_timestamps:
            raise ValueError("No sentence timestamps found")

        sentence_count = len(sentence_timestamps)
        print(f"[INFO] Found {sentence_count} sentences")

        # Create output directory
        output_dir = review_root / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load audio
        print(f"[INFO] Loading audio: {audio_path}")
        audio = load_audio(audio_path)
        audio_duration_ms = len(audio)
        print(f"[INFO] Audio duration: {audio_duration_ms / 1000:.1f}s")

        # Cut sentence audio files
        print(f"[INFO] Cutting sentence audio files...")
        audio_results = prepare_sentence_audio_files(
            audio=audio,
            sentences=sentence_timestamps,
            output_dir=output_dir,
            padding_ms=AUDIO_PADDING_MS
        )

        successful_cuts = [r for r in audio_results if r.get("success")]
        failed_cuts = [r for r in audio_results if not r.get("success")]

        if failed_cuts:
            print(f"  [WARNING] {len(failed_cuts)} sentences failed to cut")

        print(f"  Cut {len(successful_cuts)}/{sentence_count} sentences")

        # Initialize sentence reviews
        print(f"[INFO] Initializing sentence reviews...")
        reviews_count = init_sentence_reviews(
            sample_id=sample_id,
            sentences=sentence_timestamps,
            review_dir=output_dir
        )
        print(f"  Initialized {reviews_count} sentence reviews")

        # Transition to REVIEW_PREPARED
        prep_metadata = {
            "sentence_count": sentence_count,
            "audio_cuts_successful": len(successful_cuts),
            "audio_cuts_failed": len(failed_cuts),
            "output_dir": str(output_dir),
            "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        print(f"[INFO] Transitioning to REVIEW_PREPARED state...")
        transition_to_review_prepared(sample_id, prep_metadata)

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log success
        log_processing(
            operation="prepare_review_audio",
            success=True,
            sample_id=sample_id,
            previous_state="TRANSLATED",
            new_state="REVIEW_PREPARED",
            executor="prepare_review_audio",
            execution_time_ms=execution_time_ms,
            input_params={
                "audio_path": str(audio_path),
                "sentence_count": sentence_count
            },
            output_summary=prep_metadata
        )

        print(f"\n[SUCCESS] Prepared {external_id} for review")
        print(f"  Sentences: {sentence_count}")
        print(f"  Sentence audio files: {len(successful_cuts)}")
        print(f"  Output: {output_dir}")
        print(f"  Time: {execution_time_ms/1000:.2f}s")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="prepare_review_audio",
            success=False,
            sample_id=sample_id,
            previous_state="TRANSLATED",
            executor="prepare_review_audio",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to prepare {external_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for review preparation."""
    parser = argparse.ArgumentParser(
        description="Prepare sentence audio files for Label Studio unified review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Prepare a specific sample
    python prepare_review_audio.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of samples
    python prepare_review_audio.py --batch --limit 10

    # Specify directories
    python prepare_review_audio.py --batch --data-root /app/data --review-root /app/data/review
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to prepare"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in TRANSLATED state"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum samples to process in batch mode (default: 10)"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/app/data"),
        help="Root directory for input data files (default: /app/data)"
    )
    parser.add_argument(
        "--review-root",
        type=Path,
        default=None,
        help="Root directory for review audio output (default: data-root/review)"
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

    review_root = args.review_root or (data_root / "review")
    review_root.mkdir(parents=True, exist_ok=True)

    print(f"Data root: {data_root.absolute()}")
    print(f"Review root: {review_root.absolute()}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_review_prep(limit=args.limit)
        print(f"Found {len(samples)} samples ready for review preparation:")
        for s in samples:
            sentences = s.get("sentence_timestamps") or []
            if isinstance(sentences, str):
                sentences = json.loads(sentences)
            sentence_count = len(sentences)
            print(f"  - {s['external_id']}: {s['duration_seconds']:.1f}s, {sentence_count} sentences")
        return

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
                        s.source_metadata->>'title' AS video_title,
                        tr.sentence_timestamps
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
                    process_sample(dict(sample), data_root, review_root)
                else:
                    print(f"Sample not found: {args.sample_id}")
                    sys.exit(1)
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_review_prep(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process\n")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(dict(sample), data_root, review_root):
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

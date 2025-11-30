#!/usr/bin/env python3
"""
Apply Review Script.

Applies corrections from unified review to create final audio/transcript/translation.
Re-cuts audio with corrected boundaries, writes final versions, and cleans up review files.

Pipeline Stage: VERIFIED → FINAL

Workflow:
1. Load sentence reviews with corrections from database
2. Apply corrected timestamps to re-cut audio
3. Save final audio to data/final/{sample_id}/sentences/
4. Create final transcript and translation revisions
5. Clean up review audio files (data/review/{sample_id}/)
6. Transition sample to FINAL state

Usage:
    python apply_review.py --sample-id <uuid>
    python apply_review.py --batch --limit 10
    python apply_review.py --batch --skip-cleanup

Requirements:
    - pydub for audio slicing
    - Completed review (all chunks in 'completed' status)
"""

import argparse
import json
import shutil
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

# Audio settings
SAMPLE_RATE = 16000
AUDIO_FORMAT = "wav"
AUDIO_PADDING_MS = 200  # 0.2s padding before and after each sentence


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_verified_samples(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for final processing (VERIFIED state).

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
                    s.current_transcript_version,
                    s.current_translation_version
                FROM samples s
                WHERE s.processing_state = 'VERIFIED'
                  AND s.is_deleted = FALSE
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_reviewed_sentences(sample_id: str) -> List[Dict[str, Any]]:
    """
    Get all sentence reviews for a sample with final values.

    Args:
        sample_id: UUID of the sample.

    Returns:
        List of sentence dictionaries with corrected values.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    sr.sentence_idx,
                    sr.original_start_ms,
                    sr.original_end_ms,
                    sr.original_transcript,
                    sr.original_translation,
                    sr.reviewed_start_ms,
                    sr.reviewed_end_ms,
                    sr.reviewed_transcript,
                    sr.reviewed_translation,
                    sr.is_boundary_adjusted,
                    sr.is_transcript_corrected,
                    sr.is_translation_corrected,
                    sr.is_rejected
                FROM sentence_reviews sr
                WHERE sr.sample_id = %s
                ORDER BY sr.sentence_idx ASC
                """,
                (sample_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_review_statistics(sample_id: str) -> Dict[str, int]:
    """
    Get review statistics for a sample.

    Args:
        sample_id: UUID of the sample.

    Returns:
        Statistics dictionary.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    COUNT(*) AS total_sentences,
                    COUNT(*) FILTER (WHERE is_rejected) AS rejected_sentences,
                    COUNT(*) FILTER (WHERE is_boundary_adjusted) AS boundary_adjusted,
                    COUNT(*) FILTER (WHERE is_transcript_corrected) AS transcript_corrected,
                    COUNT(*) FILTER (WHERE is_translation_corrected) AS translation_corrected
                FROM sentence_reviews
                WHERE sample_id = %s
                """,
                (sample_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else {}
    finally:
        conn.close()


def create_final_revisions(
    sample_id: str,
    sentences: List[Dict[str, Any]],
    executor: str = "apply_review"
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create final transcript and translation revisions.

    Args:
        sample_id: UUID of the sample.
        sentences: List of final sentence data.
        executor: Name of executor for logging.

    Returns:
        Tuple of (transcript_revision_id, translation_revision_id).
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            # Build sentence timestamps for transcript revision
            sentence_timestamps = []
            for sent in sentences:
                if sent.get('is_rejected'):
                    continue  # Skip rejected sentences
                
                sentence_timestamps.append({
                    'text': sent.get('final_transcript'),
                    'translation': sent.get('final_translation'),
                    'start': sent.get('final_start_ms', 0) / 1000.0,
                    'end': sent.get('final_end_ms', 0) / 1000.0,
                    'duration': (sent.get('final_end_ms', 0) - sent.get('final_start_ms', 0)) / 1000.0,
                })

            # Build full transcript text
            full_transcript = ' '.join(
                sent['text'] for sent in sentence_timestamps if sent.get('text')
            )
            
            # Build full translation text
            full_translation = ' '.join(
                sent['translation'] for sent in sentence_timestamps if sent.get('translation')
            )

            # Create transcript revision
            cur.execute(
                """
                SELECT add_transcript_revision(
                    %s, %s, %s, %s, NULL, %s, %s
                )
                """,
                (
                    sample_id,
                    full_transcript,
                    'human_reviewed',
                    executor,
                    Json(sentence_timestamps),
                    executor
                )
            )
            transcript_rev_id = cur.fetchone()[0]

            # Create translation revision
            cur.execute(
                """
                SELECT add_translation_revision(
                    %s, %s, %s, %s, %s, %s, NULL, NULL, %s
                )
                """,
                (
                    sample_id,
                    full_translation,
                    'human_reviewed',
                    transcript_rev_id,
                    Json([{
                        'source': sent['text'],
                        'translation': sent['translation']
                    } for sent in sentence_timestamps]),
                    executor,
                    executor
                )
            )
            translation_rev_id = cur.fetchone()[0]

            conn.commit()
            return str(transcript_rev_id), str(translation_rev_id)

    except psycopg2.Error as e:
        conn.rollback()
        print(f"Error creating revisions: {e}")
        return None, None
    finally:
        conn.close()


def transition_to_final(
    sample_id: str,
    apply_metadata: Dict[str, Any],
    executor: str = "apply_review"
) -> None:
    """
    Transition sample to FINAL state.

    Args:
        sample_id: UUID of the sample.
        apply_metadata: Processing metadata.
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
                (Json({"apply_review": apply_metadata}), sample_id)
            )

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'FINAL'::processing_state, %s)",
                (sample_id, executor)
            )

            conn.commit()

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to transition state: {e}")
    finally:
        conn.close()


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


def cut_final_audio(
    audio: Any,
    sentences: List[Dict[str, Any]],
    output_dir: Path,
    padding_ms: int = AUDIO_PADDING_MS
) -> List[Dict[str, Any]]:
    """
    Cut final audio files for all non-rejected sentences.

    Args:
        audio: AudioSegment object.
        sentences: List of sentence data with final timestamps.
        output_dir: Directory to save final audio files.
        padding_ms: Padding in milliseconds.

    Returns:
        List of cut metadata.
    """
    audio_duration_ms = len(audio)
    sentences_dir = output_dir / "sentences"
    sentences_dir.mkdir(parents=True, exist_ok=True)

    results = []
    final_idx = 0  # Renumber excluding rejected

    for sent in sentences:
        if sent.get('is_rejected'):
            results.append({
                'original_idx': sent['sentence_idx'],
                'rejected': True
            })
            continue

        start_ms = sent['final_start_ms']
        end_ms = sent['final_end_ms']

        # Apply padding
        padded_start = max(0, start_ms - padding_ms)
        padded_end = min(audio_duration_ms, end_ms + padding_ms)

        # Extract segment
        segment = audio[padded_start:padded_end]
        segment = segment.set_frame_rate(SAMPLE_RATE).set_channels(1)

        # Save with new index
        output_path = sentences_dir / f"{final_idx:04d}.{AUDIO_FORMAT}"
        segment.export(str(output_path), format=AUDIO_FORMAT)

        results.append({
            'original_idx': sent['sentence_idx'],
            'final_idx': final_idx,
            'start_ms': start_ms,
            'end_ms': end_ms,
            'duration_ms': end_ms - start_ms,
            'output_path': str(output_path),
            'rejected': False
        })

        final_idx += 1

    return results


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_sample(
    sample: Dict[str, Any],
    data_root: Path,
    review_root: Path,
    final_root: Path,
    skip_cleanup: bool = False
) -> bool:
    """
    Process a single sample to apply review corrections.

    Args:
        sample: Sample dictionary from database.
        data_root: Root directory for raw audio files.
        review_root: Root directory for review audio (cleanup source).
        final_root: Root directory for final audio output.
        skip_cleanup: If True, don't delete review files.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample['sample_id'])
    external_id = sample['external_id']
    video_title = sample.get('video_title', external_id)
    audio_path = data_root / sample['audio_file_path']

    print(f"\n{'='*60}")
    print(f"Applying review: {video_title[:50]}...")
    print(f"Sample ID: {sample_id}")
    print(f"External ID: {external_id}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        # Get review statistics
        stats = get_review_statistics(sample_id)
        print(f"[INFO] Review statistics:")
        print(f"  Total sentences: {stats.get('total_sentences', 0)}")
        print(f"  Rejected: {stats.get('rejected_sentences', 0)}")
        print(f"  Boundary adjusted: {stats.get('boundary_adjusted', 0)}")
        print(f"  Transcript corrected: {stats.get('transcript_corrected', 0)}")
        print(f"  Translation corrected: {stats.get('translation_corrected', 0)}")

        # Get reviewed sentences
        sentences = get_reviewed_sentences(sample_id)
        if not sentences:
            raise ValueError("No sentence reviews found")

        # Prepare final values (use corrected if available, else original)
        for sent in sentences:
            sent['final_start_ms'] = (
                sent['reviewed_start_ms'] 
                if sent['reviewed_start_ms'] is not None 
                else sent['original_start_ms']
            )
            sent['final_end_ms'] = (
                sent['reviewed_end_ms'] 
                if sent['reviewed_end_ms'] is not None 
                else sent['original_end_ms']
            )
            sent['final_transcript'] = (
                sent['reviewed_transcript'] 
                if sent['reviewed_transcript'] 
                else sent['original_transcript']
            )
            sent['final_translation'] = (
                sent['reviewed_translation'] 
                if sent['reviewed_translation'] 
                else sent['original_translation']
            )

        # Count non-rejected sentences
        valid_sentences = [s for s in sentences if not s.get('is_rejected')]
        print(f"[INFO] Valid sentences for final: {len(valid_sentences)}")

        # Create output directory
        output_dir = final_root / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load and cut final audio
        print(f"[INFO] Loading audio: {audio_path}")
        audio = load_audio(audio_path)

        print(f"[INFO] Cutting final audio files...")
        cut_results = cut_final_audio(
            audio=audio,
            sentences=sentences,
            output_dir=output_dir,
            padding_ms=AUDIO_PADDING_MS
        )

        successful_cuts = [r for r in cut_results if not r.get('rejected') and r.get('output_path')]
        print(f"  Created {len(successful_cuts)} final audio files")

        # Create final transcript and translation revisions
        print(f"[INFO] Creating final revisions...")
        transcript_rev_id, translation_rev_id = create_final_revisions(
            sample_id=sample_id,
            sentences=sentences
        )

        if not transcript_rev_id or not translation_rev_id:
            raise ValueError("Failed to create final revisions")

        print(f"  Transcript revision: {transcript_rev_id}")
        print(f"  Translation revision: {translation_rev_id}")

        # Clean up review files
        review_dir = review_root / sample_id
        if not skip_cleanup and review_dir.exists():
            print(f"[INFO] Cleaning up review files: {review_dir}")
            shutil.rmtree(review_dir)
            print(f"  Deleted {review_dir}")
        elif skip_cleanup:
            print(f"[INFO] Skipping cleanup (--skip-cleanup flag)")

        # Prepare metadata
        apply_metadata = {
            'total_sentences': stats.get('total_sentences', 0),
            'rejected_sentences': stats.get('rejected_sentences', 0),
            'final_sentences': len(valid_sentences),
            'boundary_adjusted': stats.get('boundary_adjusted', 0),
            'transcript_corrected': stats.get('transcript_corrected', 0),
            'translation_corrected': stats.get('translation_corrected', 0),
            'transcript_revision_id': transcript_rev_id,
            'translation_revision_id': translation_rev_id,
            'output_dir': str(output_dir),
            'applied_at': time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        # Transition to FINAL
        print(f"[INFO] Transitioning to FINAL state...")
        transition_to_final(sample_id, apply_metadata)

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log success
        log_processing(
            operation="apply_review",
            success=True,
            sample_id=sample_id,
            previous_state="VERIFIED",
            new_state="FINAL",
            executor="apply_review",
            execution_time_ms=execution_time_ms,
            input_params={
                'audio_path': str(audio_path),
                'sentence_count': len(sentences)
            },
            output_summary=apply_metadata
        )

        print(f"\n[SUCCESS] Applied review for {external_id}")
        print(f"  Final sentences: {len(valid_sentences)}")
        print(f"  Output: {output_dir}")
        print(f"  Time: {execution_time_ms/1000:.2f}s")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="apply_review",
            success=False,
            sample_id=sample_id,
            previous_state="VERIFIED",
            executor="apply_review",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to apply review for {external_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for apply review."""
    parser = argparse.ArgumentParser(
        description="Apply review corrections and create final audio/transcript/translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Apply review for a specific sample
    python apply_review.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of verified samples
    python apply_review.py --batch --limit 10

    # Keep review files (don't delete)
    python apply_review.py --batch --skip-cleanup

    # Specify directories
    python apply_review.py --batch --data-root /app/data --final-root /app/data/final
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to process"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in VERIFIED state"
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
        help="Root directory for raw data files (default: /app/data)"
    )
    parser.add_argument(
        "--review-root",
        type=Path,
        default=None,
        help="Root directory for review audio (default: data-root/review)"
    )
    parser.add_argument(
        "--final-root",
        type=Path,
        default=None,
        help="Root directory for final audio output (default: data-root/final)"
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Don't delete review files after applying"
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
    final_root = args.final_root or (data_root / "final")
    final_root.mkdir(parents=True, exist_ok=True)

    print(f"Data root: {data_root.absolute()}")
    print(f"Review root: {review_root.absolute()}")
    print(f"Final root: {final_root.absolute()}")
    print(f"Skip cleanup: {args.skip_cleanup}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_verified_samples(limit=args.limit)
        print(f"Found {len(samples)} samples ready for final processing:")
        for s in samples:
            stats = get_review_statistics(str(s['sample_id']))
            print(f"  - {s['external_id']}: {stats.get('total_sentences', 0)} sentences, "
                  f"{stats.get('rejected_sentences', 0)} rejected")
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
                        s.source_metadata->>'title' AS video_title
                    FROM samples s
                    WHERE s.sample_id = %s
                    """,
                    (args.sample_id,)
                )
                sample = cur.fetchone()
                if sample:
                    process_sample(
                        dict(sample), data_root, review_root, final_root, args.skip_cleanup
                    )
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_verified_samples(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(sample, data_root, review_root, final_root, args.skip_cleanup):
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

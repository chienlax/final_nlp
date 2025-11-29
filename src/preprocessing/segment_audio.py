#!/usr/bin/env python3
"""
Audio Segmentation Script.

Segments aligned audio into 10-30s chunks based on sentence timestamps.
Creates segment records in the database with word-level alignment data.

Pipeline Stage: ALIGNED → SEGMENTED

Strategy:
1. Group sentences to fit 10-30s target duration
2. Prefer sentence boundaries for clean cuts
3. Split long sentences at word boundaries if needed
4. Store segment metadata and transcript in database

Usage:
    python segment_audio.py --sample-id <uuid>
    python segment_audio.py --batch --limit 10

Requirements:
    - pydub for audio slicing
    - Audio file in 16kHz mono WAV format
    - WhisperX alignment data in transcript_revisions
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

# Segmentation parameters
MIN_SEGMENT_DURATION_MS = 10_000  # 10 seconds
MAX_SEGMENT_DURATION_MS = 30_000  # 30 seconds
TARGET_SEGMENT_DURATION_MS = 20_000  # 20 seconds (preferred)

# Audio settings
SAMPLE_RATE = 16000
AUDIO_FORMAT = "wav"


# =============================================================================
# SEGMENTATION LOGIC
# =============================================================================

def group_sentences_into_segments(
    sentence_timestamps: List[Dict[str, Any]],
    min_duration_ms: int = MIN_SEGMENT_DURATION_MS,
    max_duration_ms: int = MAX_SEGMENT_DURATION_MS,
    target_duration_ms: int = TARGET_SEGMENT_DURATION_MS
) -> List[Dict[str, Any]]:
    """
    Group sentences into segments targeting 10-30s duration.

    Strategy:
    1. Add sentences until we exceed min_duration
    2. Stop when we exceed target_duration or can't fit more
    3. If single sentence exceeds max, split at word boundaries

    Args:
        sentence_timestamps: List of sentence dicts with start, end, text, words.
        min_duration_ms: Minimum segment duration in milliseconds.
        max_duration_ms: Maximum segment duration in milliseconds.
        target_duration_ms: Target segment duration in milliseconds.

    Returns:
        List of segment dicts with start_ms, end_ms, transcript, words.
    """
    if not sentence_timestamps:
        return []

    segments = []
    current_segment = {
        "start_ms": None,
        "end_ms": None,
        "sentences": [],
        "words": []
    }

    def finalize_segment():
        """Finalize current segment and reset."""
        nonlocal current_segment

        if not current_segment["sentences"]:
            return

        # Build transcript from sentences
        transcript = " ".join(s["text"].strip() for s in current_segment["sentences"])

        # Calculate average alignment score
        scores = [w.get("score", 0) for w in current_segment["words"] if w.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        segments.append({
            "start_ms": current_segment["start_ms"],
            "end_ms": current_segment["end_ms"],
            "transcript_text": transcript,
            "word_timestamps": current_segment["words"],
            "alignment_score": round(avg_score, 4)
        })

        # Reset
        current_segment = {
            "start_ms": None,
            "end_ms": None,
            "sentences": [],
            "words": []
        }

    for sentence in sentence_timestamps:
        sentence_start_ms = int(sentence["start"] * 1000)
        sentence_end_ms = int(sentence["end"] * 1000)
        sentence_duration_ms = sentence_end_ms - sentence_start_ms
        sentence_words = sentence.get("words", [])

        # Convert word timestamps to ms
        words_with_ms = [
            {
                "word": w["word"],
                "start": int(w["start"] * 1000),
                "end": int(w["end"] * 1000),
                "score": w.get("score", 0)
            }
            for w in sentence_words
        ]

        # Check if single sentence exceeds max duration
        if sentence_duration_ms > max_duration_ms:
            # Finalize current segment first
            finalize_segment()

            # Split long sentence at word boundaries
            split_segments = split_long_sentence(
                sentence, words_with_ms, max_duration_ms
            )
            segments.extend(split_segments)
            continue

        # Check if adding this sentence would exceed max
        if current_segment["start_ms"] is not None:
            potential_duration = sentence_end_ms - current_segment["start_ms"]

            # If exceeds max, finalize current and start new
            if potential_duration > max_duration_ms:
                finalize_segment()

            # If we're past target and adding would be too long
            current_duration = (current_segment["end_ms"] or 0) - (current_segment["start_ms"] or 0)
            if current_duration >= target_duration_ms:
                # Check if current segment meets minimum
                if current_duration >= min_duration_ms:
                    finalize_segment()

        # Add sentence to current segment
        if current_segment["start_ms"] is None:
            current_segment["start_ms"] = sentence_start_ms

        current_segment["end_ms"] = sentence_end_ms
        current_segment["sentences"].append(sentence)
        current_segment["words"].extend(words_with_ms)

    # Finalize last segment
    finalize_segment()

    # Handle any segments that are too short
    segments = merge_short_segments(segments, min_duration_ms, max_duration_ms)

    return segments


def split_long_sentence(
    sentence: Dict[str, Any],
    words_ms: List[Dict[str, Any]],
    max_duration_ms: int
) -> List[Dict[str, Any]]:
    """
    Split a sentence that exceeds max duration at word boundaries.

    Args:
        sentence: The sentence dict with text and timing.
        words_ms: Words with timestamps in milliseconds.
        max_duration_ms: Maximum segment duration.

    Returns:
        List of segment dicts.
    """
    if not words_ms:
        # No word-level data, create single segment
        return [{
            "start_ms": int(sentence["start"] * 1000),
            "end_ms": int(sentence["end"] * 1000),
            "transcript_text": sentence["text"],
            "word_timestamps": [],
            "alignment_score": 0.0
        }]

    segments = []
    current_words = []
    segment_start_ms = words_ms[0]["start"]

    for word in words_ms:
        word_end_ms = word["end"]
        current_duration = word_end_ms - segment_start_ms

        if current_duration > max_duration_ms and current_words:
            # Finalize current segment
            transcript = " ".join(w["word"] for w in current_words)
            scores = [w.get("score", 0) for w in current_words if w.get("score")]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            segments.append({
                "start_ms": segment_start_ms,
                "end_ms": current_words[-1]["end"],
                "transcript_text": transcript,
                "word_timestamps": current_words,
                "alignment_score": round(avg_score, 4)
            })

            # Start new segment
            current_words = [word]
            segment_start_ms = word["start"]
        else:
            current_words.append(word)

    # Finalize last segment
    if current_words:
        transcript = " ".join(w["word"] for w in current_words)
        scores = [w.get("score", 0) for w in current_words if w.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        segments.append({
            "start_ms": segment_start_ms,
            "end_ms": current_words[-1]["end"],
            "transcript_text": transcript,
            "word_timestamps": current_words,
            "alignment_score": round(avg_score, 4)
        })

    return segments


def merge_short_segments(
    segments: List[Dict[str, Any]],
    min_duration_ms: int,
    max_duration_ms: int
) -> List[Dict[str, Any]]:
    """
    Merge segments that are shorter than minimum duration.

    Args:
        segments: List of segment dicts.
        min_duration_ms: Minimum segment duration.
        max_duration_ms: Maximum segment duration.

    Returns:
        List of merged segments.
    """
    if len(segments) <= 1:
        return segments

    merged = []
    i = 0

    while i < len(segments):
        current = segments[i]
        current_duration = current["end_ms"] - current["start_ms"]

        # If current is too short and there's a next segment
        if current_duration < min_duration_ms and i + 1 < len(segments):
            next_seg = segments[i + 1]
            combined_duration = next_seg["end_ms"] - current["start_ms"]

            # Merge if combined doesn't exceed max
            if combined_duration <= max_duration_ms:
                merged_transcript = (
                    current["transcript_text"] + " " + next_seg["transcript_text"]
                )
                merged_words = current["word_timestamps"] + next_seg["word_timestamps"]
                scores = [w.get("score", 0) for w in merged_words if w.get("score")]
                avg_score = sum(scores) / len(scores) if scores else 0.0

                merged.append({
                    "start_ms": current["start_ms"],
                    "end_ms": next_seg["end_ms"],
                    "transcript_text": merged_transcript,
                    "word_timestamps": merged_words,
                    "alignment_score": round(avg_score, 4)
                })
                i += 2
                continue

        merged.append(current)
        i += 1

    return merged


# =============================================================================
# AUDIO SLICING
# =============================================================================

def slice_audio(
    audio_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path
) -> List[Path]:
    """
    Slice audio into segment files.

    Args:
        audio_path: Path to source audio file.
        segments: List of segment dicts with start_ms and end_ms.
        output_dir: Directory to save segment files.

    Returns:
        List of paths to created segment files.

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

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load audio
    print(f"[INFO] Loading audio: {audio_path}")
    audio = AudioSegment.from_wav(str(audio_path))

    segment_paths = []

    for idx, segment in enumerate(segments):
        start_ms = segment["start_ms"]
        end_ms = segment["end_ms"]

        # Extract segment
        segment_audio = audio[start_ms:end_ms]

        # Set export parameters (ensure 16kHz mono)
        segment_audio = segment_audio.set_frame_rate(SAMPLE_RATE)
        segment_audio = segment_audio.set_channels(1)

        # Save
        output_path = output_dir / f"{idx:04d}.{AUDIO_FORMAT}"
        segment_audio.export(
            str(output_path),
            format=AUDIO_FORMAT
        )

        segment_paths.append(output_path)
        print(f"  Segment {idx}: {start_ms}ms - {end_ms}ms -> {output_path.name}")

    return segment_paths


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_segmentation(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for segmentation (ALIGNED state).

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries with alignment data.
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
                    tr.transcript_text,
                    tr.sentence_timestamps
                FROM samples s
                JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                WHERE s.processing_state = 'ALIGNED'
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


def save_segments_to_database(
    sample_id: str,
    segments: List[Dict[str, Any]],
    segment_dir: Path,
    executor: str = "segment_audio"
) -> List[str]:
    """
    Save segments to database and transition sample state.

    Args:
        sample_id: UUID of the parent sample.
        segments: List of segment dicts.
        segment_dir: Directory where segment files are saved.
        executor: Name of executor for logging.

    Returns:
        List of segment UUIDs.

    Raises:
        Exception: If save fails.
    """
    conn = get_pg_connection()
    segment_ids = []

    try:
        with conn.cursor() as cur:
            for idx, segment in enumerate(segments):
                audio_file_path = str(segment_dir / f"{idx:04d}.{AUDIO_FORMAT}")

                cur.execute(
                    """
                    INSERT INTO segments (
                        sample_id,
                        segment_index,
                        start_time_ms,
                        end_time_ms,
                        audio_file_path,
                        word_timestamps,
                        transcript_text,
                        alignment_score
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING segment_id
                    """,
                    (
                        sample_id,
                        idx,
                        segment["start_ms"],
                        segment["end_ms"],
                        audio_file_path,
                        Json(segment["word_timestamps"]),
                        segment["transcript_text"],
                        segment["alignment_score"]
                    )
                )
                segment_id = cur.fetchone()[0]
                segment_ids.append(str(segment_id))

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'SEGMENTED'::processing_state, %s)",
                (sample_id, executor)
            )

            conn.commit()
            return segment_ids

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to save segments: {e}")
    finally:
        conn.close()


def process_sample(
    sample: Dict[str, Any],
    data_root: Path,
    segments_root: Path
) -> bool:
    """
    Process a single sample for segmentation.

    Args:
        sample: Sample dictionary from database.
        data_root: Root directory for input audio files.
        segments_root: Root directory for output segment files.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    audio_path = data_root / sample["audio_file_path"]
    sentence_timestamps = sample["sentence_timestamps"]

    print(f"\n{'='*60}")
    print(f"Processing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Audio: {audio_path}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        # Parse sentence timestamps
        if isinstance(sentence_timestamps, str):
            sentence_timestamps = json.loads(sentence_timestamps)

        if not sentence_timestamps:
            raise ValueError("No sentence timestamps found in alignment data")

        # Group sentences into segments
        print(f"[INFO] Grouping {len(sentence_timestamps)} sentences into segments...")
        segments = group_sentences_into_segments(sentence_timestamps)

        if not segments:
            raise ValueError("No segments created from sentence timestamps")

        print(f"[INFO] Created {len(segments)} segments")

        # Create output directory
        segment_dir = segments_root / sample_id
        segment_dir.mkdir(parents=True, exist_ok=True)

        # Slice audio
        print(f"[INFO] Slicing audio into segments...")
        slice_audio(audio_path, segments, segment_dir)

        # Save to database
        print(f"[INFO] Saving segments to database...")
        segment_ids = save_segments_to_database(
            sample_id=sample_id,
            segments=segments,
            segment_dir=segment_dir
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Calculate stats
        durations = [(s["end_ms"] - s["start_ms"]) / 1000 for s in segments]
        avg_duration = sum(durations) / len(durations)

        # Log success
        log_processing(
            operation="audio_segmentation",
            success=True,
            sample_id=sample_id,
            previous_state="ALIGNED",
            new_state="SEGMENTED",
            executor="segment_audio",
            execution_time_ms=execution_time_ms,
            input_params={
                "audio_path": str(audio_path),
                "sentence_count": len(sentence_timestamps)
            },
            output_summary={
                "segment_count": len(segments),
                "avg_duration_seconds": round(avg_duration, 2),
                "segment_ids": segment_ids[:5]  # First 5 for summary
            }
        )

        print(f"[SUCCESS] Segmented {external_id}")
        print(f"  Segments: {len(segments)}")
        print(f"  Avg duration: {avg_duration:.1f}s")
        print(f"  Time: {execution_time_ms/1000:.2f}s")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="audio_segmentation",
            success=False,
            sample_id=sample_id,
            previous_state="ALIGNED",
            executor="segment_audio",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to segment {external_id}: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for audio segmentation."""
    parser = argparse.ArgumentParser(
        description="Segment aligned audio into 10-30s chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Segment a specific sample
    python segment_audio.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of samples
    python segment_audio.py --batch --limit 10

    # Specify directories
    python segment_audio.py --batch --data-root /app/data --segments-root /app/data/segments
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to segment"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in ALIGNED state"
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
        "--segments-root",
        type=Path,
        default=Path("/app/data/segments"),
        help="Root directory for output segment files (default: /app/data/segments)"
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

    segments_root = args.segments_root
    if not segments_root.exists():
        segments_root = data_root / "segments"

    print(f"Data root: {data_root.absolute()}")
    print(f"Segments root: {segments_root.absolute()}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_segmentation(limit=args.limit)
        print(f"Found {len(samples)} samples ready for segmentation:")
        for s in samples:
            sentence_count = len(s["sentence_timestamps"] or [])
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
                        tr.revision_id AS transcript_revision_id,
                        tr.transcript_text,
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
                    process_sample(dict(sample), data_root, segments_root)
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_segmentation(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(sample, data_root, segments_root):
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

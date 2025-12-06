#!/usr/bin/env python3
"""
Audio chunking utility.

Splits long audio into ~10 minute chunks with 10s overlap and records chunk
metadata in SQLite (chunks table) so each chunk can be processed/reviewed
independently.

Usage:
    python chunk_audio.py --video-id <id>
    python chunk_audio.py --all

Notes:
    - Does not merge chunks; each chunk is independent.
    - Chunks are written under data/raw/chunks/<video_id>/chunk_<idx>.wav
    - Requires pydub and ffmpeg.
"""

import argparse
import logging
from pathlib import Path
from typing import List, Tuple

from pydub import AudioSegment

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    DEFAULT_DB_PATH,
    get_db,
    get_video,
    get_videos_by_state,
    insert_chunk,
    get_chunks_by_video,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_CHUNK_MS = 6 * 60 * 1000  # 6 minutes (adjusted to avoid Gemini hallucinations)
OVERLAP_MS = 5 * 1000         # 5 seconds

CHUNK_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "chunks"


def split_audio(audio: AudioSegment) -> List[Tuple[int, int]]:
    """Return list of (start_ms, end_ms) ranges with overlap."""
    length = len(audio)
    ranges = []
    start = 0
    while start < length:
        end = min(start + MAX_CHUNK_MS, length)
        ranges.append((start, end))
        if end == length:
            break
        start = end - OVERLAP_MS
    return ranges


def chunk_video(db_path: Path, video_id: str) -> None:
    video = get_video(video_id, db_path=db_path)
    if not video:
        logger.error("Video not found: %s", video_id)
        return

    audio_path = Path(__file__).parent.parent.parent / video["audio_path"]
    if not audio_path.exists():
        logger.error("Audio missing: %s", audio_path)
        return

    audio = AudioSegment.from_file(audio_path)
    ranges = split_audio(audio)

    out_dir = CHUNK_ROOT / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_chunks = get_chunks_by_video(video_id, db_path=db_path)
    if existing_chunks:
        logger.info("Chunks already exist for %s; skipping creation", video_id)
        return

    for idx, (start_ms, end_ms) in enumerate(ranges):
        chunk_audio = audio[start_ms:end_ms]
        out_path = out_dir / f"chunk_{idx}.wav"
        chunk_audio.export(out_path, format="wav")
        insert_chunk(
            video_id=video_id,
            chunk_index=idx,
            start_ms=start_ms,
            end_ms=end_ms,
            audio_path=str(out_path.relative_to(Path(__file__).parent.parent.parent)),
            processing_state="pending",
            db_path=db_path,
        )
        logger.info("Chunk %s written: %s", idx, out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk audio into ~10m slices with overlap")
    parser.add_argument("--video-id", dest="video_id", help="Process a single video id")
    parser.add_argument("--all", action="store_true", help="Process all videos in pending state")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite DB")
    args = parser.parse_args()

    targets: List[str] = []
    if args.video_id:
        targets = [args.video_id]
    elif args.all:
        pending = get_videos_by_state("pending", db_path=args.db)
        targets = [v["video_id"] for v in pending]
    else:
        parser.error("Provide --video-id or --all")

    for vid in targets:
        chunk_video(args.db, vid)


if __name__ == "__main__":
    main()

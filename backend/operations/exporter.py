"""
Dataset Exporter - Operations Layer.

Exports approved segments as individual audio clips for training.
Uses the "300-Second Guillotine" rule to prevent duplicate data from overlaps.

Output:
    - Individual WAV clips: export/video_{id}/segment_{nnnnn}.wav
    - manifest.tsv: id, video_id, audio_path, duration, transcript, translation

The 300-Second Guillotine Rule:
    - Each chunk is only allowed to export segments that START before 300 seconds.
    - Segments starting at 300s+ exist in the next chunk's first 5 seconds.
    - This eliminates duplicate data without complex stitching logic.

Usage:
    python -m backend.operations.exporter --video-id 1
    python -m backend.operations.exporter --all
"""

import csv
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session, select
from tqdm import tqdm

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Video, Chunk, Segment, ProcessingStatus


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

CHUNK_DURATION = 300  # 5 minutes in seconds (guillotine cutoff)
SAMPLE_RATE = 16000   # 16kHz (standard for ASR)
CHANNELS = 1          # Mono

EXPORT_DIR = DATA_ROOT / "export"

# Windows needs full path for executables in subprocess
IS_WINDOWS = platform.system() == "Windows"


def _find_executable(name: str) -> str:
    """Find executable, checking PATH and common locations."""
    path = shutil.which(name)
    if path:
        return path
    
    if IS_WINDOWS:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            ffmpeg_dir = Path(ffmpeg_path).parent
            candidate = ffmpeg_dir / f"{name}.exe"
            if candidate.exists():
                return str(candidate)
    
    return name  # Fallback to just the name


FFMPEG = _find_executable("ffmpeg")


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExportedSegment:
    """Segment ready for export as individual audio clip."""
    segment_id: int
    video_id: int
    chunk_audio_path: str   # Source chunk file (relative to DATA_ROOT)
    start_time_relative: float
    end_time_relative: float
    duration: float
    transcript: str
    translation: str
    export_path: str = ""   # Output clip path (set after cutting)


@dataclass
class ExportResult:
    """Result of an export operation."""
    videos_processed: int = 0
    segments_exported: int = 0
    segments_failed: int = 0
    total_hours: float = 0.0
    failed_segments: List[str] = field(default_factory=list)


# =============================================================================
# AUDIO CUTTING
# =============================================================================

def cut_audio_segment(
    source_path: Path,
    output_path: Path,
    start_time: float,
    duration: float
) -> bool:
    """
    Cut a segment from source audio file using FFmpeg.
    
    Args:
        source_path: Path to source audio file (chunk)
        output_path: Path for output audio clip
        start_time: Start time in seconds (relative to source)
        duration: Duration in seconds
        
    Returns:
        True if successful, False otherwise
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        FFMPEG, "-y",
        "-i", str(source_path),
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-ac", str(CHANNELS),
        "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg failed for {output_path.name}: {result.stderr[:200]}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"FFmpeg exception for {output_path.name}: {e}")
        return False


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def export_video(video_id: int, session: Session) -> tuple[List[ExportedSegment], List[str]]:
    """
    Export all approved segments for a video using the 300-second guillotine rule.
    
    Args:
        video_id: ID of the video to export
        session: Database session
        
    Returns:
        Tuple of (exported_segments, failed_segment_descriptions)
    """
    # Get video
    video = session.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    # Get all approved chunks
    chunks = session.exec(
        select(Chunk)
        .where(Chunk.video_id == video_id)
        .where(Chunk.status == ProcessingStatus.APPROVED)
        .order_by(Chunk.chunk_index)
    ).all()
    
    if not chunks:
        logger.warning(f"No approved chunks for video {video_id}")
        return [], []
    
    logger.info(f"Exporting video {video_id}: {len(chunks)} approved chunks")
    
    # Collect all eligible segments
    eligible_segments: List[ExportedSegment] = []
    
    for chunk in chunks:
        # Query segments with:
        # 1. is_rejected == False (exclude rejected segments)
        # 2. start_time_relative < 300 (guillotine rule)
        segments = session.exec(
            select(Segment)
            .where(Segment.chunk_id == chunk.id)
            .where(Segment.is_rejected == False)  # noqa: E712
            .where(Segment.start_time_relative < CHUNK_DURATION)
            .order_by(Segment.start_time_relative)
        ).all()
        
        for seg in segments:
            exported = ExportedSegment(
                segment_id=seg.id,
                video_id=video_id,
                chunk_audio_path=chunk.audio_path,
                start_time_relative=seg.start_time_relative,
                end_time_relative=seg.end_time_relative,
                duration=seg.end_time_relative - seg.start_time_relative,
                transcript=seg.transcript,
                translation=seg.translation,
            )
            eligible_segments.append(exported)
    
    logger.info(f"  Found {len(eligible_segments)} eligible segments (after guillotine + rejection filter)")
    
    # Cut each segment into individual audio clip
    video_export_dir = EXPORT_DIR / f"video_{video_id}"
    exported_segments: List[ExportedSegment] = []
    failed_segments: List[str] = []
    
    # Sequential counter for filenames (5 digits, 00001 - 99999)
    segment_counter = 1
    
    for seg in tqdm(eligible_segments, desc=f"Cutting video_{video_id}", unit="seg"):
        source_path = DATA_ROOT / seg.chunk_audio_path
        output_filename = f"segment_{segment_counter:05d}.wav"
        output_path = video_export_dir / output_filename
        
        success = cut_audio_segment(
            source_path=source_path,
            output_path=output_path,
            start_time=seg.start_time_relative,
            duration=seg.duration
        )
        
        if success:
            # Store relative path for manifest
            seg.export_path = str(output_path.relative_to(DATA_ROOT))
            exported_segments.append(seg)
            segment_counter += 1
        else:
            failed_desc = f"segment_id={seg.segment_id}, chunk={seg.chunk_audio_path}, start={seg.start_time_relative:.2f}s"
            failed_segments.append(failed_desc)
    
    return exported_segments, failed_segments


def write_manifest(segments: List[ExportedSegment], output_path: Path) -> None:
    """
    Write segments to TSV manifest file.
    
    Format: id, video_id, audio_path, duration, transcript, translation
    (No start/end columns - each clip is self-contained)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t')
        
        # Header
        writer.writerow([
            'id', 'video_id', 'audio_path', 
            'duration', 'transcript', 'translation'
        ])
        
        # Data rows
        for seg in segments:
            writer.writerow([
                seg.segment_id,
                seg.video_id,
                seg.export_path,
                f"{seg.duration:.3f}",
                seg.transcript,
                seg.translation,
            ])
    
    logger.info(f"Wrote manifest: {output_path} ({len(segments)} entries)")


def export_all_approved() -> ExportResult:
    """
    Export all videos with approved chunks.
    
    Returns:
        ExportResult with statistics
    """
    result = ExportResult()
    
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    with Session(engine) as session:
        # Find all videos with at least one approved chunk
        videos = session.exec(select(Video)).all()
        
        all_segments: List[ExportedSegment] = []
        
        for video in videos:
            try:
                segments, failed = export_video(video.id, session)
                if segments:
                    all_segments.extend(segments)
                    result.videos_processed += 1
                
                if failed:
                    result.failed_segments.extend(failed)
                    result.segments_failed += len(failed)
                    
            except Exception as e:
                logger.error(f"Failed to export video {video.id}: {e}")
                result.failed_segments.append(f"video_{video.id}: {str(e)}")
        
        # Write combined manifest
        if all_segments:
            manifest_path = EXPORT_DIR / "manifest.tsv"
            write_manifest(all_segments, manifest_path)
            result.segments_exported = len(all_segments)
            
            # Calculate total duration
            total_duration = sum(s.duration for s in all_segments)
            hours = total_duration / 3600
            result.total_hours = round(hours, 2)
            
            logger.info(f"Total exported: {result.total_hours:.2f} hours of audio")
    
    # Log any failures
    if result.failed_segments:
        logger.warning(f"Failed to export {result.segments_failed} segments:")
        for fail in result.failed_segments[:10]:  # Show first 10
            logger.warning(f"  - {fail}")
        if len(result.failed_segments) > 10:
            logger.warning(f"  ... and {len(result.failed_segments) - 10} more")
    
    return result


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="Export approved segments to individual audio clips")
    parser.add_argument("--video-id", type=int, help="Export specific video")
    parser.add_argument("--all", action="store_true", help="Export all approved videos")
    parser.add_argument("--output", type=str, default=str(EXPORT_DIR), help="Output directory")
    args = parser.parse_args()
    
    if args.video_id:
        with Session(engine) as session:
            segments, failed = export_video(args.video_id, session)
            if segments:
                output_path = Path(args.output) / f"video_{args.video_id}_manifest.tsv"
                write_manifest(segments, output_path)
                print(f"✓ Exported {len(segments)} segments to {output_path}")
            if failed:
                print(f"✗ Failed to export {len(failed)} segments:")
                for f in failed:
                    print(f"  - {f}")
    elif args.all:
        result = export_all_approved()
        print(f"\n{'='*50}")
        print(f"Export Complete")
        print(f"{'='*50}")
        print(f"  Videos processed: {result.videos_processed}")
        print(f"  Segments exported: {result.segments_exported}")
        print(f"  Segments failed: {result.segments_failed}")
        print(f"  Total duration: {result.total_hours:.2f} hours")
        if result.failed_segments:
            print(f"\n  ⚠ Some segments failed - check logs for details")
    else:
        parser.print_help()

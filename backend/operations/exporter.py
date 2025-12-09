"""
Dataset Exporter - Operations Layer.

Stitches approved segments into final training dataset.
Handles 5-second overlap resolution between consecutive chunks.

Output:
    - manifest.tsv: ID, audio_path, duration, transcript, translation
    - Audio files in export/ directory

Overlap Resolution Algorithm:
    When chunk N ends at 305s and chunk N+1 starts at 0s (which is 300s absolute),
    there's a 5-second overlap (300s-305s). We need to:
    1. Detect segments in the overlap zone (300s-305s of chunk N)
    2. If they appear in both chunks, keep the version from chunk N+1 (more context)
    3. Adjust absolute timestamps accordingly

Usage:
    python -m backend.operations.exporter --video-id 1
    python -m backend.operations.exporter --all
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session, select

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Video, Chunk, Segment, ProcessingStatus


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

CHUNK_DURATION = 300  # 5 minutes in seconds
OVERLAP_DURATION = 5  # 5 second overlap

EXPORT_DIR = DATA_ROOT / "export"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExportedSegment:
    """Segment ready for export with absolute timestamps."""
    segment_id: int
    video_id: int
    start_time_absolute: float
    end_time_absolute: float
    duration: float
    transcript: str
    translation: str
    audio_path: str  # Relative path to audio
    chunk_index: int


# =============================================================================
# TIMESTAMP CONVERSION
# =============================================================================

def relative_to_absolute(chunk_index: int, relative_time: float) -> float:
    """
    Convert relative timestamp (within chunk) to absolute timestamp (video time).
    
    Formula: absolute = (chunk_index * CHUNK_DURATION) + relative_time
    
    Args:
        chunk_index: Index of the chunk (0-based)
        relative_time: Time in seconds from start of chunk
        
    Returns:
        Absolute time in seconds from start of video
    """
    return (chunk_index * CHUNK_DURATION) + relative_time


def is_in_overlap_zone(chunk_index: int, relative_time: float) -> bool:
    """
    Check if a timestamp falls within the overlap zone.
    
    The overlap zone is the first 5 seconds of each chunk (except chunk 0),
    which corresponds to the last 5 seconds of the previous chunk.
    """
    if chunk_index == 0:
        return False  # First chunk has no overlap
    
    return relative_time < OVERLAP_DURATION


# =============================================================================
# OVERLAP RESOLUTION
# =============================================================================

def resolve_overlaps(segments: List[ExportedSegment]) -> List[ExportedSegment]:
    """
    Resolve overlapping segments between consecutive chunks.
    
    Strategy:
    - If two segments have overlapping absolute time ranges (>50% overlap),
      keep the one from the later chunk (more context available)
    - For partial overlaps, adjust segment boundaries
    
    Args:
        segments: List of exported segments sorted by absolute time
        
    Returns:
        De-duplicated list of segments
    """
    if not segments:
        return []
    
    # Sort by absolute start time
    sorted_segments = sorted(segments, key=lambda s: s.start_time_absolute)
    
    resolved = []
    
    for i, seg in enumerate(sorted_segments):
        # Check if this segment overlaps significantly with the previous one
        if resolved:
            prev = resolved[-1]
            
            # Calculate overlap
            overlap_start = max(prev.start_time_absolute, seg.start_time_absolute)
            overlap_end = min(prev.end_time_absolute, seg.end_time_absolute)
            overlap_duration = max(0, overlap_end - overlap_start)
            
            prev_duration = prev.end_time_absolute - prev.start_time_absolute
            seg_duration = seg.end_time_absolute - seg.start_time_absolute
            
            # If overlap is >50% of either segment, they're likely duplicates
            if overlap_duration > 0.5 * min(prev_duration, seg_duration):
                # Keep the segment from the later chunk (more context)
                if seg.chunk_index > prev.chunk_index:
                    resolved[-1] = seg  # Replace with newer version
                continue
            
            # Adjust boundaries for partial overlaps
            if overlap_duration > 0:
                # Trim the end of the previous segment
                prev.end_time_absolute = seg.start_time_absolute
                prev.duration = prev.end_time_absolute - prev.start_time_absolute
        
        resolved.append(seg)
    
    return resolved


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def export_video(video_id: int, session: Session) -> List[ExportedSegment]:
    """
    Export all approved segments for a video.
    
    Args:
        video_id: ID of the video to export
        session: Database session
        
    Returns:
        List of exported segments with absolute timestamps
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
        return []
    
    logger.info(f"Exporting video {video_id}: {len(chunks)} approved chunks")
    
    # Collect all segments with absolute timestamps
    all_segments: List[ExportedSegment] = []
    
    for chunk in chunks:
        segments = session.exec(
            select(Segment)
            .where(Segment.chunk_id == chunk.id)
            .order_by(Segment.start_time_relative)
        ).all()
        
        for seg in segments:
            exported = ExportedSegment(
                segment_id=seg.id,
                video_id=video_id,
                start_time_absolute=relative_to_absolute(chunk.chunk_index, seg.start_time_relative),
                end_time_absolute=relative_to_absolute(chunk.chunk_index, seg.end_time_relative),
                duration=seg.end_time_relative - seg.start_time_relative,
                transcript=seg.transcript,
                translation=seg.translation,
                audio_path=chunk.audio_path,
                chunk_index=chunk.chunk_index,
            )
            all_segments.append(exported)
    
    # Resolve overlaps
    resolved = resolve_overlaps(all_segments)
    logger.info(f"  {len(all_segments)} segments -> {len(resolved)} after overlap resolution")
    
    return resolved


def write_manifest(segments: List[ExportedSegment], output_path: Path) -> None:
    """
    Write segments to TSV manifest file.
    
    Format: id, audio_path, start, end, duration, transcript, translation
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t')
        
        # Header
        writer.writerow([
            'id', 'video_id', 'audio_path', 
            'start', 'end', 'duration', 
            'transcript', 'translation'
        ])
        
        # Data rows
        for seg in segments:
            writer.writerow([
                seg.segment_id,
                seg.video_id,
                seg.audio_path,
                f"{seg.start_time_absolute:.3f}",
                f"{seg.end_time_absolute:.3f}",
                f"{seg.duration:.3f}",
                seg.transcript,
                seg.translation,
            ])
    
    logger.info(f"Wrote manifest: {output_path}")


def export_all_approved() -> dict:
    """
    Export all videos with approved chunks.
    
    Returns:
        Dict with export statistics
    """
    results = {"videos": 0, "segments": 0}
    
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    with Session(engine) as session:
        # Find all videos with at least one approved chunk
        videos = session.exec(select(Video)).all()
        
        all_segments: List[ExportedSegment] = []
        
        for video in videos:
            try:
                segments = export_video(video.id, session)
                if segments:
                    all_segments.extend(segments)
                    results["videos"] += 1
            except Exception as e:
                logger.error(f"Failed to export video {video.id}: {e}")
        
        # Write combined manifest
        if all_segments:
            manifest_path = EXPORT_DIR / "manifest.tsv"
            write_manifest(all_segments, manifest_path)
            results["segments"] = len(all_segments)
            
            # Calculate total duration
            total_duration = sum(s.duration for s in all_segments)
            hours = total_duration / 3600
            logger.info(f"Total exported: {hours:.1f} hours of audio")
            results["hours"] = round(hours, 2)
    
    return results


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="Export approved segments to manifest")
    parser.add_argument("--video-id", type=int, help="Export specific video")
    parser.add_argument("--all", action="store_true", help="Export all approved videos")
    parser.add_argument("--output", type=str, default=str(EXPORT_DIR), help="Output directory")
    args = parser.parse_args()
    
    if args.video_id:
        with Session(engine) as session:
            segments = export_video(args.video_id, session)
            if segments:
                output_path = Path(args.output) / f"video_{args.video_id}_manifest.tsv"
                write_manifest(segments, output_path)
                print(f"Exported {len(segments)} segments to {output_path}")
    elif args.all:
        results = export_all_approved()
        print(f"Export complete: {results}")
    else:
        parser.print_help()

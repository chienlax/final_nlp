"""
DeepFilterNet Audio Denoiser - Operations Layer.

Batch processing for audio chunks flagged for denoising.
Runs as a background operation ("night shift").

Process:
    1. Scan database for chunks with denoise_status = FLAGGED
    2. Run DeepFilterNet on each audio file
    3. Save denoised file alongside original (with _denoised suffix)
    4. Update database with new file path
    5. Set denoise_status = PROCESSED

Usage:
    python -m backend.operations.denoiser --limit 10
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session, select

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Chunk, DenoiseStatus


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION (from environment)
# =============================================================================

# DeepFilterNet model (df3 = highest quality, df2 = balanced)
DEEPFILTER_MODEL = os.getenv("DEEPFILTER_MODEL", "df3")

# Output suffix for denoised files
DENOISED_SUFFIX = "_denoised"


# =============================================================================
# DENOISING FUNCTIONS
# =============================================================================

def denoise_audio(input_path: Path, output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Denoise an audio file using DeepFilterNet.
    
    Args:
        input_path: Path to noisy audio file
        output_path: Path for denoised output (default: input_denoised.wav)
        
    Returns:
        Path to denoised file, or None if failed
    """
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return None
    
    # Generate output path if not provided
    if output_path is None:
        stem = input_path.stem
        output_path = input_path.parent / f"{stem}{DENOISED_SUFFIX}.wav"
    
    # Run DeepFilterNet
    # Uses the deepfilternet CLI: deepfilter <input> -o <output>
    cmd = [
        "deepfilter",
        str(input_path),
        "-o", str(output_path),
        "-m", DEEPFILTER_MODEL,
    ]
    
    logger.info(f"Denoising: {input_path.name}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per file
        )
        
        if result.returncode != 0:
            logger.error(f"DeepFilterNet failed: {result.stderr}")
            return None
        
        if output_path.exists():
            logger.info(f"  -> Output: {output_path.name}")
            return output_path
        else:
            logger.error(f"Output file not created: {output_path}")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error(f"Denoising timed out: {input_path}")
        return None
    except FileNotFoundError:
        logger.error("DeepFilterNet not found. Install with: pip install deepfilternet")
        return None
    except Exception as e:
        logger.error(f"Denoising error: {e}")
        return None


def denoise_chunk(chunk: Chunk, session: Session) -> bool:
    """
    Denoise a single chunk and update database.
    
    Args:
        chunk: Chunk to denoise
        session: Database session
        
    Returns:
        True if successful
    """
    input_path = DATA_ROOT / chunk.audio_path
    
    # Generate denoised path
    stem = Path(chunk.audio_path).stem
    parent = Path(chunk.audio_path).parent
    denoised_relative = str(parent / f"{stem}{DENOISED_SUFFIX}.wav")
    output_path = DATA_ROOT / denoised_relative
    
    # Update status to QUEUED
    chunk.denoise_status = DenoiseStatus.QUEUED
    session.add(chunk)
    session.commit()
    
    # Run denoising
    result = denoise_audio(input_path, output_path)
    
    if result:
        # Update chunk with denoised path
        chunk.audio_path = denoised_relative
        chunk.denoise_status = DenoiseStatus.PROCESSED
        session.add(chunk)
        session.commit()
        return True
    else:
        # Reset to FLAGGED for retry
        chunk.denoise_status = DenoiseStatus.FLAGGED
        session.add(chunk)
        session.commit()
        return False


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def process_flagged_chunks(limit: int = 10) -> dict:
    """
    Process all chunks flagged for denoising.
    
    Args:
        limit: Maximum chunks to process
        
    Returns:
        Dict with success/fail counts
    """
    results = {"success": 0, "failed": 0, "skipped": 0}
    
    with Session(engine) as session:
        # Find flagged chunks
        chunks = session.exec(
            select(Chunk)
            .where(Chunk.denoise_status == DenoiseStatus.FLAGGED)
            .order_by(Chunk.id)
            .limit(limit)
        ).all()
        
        if not chunks:
            logger.info("No chunks flagged for denoising")
            return results
        
        logger.info(f"Found {len(chunks)} chunks to denoise")
        
        for chunk in chunks:
            try:
                if denoise_chunk(chunk, session):
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Error processing chunk {chunk.id}: {e}")
                results["failed"] += 1
    
    return results


def get_queue_status() -> dict:
    """Get counts of chunks in each denoise status."""
    with Session(engine) as session:
        counts = {}
        for status in DenoiseStatus:
            count = len(session.exec(
                select(Chunk).where(Chunk.denoise_status == status)
            ).all())
            counts[status.value] = count
        return counts


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="DeepFilterNet batch denoiser")
    parser.add_argument("--limit", type=int, default=10, help="Max chunks to process")
    parser.add_argument("--status", action="store_true", help="Show queue status only")
    args = parser.parse_args()
    
    if args.status:
        status = get_queue_status()
        print("Denoise Queue Status:")
        for k, v in status.items():
            print(f"  {k}: {v}")
    else:
        print(f"Processing up to {args.limit} flagged chunks...")
        results = process_flagged_chunks(limit=args.limit)
        print(f"Results: {results}")

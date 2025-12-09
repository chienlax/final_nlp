"""
Gemini AI Worker for Audio Transcription.

Sends audio chunks to Gemini Flash for transcription and translation.
Handles JSON parsing, timestamp conversion, and API key rotation.

Output Schema:
    [
        {
            "start": "00:00.000",
            "end": "00:05.123",
            "text": "Hello các bạn...",
            "translation": "Xin chào các bạn..."
        }
    ]
"""

import os
import re
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from itertools import cycle

import google.generativeai as genai
from sqlmodel import Session, select

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Chunk, Segment, ProcessingStatus
from backend.utils.time_parser import parse_timestamp


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS (from environment)
# =============================================================================

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

SYSTEM_PROMPT = """You are a professional transcriber for Vietnamese-English Code-Switching audio.
Your task is to output a strictly valid JSON array of segments.

RULES:
1. TIMESTAMPS: Must be relative to the start of the audio file (00:00).
   Format: "MM:SS.mmm" (e.g., "04:05.123").
2. CONTENT: Transcribe exactly what is spoken. Do not summarize.
3. LANGUAGE: Detect Vietnamese and English automatically.
4. TRANSLATION: Provide a Vietnamese translation for every segment.
5. SEGMENTS: Each segment should be 2-25 seconds long.

OUTPUT FORMAT:
[
  {
    "start": "00:00.000",
    "end": "00:05.123",
    "text": "Hello các bạn, hôm nay...",
    "translation": "Xin chào các bạn, hôm nay..."
  }
]

CRITICAL: Output ONLY the JSON array. No markdown, no explanations."""


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

class ApiKeyPool:
    """
    Rotating pool of Gemini API keys.
    
    Reads from GEMINI_API_KEYS env var (comma-separated).
    Falls back to GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.
    """
    
    def __init__(self):
        self.keys = self._load_keys()
        if not self.keys:
            raise ValueError("No Gemini API keys found. Set GEMINI_API_KEYS env var.")
        self.key_cycle = cycle(self.keys)
        self.current_key = next(self.key_cycle)
        logger.info(f"Loaded {len(self.keys)} API keys")
    
    def _load_keys(self) -> List[str]:
        """Load API keys from environment."""
        keys = []
        
        # Try comma-separated list first
        combined = os.getenv("GEMINI_API_KEYS", "")
        if combined:
            keys = [k.strip() for k in combined.split(",") if k.strip()]
        
        # Fallback to numbered keys
        if not keys:
            for i in range(1, 10):
                key = os.getenv(f"GEMINI_API_KEY_{i}")
                if key:
                    keys.append(key)
        
        # Final fallback
        if not keys:
            key = os.getenv("GEMINI_API_KEY")
            if key:
                keys.append(key)
        
        return keys
    
    def get_key(self) -> str:
        """Get current API key."""
        return self.current_key
    
    def rotate(self) -> str:
        """Rotate to next API key and return it."""
        self.current_key = next(self.key_cycle)
        logger.info(f"Rotated to new API key: ...{self.current_key[-8:]}")
        return self.current_key


# =============================================================================
# JSON PARSING
# =============================================================================

def clean_json_response(text: str) -> str:
    """
    Clean Gemini response to extract JSON.
    
    Removes markdown code blocks and whitespace.
    """
    # Remove markdown code blocks
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'```$', '', text)
    
    return text.strip()


def parse_gemini_response(text: str) -> List[Dict[str, Any]]:
    """
    Parse Gemini response into structured segments.
    
    Args:
        text: Raw response text from Gemini
        
    Returns:
        List of segment dictionaries
        
    Raises:
        ValueError: If parsing fails
    """
    cleaned = clean_json_response(text)
    
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.error(f"Raw text: {cleaned[:500]}")
        raise ValueError(f"Invalid JSON response: {e}")
    
    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data).__name__}")
    
    # Validate and convert each segment
    segments = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        
        try:
            segment = {
                "start": parse_timestamp(item.get("start", 0)),
                "end": parse_timestamp(item.get("end", 0)),
                "text": str(item.get("text", "")),
                "translation": str(item.get("translation", "")),
            }
            segments.append(segment)
        except ValueError as e:
            logger.warning(f"Skipping segment {i}: {e}")
    
    return segments


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_chunk(
    chunk_id: int,
    api_key_pool: Optional[ApiKeyPool] = None,
    model_name: str = DEFAULT_MODEL
) -> Tuple[int, Dict[str, Any]]:
    """
    Process a single chunk with Gemini.
    
    Args:
        chunk_id: ID of chunk to process
        api_key_pool: API key pool (creates new if not provided)
        model_name: Gemini model to use
        
    Returns:
        Tuple of (segments_created, metadata)
    """
    if api_key_pool is None:
        api_key_pool = ApiKeyPool()
    
    with Session(engine) as session:
        chunk = session.get(Chunk, chunk_id)
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
        
        # Check if already processed
        if chunk.status == ProcessingStatus.REVIEW_READY:
            logger.info(f"Chunk {chunk_id} already processed, skipping")
            return 0, {"skipped": True}
        
        # Resolve audio path
        audio_path = DATA_ROOT / chunk.audio_path
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")
        
        # Update status
        chunk.status = ProcessingStatus.PROCESSING
        session.add(chunk)
        session.commit()
        
        # Configure Gemini
        genai.configure(api_key=api_key_pool.get_key())
        model = genai.GenerativeModel(model_name)
        
        # Upload and process
        logger.info(f"Processing chunk {chunk_id}: {chunk.audio_path}")
        start_time = time.time()
        
        try:
            # Upload audio file
            audio_file = genai.upload_file(str(audio_path))
            
            # Generate transcription
            response = model.generate_content(
                [SYSTEM_PROMPT, audio_file],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json"
                )
            )
            
            processing_time = time.time() - start_time
            
            # Parse response
            segments_data = parse_gemini_response(response.text)
            
            # Delete existing segments for this chunk
            existing = session.exec(
                select(Segment).where(Segment.chunk_id == chunk_id)
            ).all()
            for seg in existing:
                session.delete(seg)
            
            # Insert new segments
            for seg_data in segments_data:
                segment = Segment(
                    chunk_id=chunk_id,
                    start_time_relative=seg_data["start"],
                    end_time_relative=seg_data["end"],
                    transcript=seg_data["text"],
                    translation=seg_data["translation"],
                    is_verified=False,
                )
                session.add(segment)
            
            # Update chunk status
            chunk.status = ProcessingStatus.REVIEW_READY
            session.add(chunk)
            session.commit()
            
            metadata = {
                "processing_time_seconds": processing_time,
                "segments_count": len(segments_data),
                "api_key": f"...{api_key_pool.get_key()[-8:]}",
            }
            
            logger.info(f"Chunk {chunk_id}: {len(segments_data)} segments in {processing_time:.1f}s")
            
            return len(segments_data), metadata
            
        except Exception as e:
            logger.error(f"Failed to process chunk {chunk_id}: {e}")
            chunk.status = ProcessingStatus.PENDING  # Reset for retry
            session.add(chunk)
            session.commit()
            
            # Try rotating API key
            api_key_pool.rotate()
            raise


def process_all_pending(
    limit: int = 10,
    model_name: str = DEFAULT_MODEL
) -> Dict[str, int]:
    """
    Process all pending chunks.
    
    Args:
        limit: Maximum chunks to process
        model_name: Gemini model to use
        
    Returns:
        Dict with success/fail counts
    """
    api_key_pool = ApiKeyPool()
    
    with Session(engine) as session:
        chunks = session.exec(
            select(Chunk)
            .where(Chunk.status == ProcessingStatus.PENDING)
            .order_by(Chunk.video_id, Chunk.chunk_index)
            .limit(limit)
        ).all()
    
    results = {"success": 0, "failed": 0, "total_segments": 0}
    
    for chunk in chunks:
        try:
            segments, _ = process_chunk(chunk.id, api_key_pool, model_name)
            results["success"] += 1
            results["total_segments"] += segments
            
            # Rate limiting
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Chunk {chunk.id} failed: {e}")
            results["failed"] += 1
    
    return results


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        chunk_id = int(sys.argv[1])
        process_chunk(chunk_id)
    else:
        limit = 10
        if len(sys.argv) > 2:
            limit = int(sys.argv[2])
        
        print(f"Processing up to {limit} pending chunks...")
        results = process_all_pending(limit=limit)
        print(f"Results: {results}")

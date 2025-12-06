#!/usr/bin/env python3
"""
Gemini Processing Script (v2 - Simplified).

Transcribes audio files using Gemini's multimodal capabilities with structured
output, producing sentence-level timestamps and Vietnamese translations in a
single pass.

Pipeline: pending → transcribed

Features:
    - Single-pass: Full context understanding + structured JSON output
    - Few-shot prompting with Vietnamese-English code-switching examples
    - Audio chunking for files >10 minutes with 10s overlap
    - SQLite database backend (replaces PostgreSQL)
    - Simplified output schema (no duration field - computed on import)

Usage:
    python gemini_process.py --video-id <id>
    python gemini_process.py --batch --limit 10
    python gemini_process.py --audio-file path/to/audio.wav --output result.json

Requirements:
    - google-generativeai>=0.3.0
    - pydub
    - GEMINI_API_KEY_1 environment variable
"""

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    get_db,
    insert_segments,
    update_video_state,
    update_chunk_state,
    aggregate_chunk_state,
    get_videos_by_state,
    get_video,
    get_chunk,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Supported audio formats for Gemini
SUPPORTED_AUDIO_FORMATS = {'.wav', '.mp3', '.aiff', '.aac', '.ogg', '.flac'}

# Gemini settings
DEFAULT_MODEL = "gemini-2.5-pro"

# Audio chunking settings (per user spec)
MAX_CHUNK_DURATION_SECONDS = 10 * 60  # 10 minutes
CHUNK_OVERLAP_SECONDS = 10  # 10 seconds overlap
TAIL_MERGE_THRESHOLD_SECONDS = 11 * 60  # 11 minutes - merge if tail is <= this

# Overlap deduplication settings
OVERLAP_TIME_TOLERANCE_SECONDS = 2.0  # ±2 seconds for timestamp overlap
TEXT_SIMILARITY_THRESHOLD = 0.8  # >80% text similarity for deduplication

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
RATE_LIMIT_WAIT_SECONDS = 60

# Thinking configuration for Gemini 2.5 Pro
THINKING_BUDGET = 15668


# =============================================================================
# FEW-SHOT EXAMPLES FOR VIETNAMESE-ENGLISH CODE-SWITCHING
# =============================================================================

FEW_SHOT_EXAMPLES = """
**Example 1: Technology content with English terms**
```json
[
  {
    "text": "Hôm nay mình sẽ review cái framework mới này, nó rất là powerful.",
    "start": 0.0,
    "end": 4.5,
    "translation": "Hôm nay mình sẽ đánh giá khung phần mềm mới này, nó rất là mạnh mẽ."
  },
  {
    "text": "Cái feature chính của nó là support real-time collaboration.",
    "start": 4.5,
    "end": 8.2,
    "translation": "Tính năng chính của nó là hỗ trợ cộng tác theo thời gian thực."
  }
]
```

**Example 2: Casual conversation with slang**
```json
[
  {
    "text": "Okay các bạn, hôm nay mình sẽ đi shopping ở mall này.",
    "start": 0.0,
    "end": 3.8,
    "translation": "Được rồi các bạn, hôm nay mình sẽ đi mua sắm ở trung tâm thương mại này."
  },
  {
    "text": "Cái store này sale off đến fifty percent luôn á.",
    "start": 3.8,
    "end": 7.1,
    "translation": "Cửa hàng này đang giảm giá đến năm mươi phần trăm luôn đấy."
  }
]
```

**Example 3: Splitting longer continuous speech**
```json
[
  {
    "text": "Các bạn ơi, hôm nay mình muốn share với các bạn về kinh nghiệm học programming của mình.",
    "start": 0.0,
    "end": 7.2,
    "translation": "Các bạn ơi, hôm nay mình muốn chia sẻ với các bạn về kinh nghiệm học lập trình của mình."
  },
  {
    "text": "Thực ra mình bắt đầu learn code từ năm 2020.",
    "start": 7.2,
    "end": 11.5,
    "translation": "Thực ra mình bắt đầu học lập trình từ năm 2020."
  }
]
```
"""


# =============================================================================
# STRUCTURED OUTPUT PROMPT
# =============================================================================

PROCESSING_PROMPT = f"""You are an expert audio transcriptionist and translator for Vietnamese-English code-switched speech.

CRITICAL: TIMESTAMP ACCURACY IS ESSENTIAL
- The start and end timestamps MUST precisely match when the text is actually spoken
- Listen carefully to where each sentence begins and ends in the audio
- Do NOT guess timestamps - they must reflect the actual audio timing

TASK:
1. Listen to the ENTIRE audio first to understand context
2. Identify all speech segments (skip music, sound effects, jingles)
3. Segment into natural sentences (5-20 seconds each)
4. Transcribe preserving code-switching
5. Translate to Vietnamese
6. Assign accurate timestamps

TRANSCRIPTION RULES:
- Preserve code-switching exactly (Vietnamese as Vietnamese, English as English)
- Use correct Vietnamese diacritics
- Preserve proper nouns, brand names, technical terms as spoken
- Mark unclear sections with [unclear]

SENTENCE GUIDELINES:
- Aim for 5-20 second segments
- Split at natural boundaries: pauses, conjunctions, topic shifts
- Long continuous speech should be broken into multiple sentences

TRANSLATION RULES:
- Translate ALL English words/phrases into natural Vietnamese
- Preserve proper nouns unless they have established Vietnamese forms
- If translation impossible, output "[translation_missing]"

{FEW_SHOT_EXAMPLES}

OUTPUT FORMAT:
Return a JSON array directly (NOT wrapped in an object). Each element has:
- "text": Original transcription (code-switched)
- "start": Start time in seconds (float)
- "end": End time in seconds (float)
- "translation": Pure Vietnamese translation

Now transcribe and translate the audio:"""


# =============================================================================
# SIMPLIFIED OUTPUT SCHEMA (no duration field)
# =============================================================================

SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "Original transcription preserving code-switching"
        },
        "start": {
            "type": "number",
            "description": "Start time in seconds"
        },
        "end": {
            "type": "number",
            "description": "End time in seconds"
        },
        "translation": {
            "type": "string",
            "description": "Pure Vietnamese translation"
        }
    },
    "required": ["text", "start", "end", "translation"]
}

OUTPUT_SCHEMA = {
    "type": "array",
    "items": SENTENCE_SCHEMA,
    "description": "Array of transcribed and translated sentences"
}


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

@dataclass
class ApiKey:
    """Represents a Gemini API key."""
    key_id: int
    key_name: str
    api_key: str


def get_api_keys_from_env() -> List[ApiKey]:
    """
    Get API keys from environment variables.

    Looks for GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.

    Returns:
        List of ApiKey objects.
    """
    keys = []
    idx = 1

    while True:
        env_var = f"GEMINI_API_KEY_{idx}"
        api_key = os.environ.get(env_var)

        if not api_key and idx == 1:
            api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            break

        keys.append(ApiKey(
            key_id=idx,
            key_name=f"env_key_{idx}",
            api_key=api_key,
        ))
        idx += 1

    return keys


def get_available_api_key() -> Optional[ApiKey]:
    """Get next available API key."""
    env_keys = get_api_keys_from_env()
    return env_keys[0] if env_keys else None


# =============================================================================
# AUDIO PROCESSING
# =============================================================================

def load_audio_file(audio_path: Path) -> Tuple[bytes, str]:
    """
    Load audio file and determine its MIME type.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Tuple of (audio_bytes, mime_type).

    Raises:
        ValueError: If audio format is not supported.
        FileNotFoundError: If file doesn't exist.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    suffix = audio_path.suffix.lower()
    if suffix not in SUPPORTED_AUDIO_FORMATS:
        raise ValueError(
            f"Unsupported audio format: {suffix}. "
            f"Supported: {SUPPORTED_AUDIO_FORMATS}"
        )

    mime_types = {
        '.wav': 'audio/wav',
        '.mp3': 'audio/mp3',
        '.aiff': 'audio/aiff',
        '.aac': 'audio/aac',
        '.ogg': 'audio/ogg',
        '.flac': 'audio/flac',
    }

    mime_type = mime_types.get(suffix, 'audio/wav')

    with open(audio_path, 'rb') as f:
        audio_bytes = f.read()

    return audio_bytes, mime_type


def get_audio_duration_seconds(audio_path: Path) -> Optional[float]:
    """
    Get audio duration in seconds using pydub.

    Args:
        audio_path: Path to audio file.

    Returns:
        Duration in seconds, or None if cannot be determined.
    """
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(audio_path))
        return len(audio) / 1000.0
    except Exception:
        return None


def chunk_audio_file(
    audio_path: Path,
    max_chunk_sec: float = MAX_CHUNK_DURATION_SECONDS,
    overlap_sec: float = CHUNK_OVERLAP_SECONDS,
    tail_merge_threshold: float = TAIL_MERGE_THRESHOLD_SECONDS
) -> List[Tuple[Path, float, float]]:
    """
    Split audio file into chunks with overlap.

    Chunking rules (per user spec):
    - Chunk every 10 minutes
    - Cut at 10:05 but start next chunk at 9:55 (10s overlap on both sides)
    - If last chunk is <= 11 minutes, keep as-is
    - If last chunk > 11 minutes, apply overlap rule

    Args:
        audio_path: Path to the audio file.
        max_chunk_sec: Maximum duration per chunk (10 minutes).
        overlap_sec: Overlap between chunks (10 seconds).
        tail_merge_threshold: Threshold for merging tail (11 minutes).

    Returns:
        List of tuples (chunk_path, start_offset_sec, end_offset_sec).
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(str(audio_path))
    duration_ms = len(audio)
    duration_sec = duration_ms / 1000.0

    # No chunking needed if audio is short enough
    if duration_sec <= max_chunk_sec:
        return [(audio_path, 0.0, duration_sec)]

    print(f"[INFO] Audio duration {duration_sec:.1f}s > {max_chunk_sec}s, chunking...")

    chunks = []
    temp_dir = Path(tempfile.mkdtemp(prefix="gemini_chunks_"))

    # Calculate chunks
    chunk_positions: List[Tuple[float, float]] = []
    current_start = 0.0

    while current_start < duration_sec:
        # Calculate end of this chunk (with 5s buffer for overlap)
        chunk_end = current_start + max_chunk_sec + (overlap_sec / 2)

        # Check remaining duration
        remaining = duration_sec - current_start

        if remaining <= tail_merge_threshold:
            # Last chunk - include everything
            chunk_positions.append((current_start, duration_sec))
            break
        else:
            # Normal chunk
            chunk_positions.append((current_start, min(chunk_end, duration_sec)))
            # Next chunk starts 10s before this chunk ends (overlap)
            current_start = current_start + max_chunk_sec - (overlap_sec / 2)

    print(f"[INFO] Creating {len(chunk_positions)} chunks with {overlap_sec}s overlap")

    for chunk_idx, (start_sec, end_sec) in enumerate(chunk_positions):
        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)

        chunk = audio[start_ms:end_ms]
        chunk_path = temp_dir / f"chunk_{chunk_idx:03d}.wav"
        chunk.export(str(chunk_path), format="wav")

        chunks.append((chunk_path, start_sec, end_sec))
        print(f"  Chunk {chunk_idx}: {start_sec:.1f}s - {end_sec:.1f}s ({end_sec - start_sec:.1f}s)")

    return chunks


# =============================================================================
# TEXT SIMILARITY FOR DEDUPLICATION
# =============================================================================

def text_similarity(text1: str, text2: str) -> float:
    """Calculate text similarity ratio using SequenceMatcher."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def deduplicate_sentences(
    all_sentences: List[Dict[str, Any]],
    time_tolerance: float = OVERLAP_TIME_TOLERANCE_SECONDS,
    text_threshold: float = TEXT_SIMILARITY_THRESHOLD
) -> List[Dict[str, Any]]:
    """
    Deduplicate sentences from overlapping chunks.

    Uses: remove sentences with >80% text similarity AND timestamp overlap
    within ±2 seconds. Keeps the version from earlier chunk.

    Args:
        all_sentences: List of all sentences from all chunks.
        time_tolerance: Timestamp overlap tolerance in seconds.
        text_threshold: Text similarity threshold (0.0 to 1.0).

    Returns:
        Deduplicated list of sentences.
    """
    if not all_sentences:
        return []

    # Sort by start time
    sorted_sentences = sorted(all_sentences, key=lambda x: x.get('start', 0))

    deduplicated = []

    for sentence in sorted_sentences:
        is_duplicate = False

        for existing in deduplicated:
            # Check timestamp overlap
            time_overlap = (
                abs(sentence.get('start', 0) - existing.get('start', 0)) <= time_tolerance or
                abs(sentence.get('end', 0) - existing.get('end', 0)) <= time_tolerance
            )

            if not time_overlap:
                continue

            # Check text similarity
            similarity = text_similarity(
                sentence.get('text', ''),
                existing.get('text', '')
            )

            if similarity >= text_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            deduplicated.append(sentence)

    return deduplicated


# =============================================================================
# GEMINI API CALLS
# =============================================================================

def process_audio_chunk(
    audio_path: Path,
    api_key: ApiKey,
    model: str = DEFAULT_MODEL,
    offset_seconds: float = 0.0
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Process a single audio chunk with Gemini.

    Args:
        audio_path: Path to the audio file/chunk.
        api_key: API key to use.
        model: Gemini model to use.
        offset_seconds: Time offset to add to all timestamps.

    Returns:
        Tuple of (sentences_list, metadata).
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError(
            "google-generativeai is required. "
            "Install with: pip install google-generativeai"
        ) from e

    # Load audio
    audio_bytes, mime_type = load_audio_file(audio_path)
    audio_size_mb = len(audio_bytes) / (1024 * 1024)

    print(f"  Processing: {audio_path.name} ({audio_size_mb:.2f} MB)")

    # Initialize client
    genai.configure(api_key=api_key.api_key)

    generation_config = {
        "temperature": 1.0,
        "top_p": 0.95,
        "max_output_tokens": 65536,
        "response_mime_type": "application/json",
        "response_schema": OUTPUT_SCHEMA
    }

    client = genai.GenerativeModel(
        model_name=model,
        generation_config=generation_config
    )

    # Create audio part
    audio_part = {
        "mime_type": mime_type,
        "data": base64.standard_b64encode(audio_bytes).decode("utf-8")
    }

    start_time = time.time()
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.generate_content([PROCESSING_PROMPT, audio_part])

            # Check for blocked content
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                if hasattr(response.prompt_feedback, 'block_reason'):
                    if response.prompt_feedback.block_reason:
                        raise ValueError(
                            f"Content blocked: {response.prompt_feedback.block_reason}"
                        )

            # Parse JSON response
            response_text = response.text.strip()

            # Extract JSON if wrapped in markdown
            if response_text.startswith("```"):
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
                if json_match:
                    response_text = json_match.group(1)

            result = json.loads(response_text)

            # Handle both array and object formats
            if isinstance(result, dict) and 'sentences' in result:
                sentences = result['sentences']
            elif isinstance(result, list):
                sentences = result
            else:
                sentences = []

            # Adjust timestamps for chunk offset
            if offset_seconds > 0:
                for sentence in sentences:
                    sentence['start'] = sentence.get('start', 0) + offset_seconds
                    sentence['end'] = sentence.get('end', 0) + offset_seconds

            elapsed_time = time.time() - start_time

            metadata = {
                "model": model,
                "audio_file": audio_path.name,
                "audio_size_mb": round(audio_size_mb, 2),
                "sentence_count": len(sentences),
                "processing_time_seconds": round(elapsed_time, 2),
                "attempts": attempt + 1,
                "offset_seconds": offset_seconds
            }

            return sentences, metadata

        except json.JSONDecodeError as e:
            last_error = e
            print(f"  [WARNING] JSON parse error on attempt {attempt + 1}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            if "rate" in error_str or "quota" in error_str or "429" in error_str:
                print(f"  [WARNING] Rate limit hit on attempt {attempt + 1}")
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
            elif attempt < MAX_RETRIES - 1:
                print(f"  [WARNING] Attempt {attempt + 1} failed: {e}")
                time.sleep(RETRY_DELAY_SECONDS)

    raise Exception(f"Processing failed after {MAX_RETRIES} attempts: {last_error}")


def process_audio_file(
    audio_path: Path,
    api_key: ApiKey,
    model: str = DEFAULT_MODEL
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Process entire audio file, chunking if necessary.

    Args:
        audio_path: Path to the audio file.
        api_key: API key to use.
        model: Gemini model to use.

    Returns:
        Tuple of (sentences_list, metadata).
    """
    duration_seconds = get_audio_duration_seconds(audio_path)

    # Check if chunking is needed
    if duration_seconds and duration_seconds > MAX_CHUNK_DURATION_SECONDS:
        chunks = chunk_audio_file(audio_path)

        all_sentences: List[Dict[str, Any]] = []
        all_metadata: Dict[str, Any] = {
            "model": model,
            "audio_file": audio_path.name,
            "duration_seconds": duration_seconds,
            "chunk_count": len(chunks),
            "chunks": []
        }

        for chunk_path, start_offset, end_offset in chunks:
            try:
                sentences, chunk_meta = process_audio_chunk(
                    chunk_path,
                    api_key,
                    model,
                    offset_seconds=start_offset
                )
                all_sentences.extend(sentences)
                all_metadata["chunks"].append(chunk_meta)

                # Delay between chunks
                time.sleep(2)

            finally:
                # Clean up temp chunk file
                if chunk_path != audio_path and chunk_path.exists():
                    chunk_path.unlink()

        # Clean up temp directory
        if chunks and chunks[0][0] != audio_path:
            temp_dir = chunks[0][0].parent
            if temp_dir.exists() and "gemini_chunks_" in temp_dir.name:
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass

        # Deduplicate overlapping sentences
        print(f"[INFO] Deduplicating {len(all_sentences)} sentences...")
        deduplicated = deduplicate_sentences(all_sentences)
        print(f"[INFO] Result: {len(deduplicated)} sentences after deduplication")

        all_metadata["sentence_count"] = len(deduplicated)
        all_metadata["sentences_before_dedup"] = len(all_sentences)

        return deduplicated, all_metadata

    else:
        # Single chunk processing
        sentences, metadata = process_audio_chunk(
            audio_path, api_key, model, offset_seconds=0.0
        )
        metadata["sentence_count"] = len(sentences)
        return sentences, metadata


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def process_video(
    video_id: str,
    data_root: Path,
    model: str = DEFAULT_MODEL,
    chunk_id: Optional[int] = None
) -> bool:
    """
    Process a video with Gemini and save results to SQLite.

    Args:
        video_id: Video identifier.
        data_root: Root directory for data files.
        model: Gemini model to use.

    Returns:
        True if successful, False otherwise.
    """
    # Get video from database
    video = get_video(video_id)
    if not video:
        print(f"[ERROR] Video not found: {video_id}")
        return False

    if chunk_id:
        chunk = get_chunk(chunk_id)
        if not chunk:
            print(f"[ERROR] Chunk not found: {chunk_id}")
            return False
        audio_path_str = chunk['audio_path']
        title = f"{video['title']} (chunk {chunk['chunk_index']})"
    else:
        audio_path_str = video['denoised_audio_path'] or video['audio_path']
        title = video['title']

    print(f"\n{'='*60}")
    print(f"Processing: {title}")
    print(f"Video ID: {video_id}")
    print(f"Audio: {audio_path_str}")
    print(f"{'='*60}")

    # Resolve audio path
    audio_path = data_root / audio_path_str
    if not audio_path.exists():
        audio_path = Path(audio_path_str)
        if not audio_path.exists():
            print(f"[ERROR] Audio file not found: {audio_path_str}")
            return False

    start_time = time.time()

    try:
        # Get API key
        api_key = get_available_api_key()
        if not api_key:
            raise ValueError("No API keys available")

        print(f"[INFO] Using API key: {api_key.key_name}")
        print(f"[INFO] Using model: {model}")

        # Process audio
        print(f"[INFO] Processing audio...")
        sentences, metadata = process_audio_file(audio_path, api_key, model)

        print(f"[INFO] Processing complete ({metadata.get('processing_time_seconds', 0):.1f}s)")
        print(f"[INFO] Sentence count: {len(sentences)}")

        # Preview first few sentences
        print(f"\n[PREVIEW] First 3 sentences:")
        for i, s in enumerate(sentences[:3]):
            print(f"  {i+1}. [{s['start']:.1f}s-{s['end']:.1f}s]")
            text_preview = s['text'][:60] + "..." if len(s['text']) > 60 else s['text']
            print(f"     {text_preview}")

        # Save to database
        print(f"\n[INFO] Saving to database...")
        segment_count = insert_segments(video_id, sentences, chunk_id=chunk_id)
        if chunk_id:
            update_chunk_state(chunk_id, 'transcribed')
            agg_state = aggregate_chunk_state(video_id)
            if agg_state == 'transcribed':
                update_video_state(video_id, 'transcribed')
        else:
            update_video_state(video_id, 'transcribed')

        elapsed = time.time() - start_time
        print(f"\n[SUCCESS] Processed {video_id}")
        print(f"  Segments: {segment_count}")
        print(f"  Time: {elapsed:.2f}s")

        return True

    except Exception as e:
        print(f"[ERROR] Failed to process {video_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


def process_audio_standalone(
    audio_path: Path,
    output_path: Optional[Path] = None,
    model: str = DEFAULT_MODEL
) -> bool:
    """
    Process an audio file without database (standalone mode).

    Args:
        audio_path: Path to audio file.
        output_path: Path for JSON output (default: same name with .json).
        model: Gemini model to use.

    Returns:
        True if successful, False otherwise.
    """
    if not audio_path.exists():
        print(f"[ERROR] Audio file not found: {audio_path}")
        return False

    output_path = output_path or audio_path.with_suffix('.json')

    print(f"\n{'='*60}")
    print(f"Standalone Processing")
    print(f"Input: {audio_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}")

    try:
        api_key = get_available_api_key()
        if not api_key:
            raise ValueError("No API keys available")

        sentences, metadata = process_audio_file(audio_path, api_key, model)

        # Save to JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sentences, f, ensure_ascii=False, indent=2)

        print(f"\n[SUCCESS] Saved {len(sentences)} sentences to {output_path}")
        return True

    except Exception as e:
        print(f"[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Process audio with Gemini (transcription + translation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Process a specific video from database
    python gemini_process.py --video-id abc123

    # Process batch of pending videos
    python gemini_process.py --batch --limit 5

    # Standalone mode (no database)
    python gemini_process.py --audio-file path/to/audio.wav

    # Custom output path
    python gemini_process.py --audio-file audio.wav --output result.json

Environment Variables:
    GEMINI_API_KEY_1 : Primary Gemini API key
    GEMINI_API_KEY_2 : Backup API key
        """
    )
    parser.add_argument(
        "--video-id",
        help="Video ID to process"
    )
    parser.add_argument(
        "--chunk-id",
        type=int,
        help="Chunk ID to process (uses chunk audio path and updates chunk state)"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of pending videos"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum videos in batch mode (default: 5)"
    )
    parser.add_argument(
        "--audio-file",
        type=Path,
        help="Standalone: process audio file without database"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Standalone: output JSON path"
    )
    parser.add_argument(
        "--model",
        choices=["gemini-2.5-flash", "gemini-2.5-pro"],
        default=DEFAULT_MODEL,
        help=f"Gemini model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Root directory for data files (default: data)"
    )
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="Check API key availability and exit"
    )

    args = parser.parse_args()

    # Check API keys
    if args.check_keys:
        print("\n[API Key Status]")
        print("-" * 40)
        env_keys = get_api_keys_from_env()
        print(f"Found {len(env_keys)} API key(s):")
        for k in env_keys:
            masked = k.api_key[:8] + "..." + k.api_key[-4:]
            print(f"  - {k.key_name}: {masked}")
        return

    # Standalone mode
    if args.audio_file:
        success = process_audio_standalone(
            args.audio_file,
            args.output,
            args.model
        )
        sys.exit(0 if success else 1)

    # Chunk-specific mode
    if args.chunk_id:
        if not args.video_id:
            parser.print_help()
            print("\nError: --chunk-id requires --video-id for state updates")
            sys.exit(1)
        success = process_video(args.video_id, args.data_root, args.model, chunk_id=args.chunk_id)
        sys.exit(0 if success else 1)

    # Database mode
    if not args.video_id and not args.batch:
        parser.print_help()
        print("\nError: Specify --video-id, --batch, or --audio-file")
        sys.exit(1)

    # Verify API key
    api_key = get_available_api_key()
    if not api_key:
        print("[ERROR] No API keys available.")
        print("Set GEMINI_API_KEY_1 in your .env file.")
        sys.exit(1)

    if args.video_id:
        success = process_video(args.video_id, args.data_root, args.model)
        sys.exit(0 if success else 1)
    else:
        # Batch mode
        videos = get_videos_by_state('pending', limit=args.limit)
        print(f"\n[INFO] Found {len(videos)} pending videos")

        success_count = 0
        fail_count = 0

        for video in videos:
            if process_video(video['video_id'], args.data_root, args.model):
                success_count += 1
            else:
                fail_count += 1

            if success_count + fail_count < len(videos):
                time.sleep(2)

        print(f"\n{'='*60}")
        print(f"Batch complete: {success_count} success, {fail_count} failed")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Gemini Unified Processing Script.

Transcribes audio files using Gemini's multimodal capabilities with structured
output, producing sentence-level timestamps and Vietnamese translations in a
single pass using few-shot prompting.

This script replaces both gemini_transcribe.py and translate.py with a unified
approach that leverages Gemini's ability to understand full audio context before
outputting structured sentence-by-sentence data.

Pipeline Stage: RAW → TRANSLATED (with needs_translation_review flag if issues)

Features:
    - Hybrid single-pass: Full context understanding + structured JSON output
    - Few-shot prompting with Vietnamese-English code-switching examples
    - Audio chunking for files >20 minutes with overlap deduplication
    - Thinking mode with extended reasoning for accurate timestamps (15668 tokens)
    - Translation issue detection and flagging for repair script

Usage:
    python gemini_process.py --sample-id <uuid>
    python gemini_process.py --batch --limit 10
    python gemini_process.py --batch --replace-existing

Requirements:
    - google-generativeai>=0.3.0 (pip install google-generativeai)
    - pydub (pip install pydub)
    - GEMINI_API_KEY_1 environment variable (from .env file)
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

import psycopg2
from psycopg2.extras import Json, RealDictCursor

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.data_utils import get_pg_connection, log_processing


# =============================================================================
# CONFIGURATION
# =============================================================================

# Supported audio formats for Gemini
SUPPORTED_AUDIO_FORMATS = {'.wav', '.mp3', '.aiff', '.aac', '.ogg', '.flac'}

# Gemini settings
DEFAULT_MODEL = "gemini-2.5-pro"
PRO_MODEL = "gemini-2.5-pro"

# Audio chunking settings
MAX_AUDIO_DURATION_SECONDS = 20 * 60  # 20 minutes - threshold for chunking
CHUNK_OVERLAP_SECONDS = 20  # 20 seconds overlap between chunks for consistency

# Overlap deduplication settings
OVERLAP_TIME_TOLERANCE_SECONDS = 2.0  # ±2 seconds for timestamp overlap
TEXT_SIMILARITY_THRESHOLD = 0.8  # >80% text similarity for deduplication

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
RATE_LIMIT_WAIT_SECONDS = 60

# Thinking configuration for Gemini 2.5 Pro
THINKING_BUDGET = 15668  # Tokens allocated for reasoning about sentence boundaries

# Translation issue markers
TRANSLATION_MISSING_MARKERS = [
    "[translation_missing]",
    "[dịch_thiếu]",
    "",
    None
]


# =============================================================================
# FEW-SHOT EXAMPLES FOR VIETNAMESE-ENGLISH CODE-SWITCHING
# =============================================================================

FEW_SHOT_EXAMPLES = """
Here are examples of the expected output format for Vietnamese-English code-switched speech:

**Example 1: Technology content with English terms**
Audio segment discussing software development:
```json
{
  "sentences": [
    {
      "text": "Hôm nay mình sẽ review cái framework mới này, nó rất là powerful.",
      "start": 0.0,
      "end": 4.5,
      "duration": 4.5,
      "translation": "Hôm nay mình sẽ đánh giá khung phần mềm mới này, nó rất là mạnh mẽ."
    },
    {
      "text": "Cái feature chính của nó là support real-time collaboration.",
      "start": 4.5,
      "end": 8.2,
      "duration": 3.7,
      "translation": "Tính năng chính của nó là hỗ trợ cộng tác theo thời gian thực."
    }
  ]
}
```

**Example 2: Casual conversation with slang**
Audio segment from a lifestyle vlog:
```json
{
  "sentences": [
    {
      "text": "Okay các bạn, hôm nay mình sẽ đi shopping ở mall này.",
      "start": 0.0,
      "end": 3.8,
      "duration": 3.8,
      "translation": "Được rồi các bạn, hôm nay mình sẽ đi mua sắm ở trung tâm thương mại này."
    },
    {
      "text": "Cái store này sale off đến fifty percent luôn á.",
      "start": 3.8,
      "end": 7.1,
      "duration": 3.3,
      "translation": "Cửa hàng này đang giảm giá đến năm mươi phần trăm luôn đấy."
    },
    {
      "text": "Mình thấy outfit này cute quá, definitely phải mua.",
      "start": 7.1,
      "end": 10.5,
      "duration": 3.4,
      "translation": "Mình thấy bộ đồ này dễ thương quá, chắc chắn phải mua."
    }
  ]
}
```

**Example 3: Educational content with proper nouns**
Audio segment from a history video:
```json
{
  "sentences": [
    {
      "text": "Như các bạn biết, TikTok bây giờ rất là viral ở Việt Nam.",
      "start": 0.0,
      "end": 4.2,
      "duration": 4.2,
      "translation": "Như các bạn biết, TikTok bây giờ rất là lan truyền ở Việt Nam."
    },
    {
      "text": "Creator Hà Bang Chủ là một trong những người nổi tiếng nhất.",
      "start": 4.2,
      "end": 8.0,
      "duration": 3.8,
      "translation": "Nhà sáng tạo nội dung Hà Bang Chủ là một trong những người nổi tiếng nhất."
    }
  ]
}
```

**Example 4: Splitting longer continuous speech**
When a speaker talks for an extended period, segment at natural boundaries:

```json
{
  "sentences": [
    {
      "text": "Các bạn ơi, hôm nay mình muốn share với các bạn về kinh nghiệm học programming của mình.",
      "start": 0.0,
      "end": 7.2,
      "duration": 7.2,
      "translation": "Các bạn ơi, hôm nay mình muốn chia sẻ với các bạn về kinh nghiệm học lập trình của mình."
    },
    {
      "text": "Thực ra mình bắt đầu learn code từ năm 2020.",
      "start": 7.2,
      "end": 11.5,
      "duration": 4.3,
      "translation": "Thực ra mình bắt đầu học lập trình từ năm 2020."
    },
    {
      "text": "Lúc đó mình còn không biết gì về computer science cả.",
      "start": 11.5,
      "end": 16.0,
      "duration": 4.5,
      "translation": "Lúc đó mình còn không biết gì về khoa học máy tính cả."
    },
    {
      "text": "Nhưng mà sau một thời gian thì mình đã improve rất nhiều.",
      "start": 16.0,
      "end": 21.3,
      "duration": 5.3,
      "translation": "Nhưng mà sau một thời gian thì mình đã tiến bộ rất nhiều."
    },
    {
      "text": "Và bây giờ mình có thể build được những project khá là complex.",
      "start": 21.3,
      "end": 26.5,
      "duration": 5.2,
      "translation": "Và bây giờ mình có thể xây dựng được những dự án khá là phức tạp."
    }
  ]
}
```
"""


# =============================================================================
# STRUCTURED OUTPUT PROMPT
# =============================================================================

PROCESSING_PROMPT = f"""You are an expert audio transcriptionist and translator for Vietnamese-English code-switched speech.

CRITICAL: TIMESTAMP ACCURACY IS ESSENTIAL
- The start and end timestamps MUST precisely match when the text is actually spoken
- Listen carefully to where each sentence begins and ends in the audio
- Each sentence's timestamps must align exactly with the audio segment
- Do NOT guess timestamps - they must reflect the actual audio timing

TASK:
1. Listen to the ENTIRE audio first to understand context
2. Identify all speech segments (skip music, sound effects, jingles)
3. Segment into natural sentences
4. Transcribe each sentence preserving code-switching
5. Translate each sentence to Vietnamese
6. Assign accurate timestamps that match the spoken audio

TRANSCRIPTION RULES:
- Preserve code-switching exactly (Vietnamese as Vietnamese, English as English)
- Use correct Vietnamese diacritics (đ, ă, â, ê, ô, ơ, ư, and all tone marks)
- Preserve proper nouns, brand names, technical terms as spoken
- Mark unclear sections with [unclear]
- Timestamps in seconds (float), relative to audio start

SENTENCE GUIDELINES:
- Aim for natural sentence lengths (typically 5-15 seconds)
- Split at natural boundaries: pauses, conjunctions, topic shifts
- Vietnamese split points: "và", "nhưng", "nên", "vì", "mà", "rồi", "thì"
- Long continuous speech should be broken into multiple sentences

TRANSLATION RULES:
- Translate ALL English words/phrases into natural Vietnamese
- Maintain original meaning and tone
- Preserve proper nouns unless they have established Vietnamese forms
- If translation impossible, output "[translation_missing]"

{FEW_SHOT_EXAMPLES}

OUTPUT FORMAT:
JSON object with a "sentences" array. Each sentence has:
- "text": Original transcription (code-switched)
- "start": Start time in seconds (float) - MUST match audio
- "end": End time in seconds (float) - MUST match audio
- "duration": Duration in seconds
- "translation": Pure Vietnamese translation

Now transcribe and translate the audio with accurate timestamps:"""


# =============================================================================
# STRUCTURED OUTPUT SCHEMA
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
            "description": "Start time in seconds - must accurately match when the text is spoken"
        },
        "end": {
            "type": "number",
            "description": "End time in seconds - must accurately match when the text ends"
        },
        "duration": {
            "type": "number",
            "description": "Duration in seconds (end - start)"
        },
        "translation": {
            "type": "string",
            "description": "Pure Vietnamese translation"
        }
    },
    "required": ["text", "start", "end", "duration", "translation"]
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": SENTENCE_SCHEMA,
            "description": "Array of transcribed and translated sentences"
        }
    },
    "required": ["sentences"]
}


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

@dataclass
class ApiKey:
    """Represents a Gemini API key with usage tracking."""
    key_id: int
    key_name: str
    api_key: str
    requests_remaining: int
    is_active: bool


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
        
        if not api_key:
            if idx == 1:
                api_key = os.environ.get("GEMINI_API_KEY")
        
        if not api_key:
            break
        
        keys.append(ApiKey(
            key_id=idx,
            key_name=f"env_key_{idx}",
            api_key=api_key,
            requests_remaining=1500,
            is_active=True
        ))
        idx += 1
    
    return keys


def get_available_api_key() -> Optional[ApiKey]:
    """
    Get next available API key.
    
    Returns:
        ApiKey if available, None if all keys exhausted.
    """
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
    max_chunk_duration_sec: float = MAX_AUDIO_DURATION_SECONDS,
    overlap_sec: float = CHUNK_OVERLAP_SECONDS
) -> List[Tuple[Path, float, float]]:
    """
    Split audio file into chunks with adaptive sizing.
    
    Uses an adaptive approach that:
    1. Calculates the minimum number of chunks needed
    2. Divides the audio evenly across chunks
    3. Adds overlap between chunks for transcript consistency
    
    Args:
        audio_path: Path to the audio file.
        max_chunk_duration_sec: Maximum duration per chunk in seconds.
        overlap_sec: Overlap between chunks in seconds (15-20s recommended).
        
    Returns:
        List of tuples (chunk_path, start_offset_sec, end_offset_sec).
    """
    from pydub import AudioSegment
    import math
    
    audio = AudioSegment.from_file(str(audio_path))
    duration_ms = len(audio)
    duration_sec = duration_ms / 1000.0
    
    # No chunking needed if audio is short enough
    if duration_sec <= max_chunk_duration_sec:
        return [(audio_path, 0.0, duration_sec)]
    
    # Calculate number of chunks needed (adaptive)
    # Formula: n = ceil(duration / max_chunk_duration)
    num_chunks = math.ceil(duration_sec / max_chunk_duration_sec)
    
    # Calculate the actual chunk duration (evenly distributed)
    # Each chunk covers: total_duration / num_chunks
    # With overlap, the effective content per chunk is slightly more
    base_chunk_duration_sec = duration_sec / num_chunks
    
    print(f"[INFO] Audio duration {duration_sec:.1f}s > {max_chunk_duration_sec}s, chunking...")
    print(f"[INFO] Adaptive chunking: {num_chunks} chunks, ~{base_chunk_duration_sec:.1f}s each, {overlap_sec}s overlap")
    
    chunks = []
    temp_dir = Path(tempfile.mkdtemp(prefix="gemini_chunks_"))
    
    for chunk_idx in range(num_chunks):
        # Calculate start and end for this chunk
        # Start: chunk_idx * base_duration - overlap (except first chunk)
        # End: (chunk_idx + 1) * base_duration + overlap (except last chunk)
        
        if chunk_idx == 0:
            start_sec = 0.0
        else:
            # Include overlap from previous chunk
            start_sec = (chunk_idx * base_chunk_duration_sec) - (overlap_sec / 2)
        
        if chunk_idx == num_chunks - 1:
            end_sec = duration_sec
        else:
            # Include overlap into next chunk
            end_sec = ((chunk_idx + 1) * base_chunk_duration_sec) + (overlap_sec / 2)
        
        # Clamp to valid range
        start_sec = max(0.0, start_sec)
        end_sec = min(duration_sec, end_sec)
        
        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)
        
        chunk = audio[start_ms:end_ms]
        chunk_path = temp_dir / f"chunk_{chunk_idx:03d}.wav"
        chunk.export(str(chunk_path), format="wav")
        
        chunks.append((
            chunk_path,
            start_sec,  # Start offset in seconds
            end_sec     # End offset in seconds
        ))
        
        print(f"  Chunk {chunk_idx}: {start_sec:.1f}s - {end_sec:.1f}s ({end_sec - start_sec:.1f}s)")
    
    print(f"[INFO] Created {len(chunks)} chunks")
    return chunks


# =============================================================================
# TEXT SIMILARITY FOR DEDUPLICATION
# =============================================================================

def text_similarity(text1: str, text2: str) -> float:
    """
    Calculate text similarity ratio using SequenceMatcher.
    
    Args:
        text1: First text string.
        text2: Second text string.
        
    Returns:
        Similarity ratio between 0.0 and 1.0.
    """
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
    
    Uses moderate strategy: remove sentences with >80% text similarity
    AND timestamp overlap within ±2 seconds. Keeps the version from
    the chunk where the sentence starts (earlier chunk).
    
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
        
        # Check against already-added sentences
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
        
    Raises:
        Exception: If processing fails after retries.
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
    
    # Initialize client with structured output and thinking config
    genai.configure(api_key=api_key.api_key)
    
    # Enhanced generation config with higher temperature for better boundary decisions
    generation_config = {
        "temperature": 1.0,  # Higher temp for more creative sentence boundary decisions
        "top_p": 0.95,
        "max_output_tokens": 65536,
        "response_mime_type": "application/json",
        "response_schema": OUTPUT_SCHEMA
    }
    
    # Add thinking config for Gemini 2.5 Pro - enables explicit reasoning
    # about sentence boundaries and segmentation decisions
    thinking_config = None
    if "2.5" in model:  # Only for Gemini 2.5 models
        try:
            from google.genai import types
            thinking_config = types.ThinkingConfig(
                thinking_budget=THINKING_BUDGET  # 15668 tokens for reasoning
            )
            generation_config["thinking_config"] = thinking_config
        except (ImportError, AttributeError):
            # Fallback if types module not available
            pass
    
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
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.generate_content([PROCESSING_PROMPT, audio_part])
            
            # Check for blocked content
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                if hasattr(response.prompt_feedback, 'block_reason') and response.prompt_feedback.block_reason:
                    raise ValueError(
                        f"Content blocked: {response.prompt_feedback.block_reason}"
                    )
            
            # Parse JSON response
            response_text = response.text.strip()
            
            # Try to extract JSON if wrapped in markdown code blocks
            if response_text.startswith("```"):
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
                if json_match:
                    response_text = json_match.group(1)
            
            result = json.loads(response_text)
            sentences = result.get('sentences', [])
            
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
    if duration_seconds and duration_seconds > MAX_AUDIO_DURATION_SECONDS:
        chunks = chunk_audio_file(audio_path)
        
        all_sentences = []
        all_metadata = {
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
        print(f"[INFO] Deduplicating {len(all_sentences)} sentences from {len(chunks)} chunks...")
        deduplicated = deduplicate_sentences(all_sentences)
        print(f"[INFO] Result: {len(deduplicated)} sentences after deduplication")
        
        all_metadata["sentence_count"] = len(deduplicated)
        all_metadata["sentences_before_dedup"] = len(all_sentences)
        all_metadata["sentences_after_dedup"] = len(deduplicated)
        
        return deduplicated, all_metadata
    
    else:
        # Single chunk processing
        sentences, metadata = process_audio_chunk(audio_path, api_key, model, offset_seconds=0.0)
        
        metadata["sentence_count"] = len(sentences)
        
        return sentences, metadata


# =============================================================================
# VALIDATION AND ISSUE DETECTION
# =============================================================================

def validate_and_flag_issues(
    sentences: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], bool, List[int]]:
    """
    Validate sentences and flag translation issues.
    
    Args:
        sentences: List of sentence dictionaries.
        
    Returns:
        Tuple of (validated_sentences, has_issues, issue_indices).
    """
    has_issues = False
    issue_indices = []
    validated = []
    
    for idx, sentence in enumerate(sentences):
        # Ensure required fields exist
        if 'text' not in sentence:
            sentence['text'] = '[transcription_missing]'
        
        if 'start' not in sentence:
            sentence['start'] = 0.0
            
        if 'end' not in sentence:
            sentence['end'] = sentence.get('start', 0.0)
            
        if 'duration' not in sentence:
            sentence['duration'] = sentence['end'] - sentence['start']
        
        # Check translation
        translation = sentence.get('translation', '')
        
        is_missing = (
            not translation or
            translation.strip() == '' or
            translation.strip().lower() in [m.lower() if m else '' for m in TRANSLATION_MISSING_MARKERS if m]
        )
        
        if is_missing:
            sentence['translation'] = '[translation_missing]'
            has_issues = True
            issue_indices.append(idx)
        
        validated.append(sentence)
    
    return validated, has_issues, issue_indices


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_processing(
    limit: int = 10,
    include_existing: bool = False,
    state_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get samples ready for Gemini processing.
    
    Args:
        limit: Maximum number of samples to return.
        include_existing: If True, include samples that already have transcripts.
        state_filter: Filter by processing state (default: RAW).
        
    Returns:
        List of sample dictionaries.
    """
    conn = get_pg_connection()
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            state = state_filter or 'RAW'
            
            if include_existing:
                cur.execute(
                    """
                    SELECT 
                        s.sample_id,
                        s.external_id,
                        s.audio_file_path,
                        s.text_file_path,
                        s.subtitle_type,
                        s.duration_seconds,
                        s.processing_state,
                        s.needs_translation_review,
                        tr.transcript_text AS existing_transcript,
                        tr.revision_type AS existing_revision_type
                    FROM samples s
                    LEFT JOIN transcript_revisions tr 
                        ON s.sample_id = tr.sample_id 
                        AND tr.version = s.current_transcript_version
                    WHERE s.processing_state = %s::processing_state
                      AND s.is_deleted = FALSE
                    ORDER BY s.priority DESC, s.created_at ASC
                    LIMIT %s
                    """,
                    (state, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT 
                        s.sample_id,
                        s.external_id,
                        s.audio_file_path,
                        s.text_file_path,
                        s.subtitle_type,
                        s.duration_seconds,
                        s.processing_state,
                        s.needs_translation_review,
                        tr.transcript_text AS existing_transcript,
                        tr.revision_type AS existing_revision_type
                    FROM samples s
                    LEFT JOIN transcript_revisions tr 
                        ON s.sample_id = tr.sample_id 
                        AND tr.version = s.current_transcript_version
                    WHERE s.processing_state = %s::processing_state
                      AND s.is_deleted = FALSE
                      AND NOT EXISTS (
                          SELECT 1 FROM transcript_revisions tr2
                          WHERE tr2.sample_id = s.sample_id
                          AND tr2.revision_type = 'gemini_processed'
                      )
                    ORDER BY s.priority DESC, s.created_at ASC
                    LIMIT %s
                    """,
                    (state, limit)
                )
            
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def save_gemini_results(
    sample_id: str,
    sentences: List[Dict[str, Any]],
    has_translation_issues: bool,
    translation_issue_indices: List[int],
    metadata: Dict[str, Any],
    executor: str = "gemini_process"
) -> Tuple[str, str]:
    """
    Save Gemini processing results to database.
    
    Creates transcript revision with sentence_timestamps and translation revision
    with sentence_translations. Transitions sample to TRANSLATED state.
    
    Args:
        sample_id: UUID of the sample.
        sentences: List of sentence dictionaries.
        has_translation_issues: Whether any translations are missing.
        translation_issue_indices: Indices of sentences with issues.
        metadata: Processing metadata.
        executor: Name of executor for logging.
        
    Returns:
        Tuple of (transcript_revision_id, translation_revision_id).
    """
    conn = get_pg_connection()
    
    try:
        with conn.cursor() as cur:
            # Build full transcript text
            full_transcript = " ".join([s.get('text', '') for s in sentences])
            
            # Build full translation text
            full_translation = " ".join([
                s.get('translation', '[translation_missing]') 
                for s in sentences
            ])
            
            # Insert transcript revision with sentence_timestamps
            cur.execute(
                """
                SELECT add_transcript_revision(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    sample_id,
                    full_transcript,
                    'gemini_processed',
                    metadata.get('model'),
                    None,  # word_timestamps
                    Json(sentences),  # sentence_timestamps with translations
                    executor,
                    has_translation_issues,
                    translation_issue_indices if translation_issue_indices else None
                )
            )
            transcript_revision_id = cur.fetchone()[0]
            
            # Build sentence_translations JSONB for translation revision
            sentence_translations = [
                {
                    "source": s.get('text', ''),
                    "translation": s.get('translation', '[translation_missing]'),
                    "start": s.get('start', 0),
                    "end": s.get('end', 0),
                    "sentence_index": idx
                }
                for idx, s in enumerate(sentences)
            ]
            
            # Insert translation revision
            cur.execute(
                """
                SELECT add_translation_revision(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    sample_id,
                    full_translation,
                    'gemini_processed',
                    str(transcript_revision_id),
                    Json(sentence_translations),
                    metadata.get('model'),
                    metadata.get('model'),
                    None,  # api_cost_usd
                    executor
                )
            )
            translation_revision_id = cur.fetchone()[0]
            
            # Transition state to TRANSLATED
            cur.execute(
                """
                SELECT transition_sample_state(%s, 'TRANSLATED'::processing_state, %s)
                """,
                (sample_id, executor)
            )
            
            # Set needs_translation_review flag if issues detected
            if has_translation_issues:
                cur.execute(
                    """
                    UPDATE samples 
                    SET needs_translation_review = TRUE, updated_at = NOW()
                    WHERE sample_id = %s
                    """,
                    (sample_id,)
                )
            
            conn.commit()
            return str(transcript_revision_id), str(translation_revision_id)
            
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to save results: {e}")
    finally:
        conn.close()


def process_sample(
    sample: Dict[str, Any],
    data_root: Path,
    model: str = DEFAULT_MODEL,
    replace_existing: bool = False
) -> bool:
    """
    Process a single sample with Gemini.
    
    Args:
        sample: Sample dictionary from database.
        data_root: Root directory for data files.
        model: Gemini model to use.
        replace_existing: If True, replace existing transcript.
        
    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    audio_file_path = sample["audio_file_path"]
    existing_transcript = sample.get("existing_transcript")
    existing_type = sample.get("existing_revision_type")
    
    print(f"\n{'='*60}")
    print(f"Processing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Audio: {audio_file_path}")
    if existing_transcript:
        print(f"Existing transcript: {len(existing_transcript)} chars ({existing_type})")
    print(f"{'='*60}")
    
    # Resolve audio path
    audio_path = data_root / audio_file_path
    if not audio_path.exists():
        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            print(f"[ERROR] Audio file not found: {audio_file_path}")
            return False
    
    start_time = time.time()
    
    try:
        # Get API key
        api_key = get_available_api_key()
        if not api_key:
            raise ValueError("No API keys available for processing")
        
        print(f"[INFO] Using API key: {api_key.key_name}")
        print(f"[INFO] Using model: {model}")
        
        # Process audio
        print(f"[INFO] Processing audio (transcription + translation)...")
        sentences, metadata = process_audio_file(audio_path, api_key, model)
        
        print(f"[INFO] Processing complete ({metadata.get('processing_time_seconds', 0):.1f}s)")
        print(f"[INFO] Sentence count: {len(sentences)}")
        
        # Validate and detect issues
        validated_sentences, has_issues, issue_indices = validate_and_flag_issues(sentences)
        
        if has_issues:
            print(f"[WARNING] Translation issues detected in {len(issue_indices)} sentences")
            print(f"[WARNING] Issue indices: {issue_indices[:10]}{'...' if len(issue_indices) > 10 else ''}")
        
        # Preview first few sentences
        print(f"\n[PREVIEW] First 3 sentences:")
        for i, s in enumerate(validated_sentences[:3]):
            print(f"  {i+1}. [{s['start']:.1f}s-{s['end']:.1f}s]")
            text_preview = s['text'][:80] + "..." if len(s['text']) > 80 else s['text']
            trans_preview = s['translation'][:80] + "..." if len(s['translation']) > 80 else s['translation']
            print(f"     Text: {text_preview}")
            print(f"     Trans: {trans_preview}")
        
        # Save to database
        print(f"\n[INFO] Saving to database...")
        transcript_rev_id, translation_rev_id = save_gemini_results(
            sample_id=sample_id,
            sentences=validated_sentences,
            has_translation_issues=has_issues,
            translation_issue_indices=issue_indices,
            metadata=metadata
        )
        
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # Log success
        log_processing(
            operation="gemini_process",
            success=True,
            sample_id=sample_id,
            previous_state=str(sample.get("processing_state")),
            new_state="TRANSLATED",
            executor="gemini_process",
            execution_time_ms=execution_time_ms,
            input_params={
                "audio_file": audio_file_path,
                "model": model,
                "had_existing_transcript": existing_transcript is not None
            },
            output_summary={
                "transcript_revision_id": transcript_rev_id,
                "translation_revision_id": translation_rev_id,
                "sentence_count": len(validated_sentences),
                "has_translation_issues": has_issues,
                "issue_count": len(issue_indices)
            }
        )
        
        print(f"\n[SUCCESS] Processed {external_id}")
        print(f"  Transcript Revision: {transcript_rev_id}")
        print(f"  Translation Revision: {translation_rev_id}")
        print(f"  Sentences: {len(validated_sentences)}")
        print(f"  Has Issues: {has_issues}")
        print(f"  Time: {execution_time_ms/1000:.2f}s")
        
        return True
        
    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        log_processing(
            operation="gemini_process",
            success=False,
            sample_id=sample_id,
            executor="gemini_process",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )
        
        print(f"[ERROR] Failed to process {external_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for Gemini unified processing."""
    parser = argparse.ArgumentParser(
        description="Process audio files with Gemini (transcription + translation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Process a specific sample
    python gemini_process.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of RAW samples
    python gemini_process.py --batch --limit 5

    # Re-process samples that already have transcripts
    python gemini_process.py --batch --replace-existing --limit 5

    # Use Pro model for better quality
    python gemini_process.py --batch --model gemini-2.5-pro

Environment Variables (from .env file):
    GEMINI_API_KEY_1 : Primary Gemini API key
    GEMINI_API_KEY_2 : Backup API key for rate limit rotation
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to process"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in RAW state"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum samples to process in batch mode (default: 5)"
    )
    parser.add_argument(
        "--model",
        choices=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-exp"],
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Re-process samples that already have transcripts"
    )
    parser.add_argument(
        "--state",
        default="RAW",
        help="Processing state to filter by (default: RAW)"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/app/data"),
        help="Root directory for data files (default: /app/data)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making changes"
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
        print(f"Found {len(env_keys)} API key(s) in environment:")
        for k in env_keys:
            masked = k.api_key[:8] + "..." + k.api_key[-4:]
            print(f"  - {k.key_name}: {masked}")
        return
    
    if not args.sample_id and not args.batch:
        parser.print_help()
        print("\nError: Specify --sample-id or --batch")
        sys.exit(1)
    
    # Verify API key
    api_key = get_available_api_key()
    if not api_key:
        print("[ERROR] No API keys available.")
        print("Set GEMINI_API_KEY_1 in your .env file or environment.")
        sys.exit(1)
    
    print(f"Using API key: {api_key.key_name}")
    print(f"Using model: {args.model}")
    
    # Determine data root
    data_root = args.data_root
    if not data_root.exists():
        data_root = Path("data")
        if not data_root.exists():
            data_root = Path(".")
    
    print(f"Data root: {data_root}")
    
    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_processing(
            limit=args.limit,
            include_existing=args.replace_existing,
            state_filter=args.state
        )
        print(f"Found {len(samples)} samples to process:")
        for s in samples:
            existing = s.get('existing_transcript')
            existing_info = f" (has {len(existing)} char transcript)" if existing else " (no transcript)"
            print(f"  - {s['external_id']}: {s['audio_file_path']}{existing_info}")
        return
    
    # Process samples
    if args.sample_id:
        conn = get_pg_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        s.sample_id,
                        s.external_id,
                        s.audio_file_path,
                        s.text_file_path,
                        s.subtitle_type,
                        s.duration_seconds,
                        s.processing_state,
                        s.needs_translation_review,
                        tr.transcript_text AS existing_transcript,
                        tr.revision_type AS existing_revision_type
                    FROM samples s
                    LEFT JOIN transcript_revisions tr 
                        ON s.sample_id = tr.sample_id 
                        AND tr.version = s.current_transcript_version
                    WHERE s.sample_id = %s
                    """,
                    (args.sample_id,)
                )
                sample = cur.fetchone()
                if sample:
                    process_sample(
                        dict(sample),
                        data_root,
                        model=args.model,
                        replace_existing=args.replace_existing
                    )
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_processing(
            limit=args.limit,
            include_existing=args.replace_existing,
            state_filter=args.state
        )
        print(f"\n[INFO] Found {len(samples)} samples to process")
        
        success_count = 0
        fail_count = 0
        
        for sample in samples:
            if process_sample(
                sample,
                data_root,
                model=args.model,
                replace_existing=args.replace_existing
            ):
                success_count += 1
            else:
                fail_count += 1
            
            if success_count + fail_count < len(samples):
                time.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"Batch processing complete")
        print(f"  Success: {success_count}")
        print(f"  Failed: {fail_count}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

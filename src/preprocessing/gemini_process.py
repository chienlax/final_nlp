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
    get_chunks_by_video,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Supported audio formats for Gemini
SUPPORTED_AUDIO_FORMATS = {'.wav', '.mp3', '.aiff', '.aac', '.ogg', '.flac'}

# Gemini settings
DEFAULT_MODEL = "gemini-2.5-pro"

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

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
    "start": 0.00,
    "end": 4.54,
    "translation": "Hôm nay mình sẽ đánh giá khung phần mềm mới này, nó rất là mạnh mẽ."
  },
  {
    "text": "Cái feature chính của nó là support real-time collaboration.",
    "start": 4.54,
    "end": 8.22,
    "translation": "Tính năng chính của nó là hỗ trợ cộng tác theo thời gian thực."
  }
]
```

**Example 2: Casual conversation with slang**
```json
[
  {
    "text": "Okay các bạn, hôm nay mình sẽ đi shopping ở mall này.",
    "start": 3.81,
    "end": 7.03,
    "translation": "Được rồi các bạn, hôm nay mình sẽ đi mua sắm ở trung tâm thương mại này."
  },
  {
    "text": "Cái store này sale off đến fifty percent luôn á.",
    "start": 9.92,
    "end": 11.65,
    "translation": "Cửa hàng này đang giảm giá đến năm mươi phần trăm luôn đấy."
  }
]
```

**Example 3: Splitting longer continuous speech**
```json
[
  {
    "text": "Các bạn ơi, hôm nay mình muốn share với các bạn về kinh nghiệm học programming của mình.",
    "start": 0.00,
    "end": 7.62,
    "translation": "Các bạn ơi, hôm nay mình muốn chia sẻ với các bạn về kinh nghiệm học lập trình của mình."
  },
  {
    "text": "Thực ra mình bắt đầu learn code từ năm 2020.",
    "start": 7.62,
    "end": 11.55,
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
- The start and end timestamps MUST precisely match when the text is actually spoken down to milisecond
- The transcript length MUST match the total audio length. You can not transcripe an 8 minute audio file to a JSON file that only contain total 5 minutes of content.
- Listen carefully to where each sentence begins and ends in the audio
- Do NOT guess timestamps - they must reflect the actual audio timing. Normally, there would be music or intro, ... in between speech section. You MUST exclude them and ONLY transcipe the speech section. THIS IS A MUST-DO REQUIREMENTS.

GENERAL TRANSCRIPTION AND TRANSLATION RULES: ABSOLUTE HONESTY - NO CENSORSHIP.
* Transcript/Translate 100% of the content; **DO NOT** add, remove, summarize, or censor.
* Transcript/Translate $18+$, violent, and sensitive scenes fully, exactly as they appear in the original audio.
* **DO NOT** invent your own plot details.
* **DO NOT** skip or tone down descriptions of sex or violence.

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


class ApiKeyPool:
    """
    Manages rotation of multiple Gemini API keys with rate-limit blacklisting.
    
    Uses round-robin selection based on usage count. When a key is rate-limited,
    it's blacklisted for 60 seconds before being eligible again.
    """
    
    def __init__(self, keys: List[ApiKey]):
        """
        Initialize the API key pool.
        
        Args:
            keys: List of ApiKey objects to rotate through.
        
        Raises:
            ValueError: If keys list is empty.
        """
        if not keys:
            raise ValueError("ApiKeyPool requires at least one API key")
        
        self.keys = keys
        self.usage_count: Dict[str, int] = {key.key_name: 0 for key in keys}
        self.rate_limited_until: Dict[str, float] = {}
    
    def get_next_key(self) -> ApiKey:
        """
        Get next available API key using round-robin based on usage count.
        
        Returns:
            ApiKey that is not currently rate-limited and has lowest usage count.
        
        Raises:
            RuntimeError: If all keys are currently rate-limited.
        """
        current_time = time.time()
        
        # Find available (non-rate-limited) keys
        available_keys = []
        for key in self.keys:
            blacklist_until = self.rate_limited_until.get(key.key_name, 0)
            if current_time >= blacklist_until:
                available_keys.append(key)
        
        if not available_keys:
            # Calculate wait time until next key becomes available
            min_wait = min(self.rate_limited_until.values()) - current_time
            raise RuntimeError(
                f"All API keys are rate-limited. Wait {min_wait:.1f}s or add more keys."
            )
        
        # Select key with lowest usage count (round-robin)
        next_key = min(available_keys, key=lambda k: self.usage_count[k.key_name])
        self.usage_count[next_key.key_name] += 1
        
        print(
            f"[INFO] Selected {next_key.key_name} (usage: {self.usage_count[next_key.key_name]}, "
            f"available: {len(available_keys)}/{len(self.keys)})"
        )
        
        return next_key
    
    def mark_rate_limited(self, key_name: str, timeout_seconds: int = 60) -> None:
        """
        Mark an API key as rate-limited for specified duration.
        
        Args:
            key_name: Name of the key to blacklist.
            timeout_seconds: Duration in seconds to blacklist (default: 60s).
        """
        blacklist_until = time.time() + timeout_seconds
        self.rate_limited_until[key_name] = blacklist_until
        
        print(
            f"[WARNING] API key {key_name} rate-limited until "
            f"{time.strftime('%H:%M:%S', time.localtime(blacklist_until))}"
        )
    
    def reset_key(self, key_name: str) -> None:
        """
        Reset rate-limit status for a specific key (make it available immediately).
        
        Args:
            key_name: Name of the key to reset.
        """
        if key_name in self.rate_limited_until:
            del self.rate_limited_until[key_name]
            print(f"[INFO] Reset rate-limit for {key_name}")


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


# =============================================================================
# GEMINI API CALLS
# =============================================================================

def process_audio_chunk(
    audio_path: Path,
    api_key_pool: ApiKeyPool,
    model: str = DEFAULT_MODEL,
    offset_seconds: float = 0.0
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Process a single audio chunk with Gemini using API key pool.

    Args:
        audio_path: Path to the audio file/chunk.
        api_key_pool: ApiKeyPool for key rotation and rate-limit handling.
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

    start_time = time.time()
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            # Get next available API key
            api_key = api_key_pool.get_next_key()
            
            # Initialize client with selected key
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
                "api_key": api_key.key_name,
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
                # Mark this key as rate-limited
                api_key_pool.mark_rate_limited(api_key.key_name, timeout_seconds=60)
                print(f"  [WARNING] Rate limit hit on {api_key.key_name}, switching keys...")
                # Continue to retry with different key (no sleep needed)
            elif attempt < MAX_RETRIES - 1:
                print(f"  [WARNING] Attempt {attempt + 1} failed: {e}")
                time.sleep(RETRY_DELAY_SECONDS)

    raise Exception(f"Processing failed after {MAX_RETRIES} attempts: {last_error}")


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
    Process a video with Gemini using pre-chunked audio from database.

    Processes either all pending chunks (if chunk_id=None) or a specific chunk.
    Uses ApiKeyPool for automatic key rotation and rate-limit handling.

    Args:
        video_id: Video identifier.
        data_root: Root directory for data files (used for path resolution).
        model: Gemini model to use (default: gemini-2.0-flash-exp).
        chunk_id: Optional specific chunk ID to process. If None, processes all pending chunks.

    Returns:
        True if successful, False otherwise.
    """
    # Get video from database
    video = get_video(video_id)
    if not video:
        print(f"[ERROR] Video not found: {video_id}")
        return False

    print(f"\n{'='*60}")
    print(f"Processing: {video['title']}")
    print(f"Video ID: {video_id}")
    print(f"{'='*60}")

    # Initialize API key pool
    env_keys = get_api_keys_from_env()
    if not env_keys:
        print(f"[ERROR] No API keys found in environment")
        return False
    
    api_key_pool = ApiKeyPool(env_keys)
    print(f"[INFO] Initialized API key pool with {len(env_keys)} keys")
    print(f"[INFO] Using model: {model}")

    start_time = time.time()

    try:
        # Get chunks to process
        if chunk_id is not None:
            # Process specific chunk
            chunk = get_chunk(chunk_id)
            if not chunk:
                print(f"[ERROR] Chunk not found: {chunk_id}")
                return False
            
            if chunk['video_id'] != video_id:
                print(f"[ERROR] Chunk {chunk_id} does not belong to video {video_id}")
                return False
            
            chunks_to_process = [chunk]
        else:
            # Process all pending chunks for this video
            all_chunks = get_chunks_by_video(video_id)
            chunks_to_process = [
                c for c in all_chunks 
                if c['processing_state'] in ('pending', 'rejected')  # 'rejected' used for failed chunks
            ]
            
            if not chunks_to_process:
                print(f"[INFO] No pending chunks to process for {video_id}")
                return True

        print(f"[INFO] Processing {len(chunks_to_process)} chunk(s)...")

        # Process each chunk
        for idx, chunk in enumerate(chunks_to_process, 1):
            chunk_id_current = chunk['chunk_id']
            chunk_index = chunk['chunk_index']
            audio_path_str = chunk['audio_path']
            
            print(f"\n[{idx}/{len(chunks_to_process)}] Chunk {chunk_index} (ID: {chunk_id_current})")
            print(f"  Audio: {audio_path_str}")
            
            # Resolve audio path from chunk record (stored relative to project root)
            # chunk['audio_path'] format: 'data/raw/chunks/<video_id>/chunk_<idx>.wav'
            audio_path = Path(data_root).parent / audio_path_str
            
            if not audio_path.exists():
                print(f"  [ERROR] Chunk audio file not found: {audio_path}")
                update_chunk_state(chunk_id_current, 'failed')
                continue
            
            # Verify chunk duration matches expected (6 minutes max)
            actual_duration_sec = get_audio_duration_seconds(audio_path)
            expected_duration_sec = (chunk['end_ms'] - chunk['start_ms']) / 1000.0
            
            if actual_duration_sec:
                print(f"  [INFO] Chunk duration: {actual_duration_sec:.1f}s (expected: {expected_duration_sec:.1f}s)")
                if abs(actual_duration_sec - expected_duration_sec) > 1.0:
                    print(f"  [WARNING] Duration mismatch! Actual: {actual_duration_sec:.1f}s, Expected: {expected_duration_sec:.1f}s")
            else:
                print(f"  [WARNING] Could not verify chunk duration")

            # Calculate offset for timestamps
            offset_seconds = chunk['start_ms'] / 1000.0

            # Process chunk with Gemini
            try:
                print(f"  [INFO] Transcribing with Gemini...")
                sentences, metadata = process_audio_chunk(
                    audio_path, 
                    api_key_pool, 
                    model,
                    offset_seconds=offset_seconds
                )

                print(f"  [INFO] Complete ({metadata.get('processing_time_seconds', 0):.1f}s)")
                print(f"  [INFO] Sentences: {len(sentences)}")
                print(f"  [INFO] API key used: {metadata.get('api_key', 'unknown')}")

                # Preview first sentence
                if sentences:
                    s = sentences[0]
                    text_preview = s['text'][:50] + "..." if len(s['text']) > 50 else s['text']
                    print(f"  [PREVIEW] [{s['start']:.1f}s-{s['end']:.1f}s] {text_preview}")

                # Save to database (will replace existing segments for this chunk)
                print(f"  [INFO] Saving to database...")
                segment_count = insert_segments(video_id, sentences, chunk_id=chunk_id_current)
                
                # Update chunk state
                update_chunk_state(chunk_id_current, 'transcribed')
                print(f"  [SUCCESS] Saved {segment_count} segments")

            except Exception as e:
                print(f"  [ERROR] Failed to process chunk {chunk_id_current}: {e}")
                update_chunk_state(chunk_id_current, 'rejected')  # Mark as rejected (failed is not valid state)
                import traceback
                traceback.print_exc()
                continue

        # Aggregate chunk states to update video state
        agg_state = aggregate_chunk_state(video_id)
        update_video_state(video_id, agg_state)

        elapsed = time.time() - start_time
        print(f"\n[SUCCESS] Processed {video_id}")
        print(f"  Video state: {agg_state}")
        print(f"  Total time: {elapsed:.2f}s")

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
        # Initialize API key pool
        env_keys = get_api_keys_from_env()
        if not env_keys:
            raise ValueError("No API keys available")
        
        api_key_pool = ApiKeyPool(env_keys)
        print(f"[INFO] Using {len(env_keys)} API key(s)")

        # Process audio (no offset for standalone)
        sentences, metadata = process_audio_chunk(
            audio_path, 
            api_key_pool, 
            model, 
            offset_seconds=0.0
        )

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

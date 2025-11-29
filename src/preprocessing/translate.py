#!/usr/bin/env python3
"""
Gemini Translation Script.

Translates Vietnamese-English code-switched transcripts to pure Vietnamese.
Uses Gemini API with multi-key rotation for rate limit handling.

Strategy:
1. Translate FULL transcript for global context
2. Split translation into segments to match audio chunks
3. Store both full translation and per-segment translations

Pipeline Stage: SEGMENT_VERIFIED → TRANSLATED

Usage:
    python translate.py --sample-id <uuid>
    python translate.py --batch --limit 10

Requirements:
    - google-generativeai package
    - API keys configured in database (api_keys table) or env vars
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
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

# Translation settings
SOURCE_LANGUAGE = "vi-en"  # Vietnamese-English code-switched
TARGET_LANGUAGE = "vi"     # Pure Vietnamese

# Gemini settings
DEFAULT_MODEL = "gemini-1.5-flash"  # Use flash for cost efficiency
BACKUP_MODEL = "gemini-1.5-pro"     # Pro for retries if flash fails

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
RATE_LIMIT_WAIT_SECONDS = 60

# Prompt template for translation
TRANSLATION_PROMPT = """You are a professional translator specializing in Vietnamese-English code-switched content.

Task: Translate the following Vietnamese-English code-switched transcript into pure, natural Vietnamese.

Guidelines:
1. Translate ALL English words/phrases into Vietnamese
2. Maintain the original meaning and tone
3. Use natural Vietnamese expressions, not literal translations
4. Preserve proper nouns (names of people, places, brands) unless they have established Vietnamese forms
5. Keep the same sentence structure where possible
6. Do not add or remove information

Code-switched transcript:
---
{transcript}
---

Provide ONLY the Vietnamese translation, no explanations or notes."""


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

@dataclass
class ApiKey:
    """Represents a Gemini API key with usage tracking."""
    key_id: int
    key_name: str
    api_key: str  # Actual key value
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
            # Also check without number for backward compat
            if idx == 1:
                api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            break

        keys.append(ApiKey(
            key_id=idx,
            key_name=f"env_key_{idx}",
            api_key=api_key,
            requests_remaining=1500,  # Default daily limit
            is_active=True
        ))
        idx += 1

    return keys


def get_available_api_key() -> Optional[ApiKey]:
    """
    Get next available API key with rotation.

    First tries database, falls back to environment variables.

    Returns:
        ApiKey if available, None if all keys exhausted.
    """
    # Try database first
    conn = get_pg_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM get_available_api_key()")
            result = cur.fetchone()

            if result:
                key_id = result["key_id"]
                key_name = result["key_name"]

                # Get actual API key from env var (keys stored by reference, not value)
                # Pattern: GEMINI_API_KEY_{key_name} or GEMINI_API_KEY_{key_id}
                api_key = os.environ.get(f"GEMINI_API_KEY_{key_name}")
                if not api_key:
                    api_key = os.environ.get(f"GEMINI_API_KEY_{key_id}")

                if api_key:
                    return ApiKey(
                        key_id=key_id,
                        key_name=key_name,
                        api_key=api_key,
                        requests_remaining=1500,  # Will be updated after use
                        is_active=True
                    )
    except Exception as e:
        print(f"[WARNING] Could not query API keys from database: {e}")
    finally:
        conn.close()

    # Fallback to environment variables
    env_keys = get_api_keys_from_env()
    return env_keys[0] if env_keys else None


def record_api_usage(
    key_id: int,
    requests: int = 1,
    rate_limited: bool = False
) -> None:
    """
    Record API key usage in database.

    Args:
        key_id: ID of the API key.
        requests: Number of requests made.
        rate_limited: Whether the key hit rate limit.
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT record_api_key_usage(%s, %s, %s)",
                (key_id, requests, rate_limited)
            )
            conn.commit()
    except Exception as e:
        print(f"[WARNING] Could not record API usage: {e}")
    finally:
        conn.close()


# =============================================================================
# TRANSLATION FUNCTIONS
# =============================================================================

def init_gemini_client(api_key: str, model: str = DEFAULT_MODEL) -> Any:
    """
    Initialize Gemini client.

    Args:
        api_key: Gemini API key.
        model: Model name to use.

    Returns:
        Configured GenerativeModel instance.

    Raises:
        ImportError: If google-generativeai is not installed.
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError(
            "google-generativeai is required. Install with: pip install google-generativeai"
        ) from e

    genai.configure(api_key=api_key)

    # Configure generation settings
    generation_config = {
        "temperature": 0.3,  # Low temperature for consistent translations
        "top_p": 0.9,
        "max_output_tokens": 8192,
    }

    return genai.GenerativeModel(
        model_name=model,
        generation_config=generation_config
    )


def translate_text(
    transcript: str,
    api_key: ApiKey,
    model: str = DEFAULT_MODEL
) -> Tuple[str, Dict[str, Any]]:
    """
    Translate code-switched text to pure Vietnamese.

    Args:
        transcript: The code-switched transcript text.
        api_key: API key to use.
        model: Gemini model to use.

    Returns:
        Tuple of (translation_text, metadata).

    Raises:
        Exception: If translation fails after retries.
    """
    client = init_gemini_client(api_key.api_key, model)
    prompt = TRANSLATION_PROMPT.format(transcript=transcript)

    start_time = time.time()
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.generate_content(prompt)

            # Check for blocked content
            if response.prompt_feedback.block_reason:
                raise ValueError(f"Content blocked: {response.prompt_feedback.block_reason}")

            translation = response.text.strip()

            # Record successful usage
            record_api_usage(api_key.key_id, requests=1, rate_limited=False)

            # Calculate basic stats
            input_chars = len(transcript)
            output_chars = len(translation)
            elapsed_time = time.time() - start_time

            metadata = {
                "model": model,
                "input_characters": input_chars,
                "output_characters": output_chars,
                "translation_time_seconds": round(elapsed_time, 2),
                "attempts": attempt + 1,
                "api_key_name": api_key.key_name
            }

            return translation, metadata

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Check for rate limit
            if "rate" in error_str or "quota" in error_str or "429" in error_str:
                print(f"[WARNING] Rate limit hit on attempt {attempt + 1}")
                record_api_usage(api_key.key_id, requests=1, rate_limited=True)

                # Try to get new API key
                new_key = get_available_api_key()
                if new_key and new_key.key_id != api_key.key_id:
                    print(f"[INFO] Switching to API key: {new_key.key_name}")
                    api_key = new_key
                    client = init_gemini_client(api_key.api_key, model)
                else:
                    print(f"[WARNING] No alternative API key available, waiting...")
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)

            elif attempt < MAX_RETRIES - 1:
                print(f"[WARNING] Attempt {attempt + 1} failed: {e}")
                time.sleep(RETRY_DELAY_SECONDS)

    raise Exception(f"Translation failed after {MAX_RETRIES} attempts: {last_error}")


def split_translation_to_segments(
    full_transcript: str,
    full_translation: str,
    segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Split full translation to match segment boundaries.

    Strategy:
    1. Use sentence count ratio to estimate split points
    2. Match sentences to segments based on order
    3. Handle edge cases (punctuation, formatting)

    Args:
        full_transcript: Complete original transcript.
        full_translation: Complete translation.
        segments: List of segment dicts with transcript_text.

    Returns:
        List of dicts with source_text and translation_text for each segment.
    """
    # Split both texts into sentences
    def split_sentences(text: str) -> List[str]:
        """Split text into sentences."""
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s.strip() for s in sentences if s.strip()]

    transcript_sentences = split_sentences(full_transcript)
    translation_sentences = split_sentences(full_translation)

    # If counts don't match, try to adjust
    if len(transcript_sentences) != len(translation_sentences):
        print(f"[WARNING] Sentence count mismatch: {len(transcript_sentences)} vs {len(translation_sentences)}")
        # Use the minimum count for safe mapping
        min_count = min(len(transcript_sentences), len(translation_sentences))
        transcript_sentences = transcript_sentences[:min_count]
        translation_sentences = translation_sentences[:min_count]

    # Build sentence-to-translation map
    sentence_map = dict(zip(transcript_sentences, translation_sentences))

    # Assign translations to segments
    segment_translations = []
    used_translation_idx = 0

    for segment in segments:
        segment_text = segment.get("transcript_text", "")
        segment_sentences = split_sentences(segment_text)

        # Collect translations for this segment
        segment_trans_parts = []

        for sent in segment_sentences:
            # Try exact match first
            if sent in sentence_map:
                segment_trans_parts.append(sentence_map[sent])
            elif used_translation_idx < len(translation_sentences):
                # Fall back to sequential assignment
                segment_trans_parts.append(translation_sentences[used_translation_idx])
                used_translation_idx += 1

        segment_translation = " ".join(segment_trans_parts) if segment_trans_parts else ""

        segment_translations.append({
            "segment_id": segment.get("segment_id"),
            "segment_index": segment.get("segment_index", 0),
            "source_text": segment_text,
            "translation_text": segment_translation
        })

    return segment_translations


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_for_translation(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready for translation (SEGMENT_VERIFIED state).

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries with transcript and segment info.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    tr.revision_id AS transcript_revision_id,
                    tr.transcript_text,
                    (
                        SELECT json_agg(
                            json_build_object(
                                'segment_id', seg.segment_id,
                                'segment_index', seg.segment_index,
                                'transcript_text', seg.transcript_text
                            ) ORDER BY seg.segment_index
                        )
                        FROM segments seg
                        WHERE seg.sample_id = s.sample_id
                          AND seg.is_verified = TRUE
                    ) AS segments
                FROM samples s
                JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                WHERE s.processing_state = 'SEGMENT_VERIFIED'
                  AND s.is_deleted = FALSE
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def save_translation_results(
    sample_id: str,
    transcript_revision_id: str,
    translation_text: str,
    segment_translations: List[Dict[str, Any]],
    translation_metadata: Dict[str, Any],
    executor: str = "translate"
) -> str:
    """
    Save translation results to database.

    Creates translation revision and segment_translations records.

    Args:
        sample_id: UUID of the sample.
        transcript_revision_id: UUID of source transcript revision.
        translation_text: Full translation text.
        segment_translations: Per-segment translation data.
        translation_metadata: Translation metadata.
        executor: Name of executor for logging.

    Returns:
        UUID of the translation revision.

    Raises:
        Exception: If save fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            # Build sentence translations JSON
            sentence_translations = [
                {
                    "source": st["source_text"],
                    "translation": st["translation_text"],
                    "segment_index": st["segment_index"]
                }
                for st in segment_translations
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
                    translation_text,
                    'gemini_draft',
                    transcript_revision_id,
                    Json(sentence_translations),
                    translation_metadata.get("model"),
                    translation_metadata.get("model"),
                    None,  # api_cost_usd - could estimate later
                    executor
                )
            )
            revision_id = cur.fetchone()[0]

            # Insert segment translations
            for st in segment_translations:
                if st.get("segment_id"):
                    cur.execute(
                        """
                        INSERT INTO segment_translations (
                            segment_id,
                            translation_revision_id,
                            source_text,
                            translation_text
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            st["segment_id"],
                            revision_id,
                            st["source_text"],
                            st["translation_text"]
                        )
                    )

            # Transition state
            cur.execute(
                "SELECT transition_sample_state(%s, 'TRANSLATED'::processing_state, %s)",
                (sample_id, executor)
            )

            conn.commit()
            return str(revision_id)

    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to save translation: {e}")
    finally:
        conn.close()


def process_sample(sample: Dict[str, Any]) -> bool:
    """
    Process a single sample for translation.

    Args:
        sample: Sample dictionary from database.

    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    transcript = sample["transcript_text"]
    segments = sample.get("segments") or []

    print(f"\n{'='*60}")
    print(f"Processing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Transcript length: {len(transcript)} chars")
    print(f"Segments: {len(segments)}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        # Get API key
        api_key = get_available_api_key()
        if not api_key:
            raise ValueError("No API keys available for translation")

        print(f"[INFO] Using API key: {api_key.key_name}")

        # Translate full transcript
        print(f"[INFO] Translating transcript...")
        translation, metadata = translate_text(transcript, api_key)

        print(f"[INFO] Translation complete ({metadata['translation_time_seconds']}s)")

        # Split to segments
        print(f"[INFO] Splitting translation to {len(segments)} segments...")
        segment_translations = split_translation_to_segments(
            transcript, translation, segments
        )

        # Save results
        print(f"[INFO] Saving to database...")
        revision_id = save_translation_results(
            sample_id=sample_id,
            transcript_revision_id=str(sample["transcript_revision_id"]),
            translation_text=translation,
            segment_translations=segment_translations,
            translation_metadata=metadata
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log success
        log_processing(
            operation="gemini_translation",
            success=True,
            sample_id=sample_id,
            previous_state="SEGMENT_VERIFIED",
            new_state="TRANSLATED",
            executor="translate",
            execution_time_ms=execution_time_ms,
            input_params={
                "transcript_length": len(transcript),
                "segment_count": len(segments),
                "model": metadata["model"]
            },
            output_summary={
                "revision_id": revision_id,
                "translation_length": len(translation),
                "api_key": api_key.key_name
            }
        )

        print(f"[SUCCESS] Translated {external_id}")
        print(f"  Input: {len(transcript)} chars")
        print(f"  Output: {len(translation)} chars")
        print(f"  Time: {execution_time_ms/1000:.2f}s")

        return True

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Log failure
        log_processing(
            operation="gemini_translation",
            success=False,
            sample_id=sample_id,
            previous_state="SEGMENT_VERIFIED",
            executor="translate",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )

        print(f"[ERROR] Failed to translate {external_id}: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for translation."""
    parser = argparse.ArgumentParser(
        description="Translate code-switched transcripts using Gemini API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Translate a specific sample
    python translate.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Process batch of samples
    python translate.py --batch --limit 10

    # Check API key status
    python translate.py --check-keys

Environment Variables:
    GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... : API keys for rotation
    GEMINI_API_KEY : Fallback single API key
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to translate"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples in SEGMENT_VERIFIED state"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of samples to process in batch mode (default: 10)"
    )
    parser.add_argument(
        "--model",
        choices=["gemini-1.5-flash", "gemini-1.5-pro"],
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="Check API key availability and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making changes"
    )

    args = parser.parse_args()

    # Check API keys
    if args.check_keys:
        print("\n[API Key Status]")
        print("-" * 40)

        # Check environment variables
        env_keys = get_api_keys_from_env()
        print(f"Environment keys: {len(env_keys)}")
        for k in env_keys:
            print(f"  - {k.key_name}: Active")

        # Check database
        print("\nDatabase keys:")
        conn = get_pg_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM v_api_key_status")
                for row in cur.fetchall():
                    print(f"  - {row['key_name']}: {row['status']} "
                          f"({row['requests_remaining']} remaining)")
        except Exception as e:
            print(f"  Could not query database: {e}")
        finally:
            conn.close()

        return

    if not args.sample_id and not args.batch:
        parser.print_help()
        print("\nError: Specify --sample-id or --batch")
        sys.exit(1)

    # Verify we have API keys
    api_key = get_available_api_key()
    if not api_key:
        print("[ERROR] No API keys available. Set GEMINI_API_KEY environment variable.")
        sys.exit(1)

    print(f"Using API key: {api_key.key_name}")

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
        samples = get_samples_for_translation(limit=args.limit)
        print(f"Found {len(samples)} samples ready for translation:")
        for s in samples:
            segment_count = len(s.get("segments") or [])
            print(f"  - {s['external_id']}: {len(s['transcript_text'])} chars, {segment_count} segments")
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
                        tr.revision_id AS transcript_revision_id,
                        tr.transcript_text,
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'segment_id', seg.segment_id,
                                    'segment_index', seg.segment_index,
                                    'transcript_text', seg.transcript_text
                                ) ORDER BY seg.segment_index
                            )
                            FROM segments seg
                            WHERE seg.sample_id = s.sample_id
                        ) AS segments
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
                    process_sample(dict(sample))
                else:
                    print(f"Sample not found: {args.sample_id}")
        finally:
            conn.close()
    else:
        # Batch mode
        samples = get_samples_for_translation(limit=args.limit)
        print(f"\n[INFO] Found {len(samples)} samples to process")

        success_count = 0
        fail_count = 0

        for sample in samples:
            if process_sample(sample):
                success_count += 1
            else:
                fail_count += 1

            # Small delay between samples to avoid rate limits
            if success_count + fail_count < len(samples):
                time.sleep(1)

        print(f"\n{'='*60}")
        print(f"Batch processing complete")
        print(f"  Success: {success_count}")
        print(f"  Failed: {fail_count}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Gemini Translation Repair Script.

Re-translates sentences that had translation issues during the initial
gemini_process.py run. This script queries samples with has_translation_issues=TRUE,
extracts the problematic sentences, and uses Gemini text-only API to fix them.

This is a backup/repair script that runs after gemini_process.py.

Pipeline Stage: Repairs TRANSLATED samples that have translation issues

Usage:
    python gemini_repair_translation.py --batch --limit 10
    python gemini_repair_translation.py --sample-id <uuid>
    python gemini_repair_translation.py --dry-run

Requirements:
    - google-generativeai>=0.3.0 (pip install google-generativeai)
    - GEMINI_API_KEY_1 environment variable (from .env file)
"""

import argparse
import json
import os
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

# Gemini settings
DEFAULT_MODEL = "gemini-2.5-flash"
PRO_MODEL = "gemini-2.5-pro"

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
RATE_LIMIT_WAIT_SECONDS = 60

# Batch settings
MAX_SENTENCES_PER_REQUEST = 20  # Process in batches for efficiency


# =============================================================================
# TRANSLATION REPAIR PROMPT
# =============================================================================

REPAIR_PROMPT_TEMPLATE = """You are an expert translator specializing in Vietnamese-English code-switched content.

## Task
Translate the following Vietnamese-English code-switched sentences into pure, natural Vietnamese.

## Guidelines
1. Translate ALL English words/phrases into natural Vietnamese
2. Maintain original meaning, tone, and intent
3. Use natural Vietnamese expressions, not literal word-for-word translations
4. Preserve proper nouns (names of people, places, brands) unless they have established Vietnamese forms
5. Each sentence should be translated independently but maintain consistency

## Input Sentences (JSON array)
```json
{sentences_json}
```

## Output Format
Output a JSON array with translations in the same order as input:
```json
[
  {{"index": 0, "translation": "Vietnamese translation for first sentence"}},
  {{"index": 1, "translation": "Vietnamese translation for second sentence"}},
  ...
]
```

Translate now:"""


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
    """Get next available API key."""
    env_keys = get_api_keys_from_env()
    return env_keys[0] if env_keys else None


# =============================================================================
# TRANSLATION REPAIR FUNCTIONS
# =============================================================================

def repair_translations(
    sentences_to_repair: List[Dict[str, Any]],
    api_key: ApiKey,
    model: str = DEFAULT_MODEL
) -> List[Dict[str, Any]]:
    """
    Repair translations for a batch of sentences using Gemini text-only API.
    
    Args:
        sentences_to_repair: List of sentence dicts with 'text' and 'index' keys.
        api_key: API key to use.
        model: Gemini model to use.
        
    Returns:
        List of dicts with 'index' and 'translation' keys.
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError(
            "google-generativeai is required. "
            "Install with: pip install google-generativeai"
        ) from e
    
    if not sentences_to_repair:
        return []
    
    # Initialize client
    genai.configure(api_key=api_key.api_key)
    
    generation_config = {
        "temperature": 0.2,  # Slightly higher for creative translation
        "top_p": 0.95,
        "max_output_tokens": 8192,
        "response_mime_type": "application/json"
    }
    
    client = genai.GenerativeModel(
        model_name=model,
        generation_config=generation_config
    )
    
    # Prepare input JSON
    input_sentences = [
        {"index": s["index"], "text": s["text"]}
        for s in sentences_to_repair
    ]
    
    prompt = REPAIR_PROMPT_TEMPLATE.format(
        sentences_json=json.dumps(input_sentences, ensure_ascii=False, indent=2)
    )
    
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.generate_content(prompt)
            
            # Check for blocked content
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                if hasattr(response.prompt_feedback, 'block_reason') and response.prompt_feedback.block_reason:
                    raise ValueError(
                        f"Content blocked: {response.prompt_feedback.block_reason}"
                    )
            
            # Parse JSON response
            response_text = response.text.strip()
            
            # Handle markdown code blocks
            if response_text.startswith("```"):
                import re
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
                if json_match:
                    response_text = json_match.group(1)
            
            translations = json.loads(response_text)
            
            # Validate response
            if not isinstance(translations, list):
                raise ValueError("Response is not a list")
            
            return translations
            
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
    
    raise Exception(f"Translation repair failed after {MAX_RETRIES} attempts: {last_error}")


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_samples_with_translation_issues(
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get samples that have translation issues needing repair.
    
    Args:
        limit: Maximum number of samples to return.
        
    Returns:
        List of sample dictionaries with transcript revision data.
    """
    conn = get_pg_connection()
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.processing_state,
                    s.needs_translation_review,
                    tr.revision_id AS transcript_revision_id,
                    tr.version AS transcript_version,
                    tr.sentence_timestamps,
                    tr.has_translation_issues,
                    tr.translation_issue_indices,
                    tlr.revision_id AS translation_revision_id,
                    tlr.version AS translation_version,
                    tlr.sentence_translations
                FROM samples s
                JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                LEFT JOIN translation_revisions tlr
                    ON s.sample_id = tlr.sample_id
                    AND tlr.version = s.current_translation_version
                WHERE tr.has_translation_issues = TRUE
                  AND s.is_deleted = FALSE
                ORDER BY s.priority DESC, s.updated_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_repaired_translations(
    sample_id: str,
    transcript_revision_id: str,
    translation_revision_id: str,
    updated_sentence_timestamps: List[Dict[str, Any]],
    updated_sentence_translations: List[Dict[str, Any]],
    executor: str = "gemini_repair"
) -> bool:
    """
    Update database with repaired translations.
    
    Args:
        sample_id: UUID of the sample.
        transcript_revision_id: UUID of the transcript revision.
        translation_revision_id: UUID of the translation revision.
        updated_sentence_timestamps: Updated sentence_timestamps JSONB.
        updated_sentence_translations: Updated sentence_translations JSONB.
        executor: Name of executor for logging.
        
    Returns:
        True if successful.
    """
    conn = get_pg_connection()
    
    try:
        with conn.cursor() as cur:
            # Update transcript revision - clear issue flags
            cur.execute(
                """
                UPDATE transcript_revisions
                SET sentence_timestamps = %s,
                    has_translation_issues = FALSE,
                    translation_issue_indices = NULL
                WHERE revision_id = %s
                """,
                (Json(updated_sentence_timestamps), transcript_revision_id)
            )
            
            # Update translation revision
            if translation_revision_id:
                # Build full translation text
                full_translation = " ".join([
                    s.get('translation', '') 
                    for s in updated_sentence_translations
                ])
                
                cur.execute(
                    """
                    UPDATE translation_revisions
                    SET translation_text = %s,
                        sentence_translations = %s
                    WHERE revision_id = %s
                    """,
                    (full_translation, Json(updated_sentence_translations), translation_revision_id)
                )
            
            # Clear needs_translation_review flag on sample
            cur.execute(
                """
                UPDATE samples
                SET needs_translation_review = FALSE,
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (sample_id,)
            )
            
            conn.commit()
            return True
            
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to update repaired translations: {e}")
    finally:
        conn.close()


def process_sample_repair(
    sample: Dict[str, Any],
    api_key: ApiKey,
    model: str = DEFAULT_MODEL
) -> bool:
    """
    Process translation repair for a single sample.
    
    Args:
        sample: Sample dictionary with revision data.
        api_key: API key to use.
        model: Gemini model to use.
        
    Returns:
        True if successful, False otherwise.
    """
    sample_id = str(sample["sample_id"])
    external_id = sample["external_id"]
    transcript_revision_id = str(sample["transcript_revision_id"])
    translation_revision_id = str(sample["translation_revision_id"]) if sample.get("translation_revision_id") else None
    
    sentence_timestamps = sample.get("sentence_timestamps") or []
    sentence_translations = sample.get("sentence_translations") or []
    issue_indices = sample.get("translation_issue_indices") or []
    
    print(f"\n{'='*60}")
    print(f"Repairing: {external_id}")
    print(f"Sample ID: {sample_id}")
    print(f"Issue count: {len(issue_indices)} sentences")
    print(f"{'='*60}")
    
    if not issue_indices:
        print(f"[INFO] No issues to repair for {external_id}")
        return True
    
    start_time = time.time()
    
    try:
        # Extract sentences needing repair
        sentences_to_repair = []
        for idx in issue_indices:
            if idx < len(sentence_timestamps):
                sentence = sentence_timestamps[idx]
                sentences_to_repair.append({
                    "index": idx,
                    "text": sentence.get("text", "")
                })
        
        if not sentences_to_repair:
            print(f"[WARNING] No valid sentences found at issue indices")
            return False
        
        print(f"[INFO] Repairing {len(sentences_to_repair)} sentences...")
        
        # Process in batches if needed
        all_repaired = []
        for batch_start in range(0, len(sentences_to_repair), MAX_SENTENCES_PER_REQUEST):
            batch = sentences_to_repair[batch_start:batch_start + MAX_SENTENCES_PER_REQUEST]
            
            print(f"  Processing batch {batch_start//MAX_SENTENCES_PER_REQUEST + 1}...")
            repaired_batch = repair_translations(batch, api_key, model)
            all_repaired.extend(repaired_batch)
            
            if batch_start + MAX_SENTENCES_PER_REQUEST < len(sentences_to_repair):
                time.sleep(2)  # Delay between batches
        
        # Update sentence_timestamps with repaired translations
        updated_sentence_timestamps = list(sentence_timestamps)
        updated_sentence_translations = list(sentence_translations)
        
        repaired_map = {r["index"]: r["translation"] for r in all_repaired}
        
        for idx, translation in repaired_map.items():
            if idx < len(updated_sentence_timestamps):
                updated_sentence_timestamps[idx]["translation"] = translation
            
            # Also update sentence_translations if it exists
            for st in updated_sentence_translations:
                if st.get("sentence_index") == idx:
                    st["translation"] = translation
                    break
        
        # Save to database
        print(f"[INFO] Saving repaired translations...")
        update_repaired_translations(
            sample_id=sample_id,
            transcript_revision_id=transcript_revision_id,
            translation_revision_id=translation_revision_id,
            updated_sentence_timestamps=updated_sentence_timestamps,
            updated_sentence_translations=updated_sentence_translations
        )
        
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # Log success
        log_processing(
            operation="gemini_repair_translation",
            success=True,
            sample_id=sample_id,
            executor="gemini_repair",
            execution_time_ms=execution_time_ms,
            input_params={
                "issue_count": len(issue_indices),
                "model": model
            },
            output_summary={
                "repaired_count": len(all_repaired)
            }
        )
        
        print(f"\n[SUCCESS] Repaired {external_id}")
        print(f"  Repaired: {len(all_repaired)} sentences")
        print(f"  Time: {execution_time_ms/1000:.2f}s")
        
        return True
        
    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        log_processing(
            operation="gemini_repair_translation",
            success=False,
            sample_id=sample_id,
            executor="gemini_repair",
            execution_time_ms=execution_time_ms,
            error_message=str(e)
        )
        
        print(f"[ERROR] Failed to repair {external_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main entry point for translation repair."""
    parser = argparse.ArgumentParser(
        description="Repair translation issues from gemini_process.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Repair batch of samples with translation issues
    python gemini_repair_translation.py --batch --limit 10

    # Repair a specific sample
    python gemini_repair_translation.py --sample-id 123e4567-e89b-12d3-a456-426614174000

    # Dry run to see what would be repaired
    python gemini_repair_translation.py --dry-run

Environment Variables (from .env file):
    GEMINI_API_KEY_1 : Primary Gemini API key
        """
    )
    parser.add_argument(
        "--sample-id",
        help="UUID of specific sample to repair"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process batch of samples with translation issues"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum samples to process in batch mode (default: 10)"
    )
    parser.add_argument(
        "--model",
        choices=["gemini-2.5-flash", "gemini-2.5-pro"],
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be repaired without making changes"
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
    
    if not args.sample_id and not args.batch and not args.dry_run:
        parser.print_help()
        print("\nError: Specify --sample-id, --batch, or --dry-run")
        sys.exit(1)
    
    # Verify API key
    api_key = get_available_api_key()
    if not api_key and not args.dry_run:
        print("[ERROR] No API keys available.")
        print("Set GEMINI_API_KEY_1 in your .env file or environment.")
        sys.exit(1)
    
    if api_key:
        print(f"Using API key: {api_key.key_name}")
    print(f"Using model: {args.model}")
    
    # Get samples with issues
    samples = get_samples_with_translation_issues(limit=args.limit)
    
    if args.dry_run or (not args.sample_id and not samples):
        print(f"\n[INFO] Found {len(samples)} samples with translation issues:")
        for s in samples:
            issue_count = len(s.get("translation_issue_indices") or [])
            print(f"  - {s['external_id']}: {issue_count} issues")
        
        if args.dry_run:
            print("\n[DRY RUN MODE - No changes made]")
        return
    
    # Process specific sample
    if args.sample_id:
        # Find the sample in the list or query directly
        sample = next((s for s in samples if str(s["sample_id"]) == args.sample_id), None)
        
        if not sample:
            # Query directly
            conn = get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT 
                            s.sample_id,
                            s.external_id,
                            s.processing_state,
                            tr.revision_id AS transcript_revision_id,
                            tr.sentence_timestamps,
                            tr.has_translation_issues,
                            tr.translation_issue_indices,
                            tlr.revision_id AS translation_revision_id,
                            tlr.sentence_translations
                        FROM samples s
                        JOIN transcript_revisions tr 
                            ON s.sample_id = tr.sample_id 
                            AND tr.version = s.current_transcript_version
                        LEFT JOIN translation_revisions tlr
                            ON s.sample_id = tlr.sample_id
                            AND tlr.version = s.current_translation_version
                        WHERE s.sample_id = %s
                        """,
                        (args.sample_id,)
                    )
                    sample = cur.fetchone()
                    if sample:
                        sample = dict(sample)
            finally:
                conn.close()
        
        if not sample:
            print(f"Sample not found: {args.sample_id}")
            sys.exit(1)
        
        if not sample.get("has_translation_issues"):
            print(f"Sample {args.sample_id} has no translation issues to repair")
            return
        
        process_sample_repair(sample, api_key, model=args.model)
    
    else:
        # Batch mode
        print(f"\n[INFO] Processing {len(samples)} samples with translation issues")
        
        success_count = 0
        fail_count = 0
        
        for sample in samples:
            if process_sample_repair(sample, api_key, model=args.model):
                success_count += 1
            else:
                fail_count += 1
            
            if success_count + fail_count < len(samples):
                time.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"Repair batch complete")
        print(f"  Success: {success_count}")
        print(f"  Failed: {fail_count}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

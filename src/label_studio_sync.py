"""
Label Studio synchronization module for the NLP pipeline (v2).

Handles pushing review chunks for unified annotation and pulling completed
annotations back into the database. Supports the new chunked review workflow.

Changes from v1:
- Supports unified_review task type with review_chunks
- Push/pull works at chunk level, not sample level
- Handles sentence-level corrections
- Supports reopen for partial re-review

Usage:
    python label_studio_sync.py push --task-type unified_review --limit 10
    python label_studio_sync.py pull --task-type unified_review
    python label_studio_sync.py reopen --chunk-id <uuid>
    python label_studio_sync.py reopen --sample-id <uuid> --all
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import Json, RealDictCursor

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.data_utils import (
    get_pg_connection,
    log_processing,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Label Studio configuration from environment
LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8085")
LABEL_STUDIO_API_KEY = os.getenv("LABEL_STUDIO_API_KEY", "")

# Audio server URL for serving audio files to Label Studio
AUDIO_SERVER_URL = os.getenv("AUDIO_SERVER_URL", "http://localhost:8081")
AUDIO_PUBLIC_URL = os.getenv("AUDIO_PUBLIC_URL", "http://localhost:8081")

# Task type to Label Studio project mapping
PROJECT_MAPPING = {
    'transcript_correction': os.getenv("LS_PROJECT_TRANSCRIPT", "1"),
    'translation_review': os.getenv("LS_PROJECT_TRANSLATION", "2"),
    'audio_segmentation': os.getenv("LS_PROJECT_SEGMENTATION", "3"),
    'unified_review': os.getenv("LS_PROJECT_UNIFIED_REVIEW", "4"),
}


# =============================================================================
# LABEL STUDIO CLIENT
# =============================================================================

class LabelStudioClient:
    """
    Client for interacting with Label Studio API.

    Handles authentication, task creation, and annotation retrieval.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize Label Studio client.

        Args:
            url: Label Studio instance URL.
            api_key: API key for authentication.
        """
        self.url = (url or LABEL_STUDIO_URL).rstrip('/')
        self.api_key = api_key or LABEL_STUDIO_API_KEY

        if not self.api_key:
            print("Warning: No Label Studio API key provided.")

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {self.api_key}',
            'Content-Type': 'application/json',
        })

    def check_connection(self) -> bool:
        """Check if Label Studio is accessible."""
        try:
            resp = self.session.get(f"{self.url}/api/projects/")
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"Connection error: {e}")
            return False

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get project details."""
        try:
            resp = self.session.get(f"{self.url}/api/projects/{project_id}/")
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException as e:
            print(f"Error fetching project: {e}")
        return None

    def create_task(
        self,
        project_id: str,
        data: Dict[str, Any],
        predictions: Optional[List[Dict]] = None
    ) -> Optional[int]:
        """
        Create a new annotation task in Label Studio.

        Args:
            project_id: Target project ID.
            data: Task data (content to annotate).
            predictions: Optional pre-annotations.

        Returns:
            Task ID if successful, None otherwise.
        """
        payload = {'data': data}
        if predictions:
            payload['predictions'] = predictions

        try:
            resp = self.session.post(
                f"{self.url}/api/projects/{project_id}/tasks/",
                json=payload
            )
            if resp.status_code == 201:
                return resp.json().get('id')
            else:
                print(f"Error creating task: {resp.status_code} - {resp.text}")
        except requests.RequestException as e:
            print(f"Request error: {e}")

        return None

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get task details including annotations."""
        try:
            resp = self.session.get(f"{self.url}/api/tasks/{task_id}/")
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException as e:
            print(f"Error fetching task: {e}")
        return None

    def get_completed_tasks(
        self,
        project_id: str,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get all completed tasks from a project."""
        tasks = []

        try:
            params = {'project': project_id}
            resp = self.session.get(
                f"{self.url}/api/tasks/",
                params=params
            )

            if resp.status_code == 200:
                response_data = resp.json()
                if isinstance(response_data, dict):
                    all_tasks = response_data.get('tasks', [])
                else:
                    all_tasks = response_data

                for task in all_tasks:
                    if task.get('is_labeled') or task.get('total_annotations', 0) > 0:
                        task_detail = self.get_task(task['id'])
                        if task_detail and task_detail.get('annotations'):
                            tasks.append(task_detail)

        except requests.RequestException as e:
            print(f"Error fetching tasks: {e}")

        return tasks

    def delete_task(self, task_id: int) -> bool:
        """Delete a task from Label Studio."""
        try:
            resp = self.session.delete(f"{self.url}/api/tasks/{task_id}/")
            return resp.status_code == 204
        except requests.RequestException as e:
            print(f"Error deleting task: {e}")
        return False


# =============================================================================
# DATABASE FUNCTIONS - UNIFIED REVIEW
# =============================================================================

def get_chunks_for_review(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get review chunks ready to be pushed to Label Studio.

    Returns chunks in REVIEW_PREPARED samples that have pending status.

    Args:
        limit: Maximum number of chunks to return.

    Returns:
        List of chunk dictionaries with sample and sentence data.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    rc.chunk_id,
                    rc.sample_id,
                    rc.chunk_index,
                    rc.start_sentence_idx,
                    rc.end_sentence_idx,
                    rc.start_time_ms,
                    rc.end_time_ms,
                    s.external_id,
                    s.source_metadata->>'title' AS video_title,
                    (SELECT COUNT(*) FROM review_chunks WHERE sample_id = rc.sample_id) AS chunk_count
                FROM review_chunks rc
                JOIN samples s ON rc.sample_id = s.sample_id
                WHERE rc.status = 'pending'
                  AND s.processing_state = 'REVIEW_PREPARED'
                  AND s.is_deleted = FALSE
                ORDER BY s.priority DESC, s.created_at ASC, rc.chunk_index ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_sentences_for_chunk(
    chunk_id: str,
    sample_id: str
) -> List[Dict[str, Any]]:
    """
    Get sentence reviews for a chunk to build Label Studio task data.

    Args:
        chunk_id: UUID of the chunk.
        sample_id: UUID of the sample.

    Returns:
        List of sentence dictionaries.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    sr.sentence_idx,
                    sr.original_start_ms,
                    sr.original_end_ms,
                    sr.original_transcript,
                    sr.original_translation
                FROM sentence_reviews sr
                WHERE sr.chunk_id = %s
                ORDER BY sr.sentence_idx ASC
                """,
                (chunk_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_chunk_status(
    chunk_id: str,
    status: str,
    label_studio_project_id: Optional[int] = None,
    label_studio_task_id: Optional[int] = None
) -> None:
    """
    Update review chunk status and Label Studio task info.

    Args:
        chunk_id: UUID of the chunk.
        status: New status (pending, in_progress, completed).
        label_studio_project_id: Label Studio project ID.
        label_studio_task_id: Label Studio task ID.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_chunks
                SET status = %s::annotation_status,
                    label_studio_project_id = COALESCE(%s, label_studio_project_id),
                    label_studio_task_id = COALESCE(%s, label_studio_task_id),
                    updated_at = NOW()
                WHERE chunk_id = %s
                """,
                (status, label_studio_project_id, label_studio_task_id, chunk_id)
            )
            conn.commit()
    finally:
        conn.close()


def save_sentence_reviews(
    chunk_id: str,
    sample_id: str,
    results: List[Dict[str, Any]],
    reviewer: str
) -> Tuple[int, int]:
    """
    Save sentence-level review results to database.

    Args:
        chunk_id: UUID of the chunk.
        sample_id: UUID of the sample.
        results: Label Studio annotation results.
        reviewer: Reviewer identifier.

    Returns:
        Tuple of (updated_count, rejected_count).
    """
    conn = get_pg_connection()
    updated_count = 0
    rejected_count = 0

    try:
        with conn.cursor() as cur:
            # Parse results and update each sentence
            for item in results:
                item_name = item.get('from_name', '')
                
                # Extract sentence index from field name (e.g., "transcript_42")
                if '_' in item_name:
                    parts = item_name.rsplit('_', 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        sentence_idx = int(parts[1])
                        field_type = parts[0]
                    else:
                        continue
                else:
                    continue

                value = item.get('value', {})

                # Handle different field types
                if field_type == 'transcript' and item.get('type') == 'textarea':
                    text = value.get('text', [''])[0] if isinstance(value.get('text'), list) else value.get('text', '')
                    if text:
                        cur.execute(
                            """
                            UPDATE sentence_reviews
                            SET reviewed_transcript = %s,
                                is_transcript_corrected = TRUE,
                                updated_at = NOW()
                            WHERE chunk_id = %s AND sentence_idx = %s
                            """,
                            (text, chunk_id, sentence_idx)
                        )
                        updated_count += 1

                elif field_type == 'translation' and item.get('type') == 'textarea':
                    text = value.get('text', [''])[0] if isinstance(value.get('text'), list) else value.get('text', '')
                    if text:
                        cur.execute(
                            """
                            UPDATE sentence_reviews
                            SET reviewed_translation = %s,
                                is_translation_corrected = TRUE,
                                updated_at = NOW()
                            WHERE chunk_id = %s AND sentence_idx = %s
                            """,
                            (text, chunk_id, sentence_idx)
                        )
                        updated_count += 1

                elif field_type == 'flags' and item.get('type') == 'choices':
                    choices = value.get('choices', [])
                    
                    is_rejected = 'reject' in choices
                    is_boundary_adj = 'boundary_adjust' in choices
                    is_transcript_issue = 'transcript_issue' in choices
                    is_translation_issue = 'translation_issue' in choices

                    cur.execute(
                        """
                        UPDATE sentence_reviews
                        SET is_rejected = %s,
                            is_boundary_adjusted = %s,
                            is_transcript_corrected = COALESCE(is_transcript_corrected, %s),
                            is_translation_corrected = COALESCE(is_translation_corrected, %s),
                            updated_at = NOW()
                        WHERE chunk_id = %s AND sentence_idx = %s
                        """,
                        (is_rejected, is_boundary_adj, is_transcript_issue, 
                         is_translation_issue, chunk_id, sentence_idx)
                    )
                    
                    if is_rejected:
                        rejected_count += 1

            # Update chunk status
            cur.execute(
                """
                UPDATE review_chunks
                SET status = 'completed'::annotation_status,
                    reviewed_by = %s,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE chunk_id = %s
                """,
                (reviewer, chunk_id)
            )

            conn.commit()
            return updated_count, rejected_count

    except psycopg2.Error as e:
        conn.rollback()
        print(f"Error saving sentence reviews: {e}")
        return 0, 0
    finally:
        conn.close()


def check_sample_review_complete(sample_id: str) -> bool:
    """
    Check if all chunks for a sample have been reviewed.

    Args:
        sample_id: UUID of the sample.

    Returns:
        True if all chunks are completed.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) = 0 AS all_complete
                FROM review_chunks
                WHERE sample_id = %s
                  AND status != 'completed'
                """,
                (sample_id,)
            )
            result = cur.fetchone()
            return result[0] if result else False
    finally:
        conn.close()


def transition_sample_to_verified(sample_id: str, executor: str = "label_studio_sync") -> None:
    """
    Transition a sample to VERIFIED state when all chunks are reviewed.

    Args:
        sample_id: UUID of the sample.
        executor: Name of the executor for logging.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT transition_sample_state(%s, 'VERIFIED'::processing_state, %s)",
                (sample_id, executor)
            )
            conn.commit()
    finally:
        conn.close()


# =============================================================================
# PUSH/PULL FUNCTIONS - UNIFIED REVIEW
# =============================================================================

def push_unified_review(
    limit: int = 10,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Push review chunks to Label Studio as unified review tasks.

    Args:
        limit: Maximum number of chunks to push.
        dry_run: If True, don't actually create tasks.

    Returns:
        Statistics dictionary.
    """
    stats = {'pushed': 0, 'skipped': 0, 'errors': 0}

    project_id = PROJECT_MAPPING.get('unified_review')
    if not project_id:
        print("Error: unified_review project not configured")
        return stats

    client = LabelStudioClient()

    if not dry_run and not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    chunks = get_chunks_for_review(limit=limit)
    print(f"Found {len(chunks)} chunks ready for unified review")

    for chunk in chunks:
        chunk_id = str(chunk['chunk_id'])
        sample_id = str(chunk['sample_id'])
        external_id = chunk['external_id']
        video_title = chunk.get('video_title', external_id)
        chunk_index = chunk['chunk_index']
        chunk_count = chunk['chunk_count']

        # Get sentences for this chunk
        sentences = get_sentences_for_chunk(chunk_id, sample_id)

        if not sentences:
            print(f"  Skipping chunk {chunk_id}: No sentences found")
            stats['skipped'] += 1
            continue

        # Build sentence data for Label Studio
        sentence_data = []
        for sent in sentences:
            sentence_idx = sent['sentence_idx']
            
            # Build audio URL: /review/{sample_id}/sentences/{idx:04d}.wav
            audio_url = f"{AUDIO_PUBLIC_URL}/review/{sample_id}/sentences/{sentence_idx:04d}.wav"

            sentence_data.append({
                'idx': sentence_idx,
                'audio_url': audio_url,
                'start': sent['original_start_ms'] / 1000.0,  # Convert to seconds
                'end': sent['original_end_ms'] / 1000.0,
                'text': sent['original_transcript'],
                'translation': sent['original_translation'],
            })

        # Build task data
        task_data = {
            'sample_id': sample_id,
            'chunk_id': chunk_id,
            'external_id': external_id,
            'video_title': video_title,
            'chunk_index': str(chunk_index + 1),  # 1-indexed for display
            'chunk_count': str(chunk_count),
            'sentences': sentence_data,
        }

        if dry_run:
            print(f"  [DRY RUN] Would push chunk {chunk_index + 1}/{chunk_count} "
                  f"for {external_id} ({len(sentences)} sentences)")
            stats['pushed'] += 1
            continue

        # Create task in Label Studio
        task_id = client.create_task(project_id, task_data)

        if task_id:
            # Update chunk with Label Studio info
            update_chunk_status(
                chunk_id=chunk_id,
                status='in_progress',
                label_studio_project_id=int(project_id),
                label_studio_task_id=task_id
            )

            print(f"  Pushed chunk {chunk_index + 1}/{chunk_count} for {external_id} -> Task {task_id}")
            stats['pushed'] += 1
        else:
            stats['errors'] += 1

    return stats


def pull_unified_review(dry_run: bool = False) -> Dict[str, int]:
    """
    Pull completed unified review annotations from Label Studio.

    Args:
        dry_run: If True, don't update database.

    Returns:
        Statistics dictionary.
    """
    stats = {'pulled': 0, 'skipped': 0, 'errors': 0, 'samples_completed': 0}

    project_id = PROJECT_MAPPING.get('unified_review')
    if not project_id:
        print("Error: unified_review project not configured")
        return stats

    client = LabelStudioClient()

    if not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    completed_tasks = client.get_completed_tasks(project_id)
    print(f"Found {len(completed_tasks)} completed unified review tasks")

    samples_to_check = set()

    for task in completed_tasks:
        task_id = task.get('id')
        task_data = task.get('data', {})
        chunk_id = task_data.get('chunk_id')
        sample_id = task_data.get('sample_id')

        if not chunk_id or not sample_id:
            print(f"  Skipping task {task_id}: Missing chunk_id or sample_id")
            stats['skipped'] += 1
            continue

        annotations = task.get('annotations', [])
        if not annotations:
            continue

        latest_annotation = annotations[-1]
        results = latest_annotation.get('result', [])
        reviewer = str(latest_annotation.get('completed_by', 'annotator'))

        if dry_run:
            print(f"  [DRY RUN] Would pull task {task_id} -> chunk {chunk_id}")
            stats['pulled'] += 1
            samples_to_check.add(sample_id)
            continue

        # Save sentence reviews
        updated_count, rejected_count = save_sentence_reviews(
            chunk_id=chunk_id,
            sample_id=sample_id,
            results=results,
            reviewer=reviewer
        )

        # Log the operation
        log_processing(
            operation='unified_review_completed',
            success=True,
            sample_id=sample_id,
            executor='label_studio_sync',
            output_summary={
                'chunk_id': chunk_id,
                'task_id': task_id,
                'sentences_updated': updated_count,
                'sentences_rejected': rejected_count,
                'reviewer': reviewer,
            },
        )

        print(f"  Pulled task {task_id} -> chunk {chunk_id} "
              f"({updated_count} updated, {rejected_count} rejected)")
        stats['pulled'] += 1
        samples_to_check.add(sample_id)

    # Check if any samples are now fully reviewed
    for sample_id in samples_to_check:
        if check_sample_review_complete(sample_id):
            if not dry_run:
                transition_sample_to_verified(sample_id)
                print(f"  Sample {sample_id} -> VERIFIED (all chunks complete)")
            else:
                print(f"  [DRY RUN] Sample {sample_id} would transition to VERIFIED")
            stats['samples_completed'] += 1

    return stats


def reopen_chunk(chunk_id: str) -> bool:
    """
    Reopen a single chunk for re-review.

    Args:
        chunk_id: UUID of the chunk to reopen.

    Returns:
        True if successful.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get chunk info
            cur.execute(
                """
                SELECT rc.chunk_id, rc.sample_id, rc.label_studio_task_id, s.processing_state
                FROM review_chunks rc
                JOIN samples s ON rc.sample_id = s.sample_id
                WHERE rc.chunk_id = %s
                """,
                (chunk_id,)
            )
            chunk = cur.fetchone()

            if not chunk:
                print(f"Chunk not found: {chunk_id}")
                return False

            sample_id = chunk['sample_id']
            task_id = chunk['label_studio_task_id']

            # Delete task from Label Studio if exists
            if task_id:
                client = LabelStudioClient()
                client.delete_task(task_id)

            # Reset chunk status
            cur.execute(
                """
                UPDATE review_chunks
                SET status = 'pending'::annotation_status,
                    label_studio_task_id = NULL,
                    reviewed_by = NULL,
                    reviewed_at = NULL,
                    updated_at = NOW()
                WHERE chunk_id = %s
                """,
                (chunk_id,)
            )

            # Reset sentence reviews for this chunk
            cur.execute(
                """
                UPDATE sentence_reviews
                SET reviewed_transcript = NULL,
                    reviewed_translation = NULL,
                    reviewed_start_ms = NULL,
                    reviewed_end_ms = NULL,
                    is_boundary_adjusted = FALSE,
                    is_transcript_corrected = FALSE,
                    is_translation_corrected = FALSE,
                    is_rejected = FALSE,
                    rejection_reason = NULL,
                    reviewer_notes = NULL,
                    updated_at = NOW()
                WHERE chunk_id = %s
                """,
                (chunk_id,)
            )

            # If sample was VERIFIED, transition back to REVIEW_PREPARED
            if chunk['processing_state'] == 'VERIFIED':
                cur.execute(
                    "SELECT transition_sample_state(%s, 'REVIEW_PREPARED'::processing_state, %s)",
                    (sample_id, 'label_studio_reopen')
                )

            conn.commit()
            print(f"Reopened chunk {chunk_id}")
            return True

    except psycopg2.Error as e:
        conn.rollback()
        print(f"Error reopening chunk: {e}")
        return False
    finally:
        conn.close()


def reopen_sample(sample_id: str) -> int:
    """
    Reopen all chunks for a sample for full re-review.

    Args:
        sample_id: UUID of the sample to reopen.

    Returns:
        Number of chunks reopened.
    """
    conn = get_pg_connection()
    count = 0

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all chunks for the sample
            cur.execute(
                "SELECT chunk_id FROM review_chunks WHERE sample_id = %s",
                (sample_id,)
            )
            chunks = cur.fetchall()

            for chunk in chunks:
                if reopen_chunk(str(chunk['chunk_id'])):
                    count += 1

            return count

    finally:
        conn.close()


# =============================================================================
# LEGACY PUSH/PULL FUNCTIONS (kept for backward compatibility)
# =============================================================================

def push_to_label_studio(
    task_type: str = 'transcript_correction',
    limit: Optional[int] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Push samples from review queue to Label Studio.

    Note: For unified_review, use push_unified_review instead.
    This function is kept for backward compatibility with old task types.
    """
    if task_type == 'unified_review':
        return push_unified_review(limit=limit or 10, dry_run=dry_run)

    # Legacy implementation for old task types
    stats = {'pushed': 0, 'skipped': 0, 'errors': 0}
    print(f"Warning: Task type '{task_type}' uses legacy implementation")
    print("Consider migrating to unified_review workflow")
    return stats


def pull_from_label_studio(
    task_type: str = 'transcript_correction',
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Pull completed annotations from Label Studio and update database.

    Note: For unified_review, use pull_unified_review instead.
    This function is kept for backward compatibility with old task types.
    """
    if task_type == 'unified_review':
        return pull_unified_review(dry_run=dry_run)

    # Legacy implementation for old task types
    stats = {'pulled': 0, 'skipped': 0, 'errors': 0}
    print(f"Warning: Task type '{task_type}' uses legacy implementation")
    print("Consider migrating to unified_review workflow")
    return stats


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Synchronize annotations with Label Studio.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Push chunks for unified review
    python label_studio_sync.py push --task-type unified_review --limit 10

    # Pull completed reviews
    python label_studio_sync.py pull --task-type unified_review

    # Check status
    python label_studio_sync.py status

    # Reopen a single chunk for re-review
    python label_studio_sync.py reopen --chunk-id <uuid>

    # Reopen all chunks for a sample
    python label_studio_sync.py reopen --sample-id <uuid> --all
        """
    )
    
    subparsers = parser.add_subparsers(dest='action', help='Action to perform')

    # Push subcommand
    push_parser = subparsers.add_parser('push', help='Push items to Label Studio')
    push_parser.add_argument(
        '--task-type',
        choices=['transcript_correction', 'translation_review', 
                 'audio_segmentation', 'unified_review'],
        default='unified_review',
        help='Type of annotation task (default: unified_review)'
    )
    push_parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Maximum number of items to process (default: 10)'
    )
    push_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )

    # Pull subcommand
    pull_parser = subparsers.add_parser('pull', help='Pull completed annotations')
    pull_parser.add_argument(
        '--task-type',
        choices=['transcript_correction', 'translation_review',
                 'audio_segmentation', 'unified_review'],
        default='unified_review',
        help='Type of annotation task (default: unified_review)'
    )
    pull_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )

    # Status subcommand
    status_parser = subparsers.add_parser('status', help='Check Label Studio status')

    # Reopen subcommand
    reopen_parser = subparsers.add_parser('reopen', help='Reopen chunks for re-review')
    reopen_parser.add_argument(
        '--chunk-id',
        help='UUID of specific chunk to reopen'
    )
    reopen_parser.add_argument(
        '--sample-id',
        help='UUID of sample to reopen (use with --all for all chunks)'
    )
    reopen_parser.add_argument(
        '--all',
        action='store_true',
        help='Reopen all chunks for the sample'
    )

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        return

    print("=" * 60)
    print("Label Studio Sync v2 (Unified Review)")
    print("=" * 60)
    print(f"Label Studio URL: {LABEL_STUDIO_URL}")
    print(f"Action: {args.action}")
    print()

    if args.action == 'push':
        print(f"Task Type: {args.task_type}")
        stats = push_to_label_studio(
            task_type=args.task_type,
            limit=args.limit,
            dry_run=args.dry_run
        )
        print(f"\nPushed: {stats['pushed']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")

    elif args.action == 'pull':
        print(f"Task Type: {args.task_type}")
        stats = pull_from_label_studio(
            task_type=args.task_type,
            dry_run=args.dry_run
        )
        print(f"\nPulled: {stats['pulled']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
        if 'samples_completed' in stats:
            print(f"Samples completed: {stats['samples_completed']}")

    elif args.action == 'status':
        client = LabelStudioClient()
        if client.check_connection():
            print("✓ Connected to Label Studio")
            for task_type, project_id in PROJECT_MAPPING.items():
                project = client.get_project(project_id)
                if project:
                    print(f"  - {task_type}: Project '{project.get('title')}' (ID: {project_id})")
                else:
                    print(f"  - {task_type}: Project {project_id} not found")
        else:
            print("✗ Cannot connect to Label Studio")

    elif args.action == 'reopen':
        if args.chunk_id:
            success = reopen_chunk(args.chunk_id)
            if success:
                print(f"✓ Chunk {args.chunk_id} reopened for review")
            else:
                print(f"✗ Failed to reopen chunk {args.chunk_id}")
        elif args.sample_id and args.all:
            count = reopen_sample(args.sample_id)
            print(f"✓ Reopened {count} chunks for sample {args.sample_id}")
        else:
            print("Error: Specify --chunk-id or --sample-id with --all")


if __name__ == "__main__":
    main()

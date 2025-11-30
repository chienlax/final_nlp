"""
Label Studio synchronization module for the NLP pipeline (v3 - Sample-level).

Handles pushing full samples for unified annotation and pulling completed
annotations back into the database. Sample-level review (no chunking).

Changes from v2:
- No chunking - entire sample pushed as single task
- 5-column inline editing: play | original transcript | revised | original translation | revised
- Per-sentence TextArea parsing
- Revision history tracking via update_sentence_review() SQL function

Usage:
    python label_studio_sync.py push --limit 10
    python label_studio_sync.py pull
    python label_studio_sync.py reopen --sample-id <uuid>
    python label_studio_sync.py status
"""

import argparse
import html
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

from utils.data_utils import get_pg_connection, log_processing


# =============================================================================
# CONFIGURATION
# =============================================================================

# Label Studio configuration from environment
LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8085")
LABEL_STUDIO_API_KEY = os.getenv("LABEL_STUDIO_API_KEY", "")

# Audio server URL for serving audio files to Label Studio
AUDIO_SERVER_URL = os.getenv("AUDIO_SERVER_URL", "http://localhost:8081")
AUDIO_PUBLIC_URL = os.getenv("AUDIO_PUBLIC_URL", "http://localhost:8081")

# Default project ID for sample review
LS_PROJECT_ID = os.getenv("LS_PROJECT_SAMPLE_REVIEW", "1")


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
# DATABASE FUNCTIONS - SAMPLE-LEVEL REVIEW
# =============================================================================

def get_samples_for_review(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get samples ready to be pushed to Label Studio (REVIEW_PREPARED state).

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.audio_file_path,
                    s.duration_seconds,
                    s.source_metadata->>'title' AS video_title,
                    COALESCE(src.channel_name, src.name, 'Unknown Channel') AS channel_name,
                    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id) AS sentence_count
                FROM samples s
                LEFT JOIN sources src ON s.source_id = src.source_id
                WHERE s.processing_state = 'REVIEW_PREPARED'
                  AND s.is_deleted = FALSE
                  AND s.label_studio_task_id IS NULL
                ORDER BY s.priority DESC, s.created_at ASC
                LIMIT %s
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_sentences_for_sample(sample_id: str) -> List[Dict[str, Any]]:
    """
    Get sentence reviews for a sample to build Label Studio task data.

    Args:
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
                    sr.original_translation,
                    sr.sentence_audio_path
                FROM sentence_reviews sr
                WHERE sr.sample_id = %s
                ORDER BY sr.sentence_idx ASC
                """,
                (sample_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_sample_label_studio_info(
    sample_id: str,
    project_id: int,
    task_id: int
) -> None:
    """
    Update sample with Label Studio project and task IDs.

    Args:
        sample_id: UUID of the sample.
        project_id: Label Studio project ID.
        task_id: Label Studio task ID.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE samples
                SET label_studio_project_id = %s,
                    label_studio_task_id = %s,
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (project_id, task_id, sample_id)
            )

            # Transition to IN_REVIEW state
            cur.execute(
                "SELECT transition_sample_state(%s, 'IN_REVIEW'::processing_state, %s)",
                (sample_id, 'label_studio_sync')
            )

            conn.commit()
    finally:
        conn.close()


def save_sample_review_results(
    sample_id: str,
    task_data: Dict[str, Any],
    annotation_results: List[Dict[str, Any]],
    reviewer: str
) -> Dict[str, int]:
    """
    Save review results from Label Studio back to database.

    Parses per-sentence TextArea values and calls update_sentence_review()
    for each sentence with changes.

    Args:
        sample_id: UUID of the sample.
        task_data: Original task data (has sentence info).
        annotation_results: Label Studio annotation results.
        reviewer: Reviewer identifier.

    Returns:
        Statistics dictionary with counts.
    """
    conn = get_pg_connection()
    stats = {
        'updated': 0,
        'unchanged': 0,
        'transcript_changes': 0,
        'translation_changes': 0,
        'timestamp_changes': 0,
        'rejected': 0,
    }

    try:
        with conn.cursor() as cur:
            # Parse annotation results
            # Extract per-sentence edits from the HyperText embedded form
            # Results format depends on template - look for textarea results
            
            sentence_edits = {}  # idx -> {transcript, translation, start_ms, end_ms, rejected}
            
            for result_item in annotation_results:
                from_name = result_item.get('from_name', '')
                result_type = result_item.get('type', '')
                value = result_item.get('value', {})
                
                # Parse textarea results with naming convention: revised_transcript_0042, revised_translation_0042
                if result_type == 'textarea' and '_' in from_name:
                    parts = from_name.rsplit('_', 1)
                    if len(parts) == 2:
                        field_type = parts[0]
                        try:
                            sentence_idx = int(parts[1])
                        except ValueError:
                            continue
                        
                        if sentence_idx not in sentence_edits:
                            sentence_edits[sentence_idx] = {}
                        
                        text_value = value.get('text', [''])[0] if isinstance(value.get('text'), list) else value.get('text', '')
                        
                        if field_type == 'revised_transcript':
                            sentence_edits[sentence_idx]['transcript'] = text_value
                        elif field_type == 'revised_translation':
                            sentence_edits[sentence_idx]['translation'] = text_value
                
                # Parse number inputs for timestamps: start_ms_0042, end_ms_0042
                elif result_type == 'number' and '_' in from_name:
                    parts = from_name.rsplit('_', 1)
                    if len(parts) == 2:
                        field_type = '_'.join(from_name.split('_')[:-1])  # start_ms or end_ms
                        try:
                            sentence_idx = int(parts[1])
                        except ValueError:
                            continue
                        
                        if sentence_idx not in sentence_edits:
                            sentence_edits[sentence_idx] = {}
                        
                        num_value = value.get('number')
                        if num_value is not None:
                            if field_type == 'start_ms':
                                sentence_edits[sentence_idx]['start_ms'] = int(num_value)
                            elif field_type == 'end_ms':
                                sentence_edits[sentence_idx]['end_ms'] = int(num_value)
                
                # Parse checkbox for rejection: reject_0042
                elif result_type == 'choices' and from_name.startswith('reject_'):
                    try:
                        sentence_idx = int(from_name.split('_')[1])
                    except (ValueError, IndexError):
                        continue
                    
                    if sentence_idx not in sentence_edits:
                        sentence_edits[sentence_idx] = {}
                    
                    choices = value.get('choices', [])
                    sentence_edits[sentence_idx]['rejected'] = len(choices) > 0

            # Get original sentences from database
            cur.execute(
                """
                SELECT sentence_idx, original_transcript, original_translation,
                       original_start_ms, original_end_ms
                FROM sentence_reviews
                WHERE sample_id = %s
                ORDER BY sentence_idx
                """,
                (sample_id,)
            )
            original_sentences = {
                row[0]: {
                    'transcript': row[1], 
                    'translation': row[2],
                    'start_ms': row[3],
                    'end_ms': row[4]
                } 
                for row in cur.fetchall()
            }

            # Process each sentence with edits
            for sentence_idx, edits in sentence_edits.items():
                original = original_sentences.get(sentence_idx, {})
                
                new_transcript = edits.get('transcript')
                new_translation = edits.get('translation')
                new_start_ms = edits.get('start_ms')
                new_end_ms = edits.get('end_ms')
                is_rejected = edits.get('rejected', False)
                
                orig_transcript = original.get('transcript', '')
                orig_translation = original.get('translation', '')
                orig_start_ms = original.get('start_ms', 0)
                orig_end_ms = original.get('end_ms', 0)
                
                transcript_changed = (new_transcript is not None 
                                      and new_transcript.strip() != orig_transcript.strip())
                translation_changed = (new_translation is not None 
                                       and new_translation.strip() != orig_translation.strip())
                start_changed = (new_start_ms is not None and new_start_ms != orig_start_ms)
                end_changed = (new_end_ms is not None and new_end_ms != orig_end_ms)
                
                has_changes = transcript_changed or translation_changed or start_changed or end_changed or is_rejected
                
                if has_changes:
                    # Call update function that handles revision tracking
                    cur.execute(
                        """
                        SELECT update_sentence_review(
                            %s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s
                        )
                        """,
                        (
                            sample_id,
                            sentence_idx,
                            new_transcript if transcript_changed else None,
                            new_translation if translation_changed else None,
                            new_start_ms if start_changed else None,
                            new_end_ms if end_changed else None,
                            is_rejected,
                            reviewer
                        )
                    )
                    stats['updated'] += 1
                    
                    if transcript_changed:
                        stats['transcript_changes'] += 1
                    if translation_changed:
                        stats['translation_changes'] += 1
                    if start_changed or end_changed:
                        stats['timestamp_changes'] += 1
                    if is_rejected:
                        stats['rejected'] += 1
                else:
                    stats['unchanged'] += 1

            # Also parse sample-level decisions
            decision = None
            audio_quality = None
            transcript_quality = None
            translation_quality = None
            confidence = None
            notes = None
            
            for result_item in annotation_results:
                from_name = result_item.get('from_name', '')
                result_type = result_item.get('type', '')
                value = result_item.get('value', {})
                
                if from_name == 'decision' and result_type == 'choices':
                    choices = value.get('choices', [])
                    decision = choices[0] if choices else None
                elif from_name == 'audio_quality' and result_type == 'choices':
                    choices = value.get('choices', [])
                    audio_quality = choices[0] if choices else None
                elif from_name == 'transcript_quality' and result_type == 'choices':
                    choices = value.get('choices', [])
                    transcript_quality = choices[0] if choices else None
                elif from_name == 'translation_quality' and result_type == 'choices':
                    choices = value.get('choices', [])
                    translation_quality = choices[0] if choices else None
                elif from_name == 'confidence' and result_type == 'rating':
                    confidence = value.get('rating')
                elif from_name == 'notes' and result_type == 'textarea':
                    text = value.get('text', [''])[0] if isinstance(value.get('text'), list) else value.get('text', '')
                    notes = text if text else None

            # Update sample with review summary
            review_metadata = {
                'decision': decision,
                'audio_quality': audio_quality,
                'transcript_quality': transcript_quality,
                'translation_quality': translation_quality,
                'confidence': confidence,
                'notes': notes,
                'reviewer': reviewer,
                'reviewed_at': datetime.utcnow().isoformat(),
                'stats': stats,
            }
            
            cur.execute(
                """
                UPDATE samples 
                SET processing_metadata = processing_metadata || %s
                WHERE sample_id = %s
                """,
                (Json({'review_summary': review_metadata}), sample_id)
            )

            # Transition state based on decision
            new_state = 'VERIFIED'
            if decision == 'reject':
                new_state = 'REJECTED'
            elif decision == 'needs_revision':
                new_state = 'REVIEW_PREPARED'  # Re-review needed
            
            cur.execute(
                "SELECT transition_sample_state(%s, %s::processing_state, %s)",
                (sample_id, new_state, 'label_studio_sync')
            )

            conn.commit()
            return stats

    except psycopg2.Error as e:
        conn.rollback()
        print(f"Error saving review results: {e}")
        return stats
    finally:
        conn.close()


# =============================================================================
# HTML GENERATION FOR TASK DATA
# =============================================================================

def build_sentences_html(
    sample_id: str,
    sentences: List[Dict[str, Any]],
    audio_base_url: str
) -> str:
    """
    Build HTML table for editing sentences (transcript & translation).

    This is the EDITING table - not for audio playback.
    Audio playback is handled by Label Studio's native Paragraphs + Audio tags.

    Columns: Index | Timestamps | Original Transcript | Revised Transcript | 
             Original Translation | Revised Translation | Reject

    Args:
        sample_id: UUID of the sample.
        sentences: List of sentence dictionaries.
        audio_base_url: Base URL for audio files (not used in this version).

    Returns:
        HTML string for the editing table.
    """
    rows = []
    
    for sent in sentences:
        idx = sent['sentence_idx']
        
        orig_transcript = html.escape(sent.get('original_transcript', ''))
        orig_translation = html.escape(sent.get('original_translation', ''))
        
        start_ms = sent['original_start_ms']
        end_ms = sent['original_end_ms']
        start_sec = start_ms / 1000.0
        end_sec = end_ms / 1000.0
        
        # Build row with editing controls
        row = f'''
        <tr data-sentence-idx="{idx}" id="row_{idx:04d}">
            <td style="width: 40px; text-align: center; vertical-align: top; padding: 8px; background: #f5f5f5;">
                <span style="font-size: 12px; font-weight: 700; background: #667eea; color: white; padding: 3px 8px; border-radius: 12px;">{idx:03d}</span>
            </td>
            <td style="width: 80px; text-align: center; vertical-align: top; padding: 6px; background: #fafafa;">
                <div style="display: flex; flex-direction: column; gap: 2px;">
                    <span style="font-size: 10px; color: #666;">{start_sec:.1f}s - {end_sec:.1f}s</span>
                    <input type="number" name="start_ms_{idx:04d}" value="{start_ms}" step="100" 
                           style="width: 60px; font-size: 9px; padding: 2px; border: 1px solid #ccc; border-radius: 3px; text-align: center;">
                    <input type="number" name="end_ms_{idx:04d}" value="{end_ms}" step="100"
                           style="width: 60px; font-size: 9px; padding: 2px; border: 1px solid #ccc; border-radius: 3px; text-align: center;">
                </div>
            </td>
            <td style="width: 20%; vertical-align: top; padding: 8px; background: #f0f0f0;">
                <div style="font-size: 12px; line-height: 1.4; white-space: pre-wrap;">{orig_transcript}</div>
            </td>
            <td style="width: 20%; vertical-align: top; padding: 4px;">
                <textarea name="revised_transcript_{idx:04d}" 
                          style="width: 100%; min-height: 60px; font-size: 12px; border: 1px solid #ddd; border-radius: 4px; padding: 6px; resize: vertical; line-height: 1.4;"
                          placeholder="Edit transcript...">{orig_transcript}</textarea>
            </td>
            <td style="width: 20%; vertical-align: top; padding: 8px; background: #fff8e1;">
                <div style="font-size: 12px; line-height: 1.4; white-space: pre-wrap;">{orig_translation}</div>
            </td>
            <td style="width: 20%; vertical-align: top; padding: 4px;">
                <textarea name="revised_translation_{idx:04d}" 
                          style="width: 100%; min-height: 60px; font-size: 12px; border: 1px solid #ddd; border-radius: 4px; padding: 6px; resize: vertical; line-height: 1.4;"
                          placeholder="Edit translation...">{orig_translation}</textarea>
            </td>
            <td style="width: 50px; text-align: center; vertical-align: top; padding: 8px;">
                <label style="display: flex; flex-direction: column; align-items: center; gap: 2px; cursor: pointer;">
                    <input type="checkbox" name="reject_{idx:04d}" style="width: 16px; height: 16px;">
                    <span style="font-size: 9px; color: #c62828;">Reject</span>
                </label>
            </td>
        </tr>'''
        rows.append(row)
    
    # Build complete table
    table_html = f'''
<table style="width: 100%; border-collapse: collapse; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px;">
    <thead>
        <tr>
            <th style="width: 40px; text-align: center; background: #667eea; color: white; padding: 8px 4px; font-size: 10px;">#</th>
            <th style="width: 80px; text-align: center; background: #667eea; color: white; padding: 8px 4px; font-size: 10px;">Time (ms)</th>
            <th style="width: 20%; background: #667eea; color: white; padding: 8px; text-align: left; font-size: 10px;">Original Transcript</th>
            <th style="width: 20%; background: #667eea; color: white; padding: 8px; text-align: left; font-size: 10px;">✏️ Revised Transcript</th>
            <th style="width: 20%; background: #667eea; color: white; padding: 8px; text-align: left; font-size: 10px;">Original Translation</th>
            <th style="width: 20%; background: #667eea; color: white; padding: 8px; text-align: left; font-size: 10px;">✏️ Revised Translation</th>
            <th style="width: 50px; text-align: center; background: #667eea; color: white; padding: 8px 4px; font-size: 10px;">❌</th>
        </tr>
    </thead>
    <tbody>
        {''.join(rows)}
    </tbody>
</table>
'''
    
    return table_html


def build_paragraphs_data(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build paragraphs data for Label Studio's Paragraphs tag.

    Each paragraph has start/end timestamps for audio sync.

    Args:
        sentences: List of sentence dictionaries.

    Returns:
        List of paragraph dictionaries for Label Studio.
    """
    paragraphs = []
    
    for sent in sentences:
        idx = sent['sentence_idx']
        start_ms = sent['original_start_ms']
        end_ms = sent['original_end_ms']
        transcript = sent.get('original_transcript', '')
        
        paragraph = {
            'idx': f"{idx:03d}",
            'start': start_ms / 1000.0,  # Convert to seconds
            'end': end_ms / 1000.0,
            'text': transcript,
        }
        paragraphs.append(paragraph)
    
    return paragraphs


# =============================================================================
# PUSH/PULL FUNCTIONS - SAMPLE-LEVEL REVIEW
# =============================================================================

def push_sample_reviews(
    limit: int = 10,
    project_id: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Push samples to Label Studio as review tasks.

    Args:
        limit: Maximum number of samples to push.
        project_id: Label Studio project ID (uses env default if not provided).
        dry_run: If True, don't actually create tasks.

    Returns:
        Statistics dictionary.
    """
    stats = {'pushed': 0, 'skipped': 0, 'errors': 0}

    project_id = project_id or LS_PROJECT_ID
    client = LabelStudioClient()

    if not dry_run and not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    samples = get_samples_for_review(limit=limit)
    print(f"Found {len(samples)} samples ready for review")

    for sample in samples:
        sample_id = str(sample['sample_id'])
        external_id = sample['external_id']
        video_title = sample.get('video_title', external_id)
        channel_name = sample.get('channel_name', 'Unknown Channel')
        duration_seconds = sample.get('duration_seconds', 0)
        sentence_count = sample.get('sentence_count', 0)

        # Get sentences for this sample
        sentences = get_sentences_for_sample(sample_id)

        if not sentences:
            print(f"  Skipping {external_id}: No sentences found")
            stats['skipped'] += 1
            continue

        # Build paragraphs data for Label Studio's native Paragraphs tag
        paragraphs = build_paragraphs_data(sentences)

        # Build HTML table for editing (no audio controls - audio handled by Paragraphs tag)
        sentences_html = build_sentences_html(
            sample_id=sample_id,
            sentences=sentences,
            audio_base_url=AUDIO_PUBLIC_URL
        )

        # Full sample audio URL for Label Studio's Audio tag
        audio_url = f"{AUDIO_PUBLIC_URL}/audio/{external_id}.wav"

        # Format duration for display
        duration_min = int(duration_seconds // 60)
        duration_sec = int(duration_seconds % 60)
        duration_display = f"{duration_min}:{duration_sec:02d}"

        # Build task data with new format for Paragraphs tag
        task_data = {
            'sample_id': sample_id,
            'external_id': external_id,
            'video_title': video_title[:100] if video_title else external_id,
            'channel_name': channel_name,
            'sentence_count': str(sentence_count),
            'duration_display': duration_display,
            'duration_seconds': str(int(duration_seconds)),
            'audio_url': audio_url,
            'paragraphs': paragraphs,
            'sentences_html': sentences_html,
        }

        if dry_run:
            print(f"  [DRY RUN] Would push {external_id} ({sentence_count} sentences)")
            stats['pushed'] += 1
            continue

        # Create task in Label Studio
        task_id = client.create_task(project_id, task_data)

        if task_id:
            # Update sample with Label Studio info
            update_sample_label_studio_info(
                sample_id=sample_id,
                project_id=int(project_id),
                task_id=task_id
            )

            print(f"  Pushed {external_id} ({sentence_count} sentences) -> Task {task_id}")
            stats['pushed'] += 1
        else:
            print(f"  Failed to push {external_id}")
            stats['errors'] += 1

    return stats


def pull_sample_reviews(
    project_id: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Pull completed sample review annotations from Label Studio.

    Args:
        project_id: Label Studio project ID.
        dry_run: If True, don't update database.

    Returns:
        Statistics dictionary.
    """
    stats = {
        'pulled': 0, 
        'skipped': 0, 
        'errors': 0, 
        'verified': 0,
        'rejected': 0,
        'needs_revision': 0,
    }

    project_id = project_id or LS_PROJECT_ID
    client = LabelStudioClient()

    if not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    completed_tasks = client.get_completed_tasks(project_id)
    print(f"Found {len(completed_tasks)} completed review tasks")

    for task in completed_tasks:
        task_id = task.get('id')
        task_data = task.get('data', {})
        sample_id = task_data.get('sample_id')

        if not sample_id:
            print(f"  Skipping task {task_id}: Missing sample_id")
            stats['skipped'] += 1
            continue

        annotations = task.get('annotations', [])
        if not annotations:
            continue

        latest_annotation = annotations[-1]
        results = latest_annotation.get('result', [])
        reviewer = str(latest_annotation.get('completed_by', 'annotator'))

        if dry_run:
            print(f"  [DRY RUN] Would pull task {task_id} -> sample {sample_id}")
            stats['pulled'] += 1
            continue

        # Save review results
        result_stats = save_sample_review_results(
            sample_id=sample_id,
            task_data=task_data,
            annotation_results=results,
            reviewer=reviewer
        )

        # Log the operation
        log_processing(
            operation='sample_review_completed',
            success=True,
            sample_id=sample_id,
            executor='label_studio_sync',
            output_summary={
                'task_id': task_id,
                'reviewer': reviewer,
                **result_stats,
            },
        )

        # Parse decision for stats
        decision = None
        for result_item in results:
            if result_item.get('from_name') == 'decision':
                choices = result_item.get('value', {}).get('choices', [])
                decision = choices[0] if choices else None
                break

        if decision == 'approve':
            stats['verified'] += 1
        elif decision == 'reject':
            stats['rejected'] += 1
        elif decision == 'needs_revision':
            stats['needs_revision'] += 1

        print(f"  Pulled task {task_id} -> sample {sample_id} "
              f"({result_stats['updated']} changes, decision: {decision})")
        stats['pulled'] += 1

    return stats


def reopen_sample(sample_id: str) -> bool:
    """
    Reopen a sample for re-review.

    Args:
        sample_id: UUID of the sample to reopen.

    Returns:
        True if successful.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get sample info
            cur.execute(
                """
                SELECT sample_id, label_studio_task_id, processing_state
                FROM samples
                WHERE sample_id = %s
                """,
                (sample_id,)
            )
            sample = cur.fetchone()

            if not sample:
                print(f"Sample not found: {sample_id}")
                return False

            task_id = sample['label_studio_task_id']

            # Delete task from Label Studio if exists
            if task_id:
                client = LabelStudioClient()
                client.delete_task(task_id)

            # Reset sample Label Studio info
            cur.execute(
                """
                UPDATE samples
                SET label_studio_task_id = NULL,
                    label_studio_project_id = NULL,
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (sample_id,)
            )

            # Reset sentence reviews (keep originals, clear reviewed values)
            cur.execute(
                """
                UPDATE sentence_reviews
                SET reviewed_transcript = NULL,
                    reviewed_translation = NULL,
                    is_transcript_changed = FALSE,
                    is_translation_changed = FALSE,
                    revision_count = 0,
                    previous_transcript = NULL,
                    previous_translation = NULL,
                    last_revised_at = NULL,
                    last_revised_by = NULL,
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (sample_id,)
            )

            # Transition back to REVIEW_PREPARED
            cur.execute(
                "SELECT transition_sample_state(%s, 'REVIEW_PREPARED'::processing_state, %s)",
                (sample_id, 'label_studio_reopen')
            )

            conn.commit()
            print(f"Reopened sample {sample_id} for re-review")
            return True

    except psycopg2.Error as e:
        conn.rollback()
        print(f"Error reopening sample: {e}")
        return False
    finally:
        conn.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Synchronize sample reviews with Label Studio (v3).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Push samples for review
    python label_studio_sync.py push --limit 10

    # Pull completed reviews
    python label_studio_sync.py pull

    # Check status
    python label_studio_sync.py status

    # Reopen a sample for re-review
    python label_studio_sync.py reopen --sample-id <uuid>

    # Dry run to preview
    python label_studio_sync.py push --limit 5 --dry-run
        """
    )
    
    subparsers = parser.add_subparsers(dest='action', help='Action to perform')

    # Push subcommand
    push_parser = subparsers.add_parser('push', help='Push samples to Label Studio')
    push_parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Maximum number of samples to push (default: 10)'
    )
    push_parser.add_argument(
        '--project-id',
        help='Label Studio project ID (default from LS_PROJECT_SAMPLE_REVIEW env)'
    )
    push_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )

    # Pull subcommand
    pull_parser = subparsers.add_parser('pull', help='Pull completed annotations')
    pull_parser.add_argument(
        '--project-id',
        help='Label Studio project ID (default from LS_PROJECT_SAMPLE_REVIEW env)'
    )
    pull_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )

    # Status subcommand
    status_parser = subparsers.add_parser('status', help='Check Label Studio status')

    # Reopen subcommand
    reopen_parser = subparsers.add_parser('reopen', help='Reopen sample for re-review')
    reopen_parser.add_argument(
        '--sample-id',
        required=True,
        help='UUID of sample to reopen'
    )

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        return

    print("=" * 60)
    print("Label Studio Sync v3 (Sample-level Review)")
    print("=" * 60)
    print(f"Label Studio URL: {LABEL_STUDIO_URL}")
    print(f"Project ID: {LS_PROJECT_ID}")
    print(f"Action: {args.action}")
    print()

    if args.action == 'push':
        stats = push_sample_reviews(
            limit=args.limit,
            project_id=args.project_id,
            dry_run=args.dry_run
        )
        print(f"\n{'='*40}")
        print(f"Pushed: {stats['pushed']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")

    elif args.action == 'pull':
        stats = pull_sample_reviews(
            project_id=args.project_id,
            dry_run=args.dry_run
        )
        print(f"\n{'='*40}")
        print(f"Pulled: {stats['pulled']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print(f"Verified: {stats['verified']}")
        print(f"Rejected: {stats['rejected']}")
        print(f"Needs Revision: {stats['needs_revision']}")

    elif args.action == 'status':
        client = LabelStudioClient()
        if client.check_connection():
            print("✓ Connected to Label Studio")
            project = client.get_project(LS_PROJECT_ID)
            if project:
                print(f"  - Project: '{project.get('title')}' (ID: {LS_PROJECT_ID})")
                print(f"    Tasks: {project.get('task_number', 0)}")
            else:
                print(f"  - Project {LS_PROJECT_ID} not found")
        else:
            print("✗ Cannot connect to Label Studio")

    elif args.action == 'reopen':
        success = reopen_sample(args.sample_id)
        if success:
            print(f"✓ Sample {args.sample_id} reopened for review")
        else:
            print(f"✗ Failed to reopen sample {args.sample_id}")


if __name__ == "__main__":
    main()

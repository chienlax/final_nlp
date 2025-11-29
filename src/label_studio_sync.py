"""
Label Studio synchronization module for the NLP pipeline.

Handles pushing samples for annotation and pulling completed annotations
back into the database. Supports webhook handlers for real-time sync.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.data_utils import (
    get_pg_connection,
    get_review_queue,
    insert_annotation,
    update_annotation_status,
    transition_state,
    log_processing,
    insert_transcript_revision,
    insert_translation_revision,
)


# Label Studio configuration from environment
# Default to localhost:8085 for local development (Docker maps 8085->8080)
# Inside Docker containers, use http://label_studio:8085 (set via docker-compose.yml)
LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8085")
LABEL_STUDIO_API_KEY = os.getenv("LABEL_STUDIO_API_KEY", "")

# Audio server URL for serving audio files to Label Studio
# AUDIO_SERVER_URL: Internal URL for Docker-to-Docker communication
# AUDIO_PUBLIC_URL: External URL for browser access (Label Studio UI loads audio in browser)
AUDIO_SERVER_URL = os.getenv("AUDIO_SERVER_URL", "http://localhost:8081")
AUDIO_PUBLIC_URL = os.getenv("AUDIO_PUBLIC_URL", "http://localhost:8081")

# Task type to Label Studio project mapping
PROJECT_MAPPING = {
    'transcript_correction': os.getenv("LS_PROJECT_TRANSCRIPT", "1"),
    'translation_review': os.getenv("LS_PROJECT_TRANSLATION", "2"),
    'audio_segmentation': os.getenv("LS_PROJECT_SEGMENTATION", "3"),
}


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
        """
        Check if Label Studio is accessible.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            resp = self.session.get(f"{self.url}/api/projects/")
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"Connection error: {e}")
            return False

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Get project details.

        Args:
            project_id: Label Studio project ID.

        Returns:
            Project data or None if not found.
        """
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
        """
        Get task details including annotations.

        Args:
            task_id: Label Studio task ID.

        Returns:
            Task data or None if not found.
        """
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
        """
        Get all completed tasks from a project.

        Args:
            project_id: Label Studio project ID.
            since: Only fetch tasks completed after this time.

        Returns:
            List of completed task data.
        """
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
                    # Check if task is labeled (has annotations)
                    if task.get('is_labeled') or task.get('total_annotations', 0) > 0:
                        # Fetch full task details including annotations
                        task_detail = self.get_task(task['id'])
                        if task_detail and task_detail.get('annotations'):
                            tasks.append(task_detail)

        except requests.RequestException as e:
            print(f"Error fetching tasks: {e}")

        return tasks

    def delete_task(self, task_id: int) -> bool:
        """
        Delete a task from Label Studio.

        Args:
            task_id: Task ID to delete.

        Returns:
            True if successful, False otherwise.
        """
        try:
            resp = self.session.delete(f"{self.url}/api/tasks/{task_id}/")
            return resp.status_code == 204
        except requests.RequestException as e:
            print(f"Error deleting task: {e}")
        return False


def push_to_label_studio(
    task_type: str = 'transcript_correction',
    limit: Optional[int] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Push samples from review queue to Label Studio.

    Args:
        task_type: Type of annotation task.
        limit: Maximum number of samples to push.
        dry_run: If True, don't actually create tasks.

    Returns:
        Statistics dictionary.
    """
    stats = {'pushed': 0, 'skipped': 0, 'errors': 0}

    project_id = PROJECT_MAPPING.get(task_type)
    if not project_id:
        print(f"Unknown task type: {task_type}")
        return stats

    client = LabelStudioClient()

    if not dry_run and not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    try:
        # Get samples ready for review (function creates its own connection)
        samples = get_review_queue(task_type=task_type, limit=limit)
        print(f"Found {len(samples)} samples ready for {task_type}")

        for sample in samples:
            sample_id = sample['sample_id']

            # Generate HTTP URL for audio file (use PUBLIC URL for browser access)
            file_path = sample.get('audio_file_path', '')
            if file_path:
                # Extract filename from path (e.g., "data/raw/audio/xyz.wav" -> "xyz.wav")
                audio_filename = Path(file_path).name
                audio_url = f"{AUDIO_PUBLIC_URL}/audio/{audio_filename}"
            else:
                audio_url = ''

            # Prepare task data based on task type
            if task_type == 'transcript_correction':
                task_data = {
                    'sample_id': sample_id,
                    'external_id': sample.get('external_id', ''),
                    'duration_seconds': str(sample.get('duration_seconds', 0)),
                    'subtitle_type': sample.get('subtitle_type', 'unknown'),
                    'transcript_text': sample.get('transcript', ''),
                    'audio': audio_url,
                }
            elif task_type == 'translation_review':
                task_data = {
                    'sample_id': sample_id,
                    'source_text': sample.get('transcript', ''),
                    'translation': sample.get('translation', ''),
                    'metadata': json.dumps(sample.get('metadata', {})),
                }
            else:
                task_data = {
                    'sample_id': sample_id,
                    'content': json.dumps(sample),
                }

            if dry_run:
                print(f"  [DRY RUN] Would push sample {sample_id}")
                stats['pushed'] += 1
                continue

            # Create task in Label Studio
            task_id = client.create_task(project_id, task_data)

            if task_id:
                # Record annotation task in database
                insert_annotation(
                    sample_id=sample_id,
                    task_type=task_type,
                    label_studio_project_id=int(project_id),
                    label_studio_task_id=task_id,
                )
                print(f"  Pushed sample {sample_id} -> Task {task_id}")
                stats['pushed'] += 1
            else:
                stats['errors'] += 1

    except Exception as e:
        print(f"Error: {e}")
        stats['errors'] += 1

    return stats


def pull_from_label_studio(
    task_type: str = 'transcript_correction',
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Pull completed annotations from Label Studio and update database.

    Args:
        task_type: Type of annotation task.
        dry_run: If True, don't update database.

    Returns:
        Statistics dictionary.
    """
    stats = {'pulled': 0, 'skipped': 0, 'errors': 0}

    project_id = PROJECT_MAPPING.get(task_type)
    if not project_id:
        print(f"Unknown task type: {task_type}")
        return stats

    client = LabelStudioClient()

    if not client.check_connection():
        print("Cannot connect to Label Studio.")
        return stats

    try:
        # Get completed tasks from Label Studio
        completed_tasks = client.get_completed_tasks(project_id)
        print(f"Found {len(completed_tasks)} completed tasks")

        for task in completed_tasks:
            task_id = task.get('id')
            task_data = task.get('data', {})
            sample_id = task_data.get('sample_id')

            if not sample_id:
                print(f"  Skipping task {task_id}: No sample_id")
                stats['skipped'] += 1
                continue

            # Get the latest annotation
            annotations = task.get('annotations', [])
            if not annotations:
                continue

            latest_annotation = annotations[-1]
            result = latest_annotation.get('result', [])

            if dry_run:
                print(f"  [DRY RUN] Would pull task {task_id} -> sample {sample_id}")
                stats['pulled'] += 1
                continue

            # Process based on task type
            if task_type == 'transcript_correction':
                # Extract corrected text
                corrected_text = None
                for item in result:
                    if item.get('type') == 'textarea':
                        corrected_text = item.get('value', {}).get('text', [''])[0]
                        break

                if corrected_text:
                    # Update database with correction
                    insert_transcript_revision(
                        sample_id=sample_id,
                        transcript_text=corrected_text,
                        revision_type='human_corrected',
                        created_by=str(latest_annotation.get('completed_by', 'annotator')),
                    )

            elif task_type == 'translation_review':
                # Extract corrected translation
                corrected_translation = None
                for item in result:
                    if item.get('type') == 'textarea':
                        corrected_translation = item.get('value', {}).get('text', [''])[0]
                        break

                if corrected_translation:
                    insert_translation_revision(
                        sample_id=sample_id,
                        transcript_revision_id=task_data.get('transcript_id'),
                        translation_text=corrected_translation,
                        revision_type='human_corrected',
                        translator='human',
                        created_by=str(latest_annotation.get('completed_by', 'annotator')),
                    )

            # Update annotation status (lookup by label_studio_task_id)
            conn = get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE annotations 
                        SET status = 'completed', 
                            result = %s,
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE label_studio_task_id = %s
                        """,
                        (json.dumps(result), task_id)
                    )
                    conn.commit()
            finally:
                conn.close()

            # Transition sample state based on task type
            if task_type == 'transcript_correction':
                new_state = 'TRANSCRIPT_VERIFIED'
            elif task_type == 'translation_review':
                new_state = 'FINAL'
            elif task_type == 'segment_review':
                new_state = 'SEGMENT_VERIFIED'
            else:
                new_state = 'TRANSCRIPT_VERIFIED'  # Default fallback

            transition_state(
                sample_id=sample_id,
                new_state=new_state,
                executor=f'label_studio_{task_type}',
            )

            # Log the operation
            log_processing(
                operation='annotation_completed',
                success=True,
                sample_id=sample_id,
                new_state=new_state,
                executor='label_studio_sync',
                output_summary={
                    'task_type': task_type,
                    'task_id': task_id,
                    'annotator': latest_annotation.get('completed_by'),
                },
            )

            print(f"  Pulled task {task_id} -> sample {sample_id}")
            stats['pulled'] += 1

    except Exception as e:
        print(f"Error: {e}")
        stats['errors'] += 1

    return stats


def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle incoming webhook from Label Studio.

    Called when an annotation is created or updated.

    Args:
        payload: Webhook payload from Label Studio.

    Returns:
        Response dictionary.
    """
    action = payload.get('action')
    task = payload.get('task', {})
    annotation = payload.get('annotation', {})

    task_id = task.get('id')
    sample_id = task.get('data', {}).get('sample_id')

    if action == 'ANNOTATION_CREATED':
        print(f"Annotation created for task {task_id}, sample {sample_id}")

        # Trigger pull for this specific task
        # In production, you'd process this immediately
        return {'status': 'received', 'task_id': task_id}

    elif action == 'ANNOTATION_UPDATED':
        print(f"Annotation updated for task {task_id}, sample {sample_id}")
        return {'status': 'received', 'task_id': task_id}

    return {'status': 'ignored', 'action': action}


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Synchronize annotations with Label Studio.'
    )
    parser.add_argument(
        'action',
        choices=['push', 'pull', 'status'],
        help='Action to perform'
    )
    parser.add_argument(
        '--task-type',
        choices=['transcript_correction', 'translation_review', 'audio_segmentation'],
        default='transcript_correction',
        help='Type of annotation task'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of items to process'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Label Studio Sync")
    print("=" * 60)
    print(f"Label Studio URL: {LABEL_STUDIO_URL}")
    print(f"Task Type: {args.task_type}")
    print(f"Action: {args.action}")
    print()

    if args.action == 'push':
        stats = push_to_label_studio(
            task_type=args.task_type,
            limit=args.limit,
            dry_run=args.dry_run
        )
        print(f"\nPushed: {stats['pushed']}, Errors: {stats['errors']}")

    elif args.action == 'pull':
        stats = pull_from_label_studio(
            task_type=args.task_type,
            dry_run=args.dry_run
        )
        print(f"\nPulled: {stats['pulled']}, Errors: {stats['errors']}")

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


if __name__ == "__main__":
    main()

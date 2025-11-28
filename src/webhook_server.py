"""
FastAPI Webhook Server for Label Studio integration.

Receives webhook callbacks from Label Studio when annotations are
created, updated, or deleted, and updates the database accordingly.

Usage:
    uvicorn src.webhook_server:app --host 0.0.0.0 --port 8000 --reload

Webhook Events:
    - ANNOTATION_CREATED: New annotation submitted
    - ANNOTATION_UPDATED: Existing annotation modified
    - TASK_CREATED: New task added to project
    - PROJECT_UPDATED: Project settings changed
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.data_utils import (
    get_pg_connection,
    update_annotation_status,
    transition_state,
    log_processing,
    insert_transcript_revision,
    insert_translation_revision,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('webhook_server')

# Configuration
LABEL_STUDIO_WEBHOOK_SECRET = os.getenv('LABEL_STUDIO_WEBHOOK_SECRET', '')
SKIP_GOLD_VALIDATION = os.getenv('SKIP_GOLD_VALIDATION', 'false').lower() == 'true'

# FastAPI app
app = FastAPI(
    title="Label Studio Webhook Server",
    description="Handles Label Studio annotation callbacks for the NLP pipeline",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Pydantic Models
# =============================================================================

class AnnotationData(BaseModel):
    """Annotation data from Label Studio webhook."""
    id: int
    result: list
    completed_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskData(BaseModel):
    """Task data from Label Studio webhook."""
    id: int
    data: Dict[str, Any]
    annotations: Optional[list] = []
    predictions: Optional[list] = []


class WebhookPayload(BaseModel):
    """Label Studio webhook payload."""
    action: str
    task: Optional[TaskData] = None
    annotation: Optional[AnnotationData] = None
    project: Optional[Dict[str, Any]] = None


# =============================================================================
# Helper Functions
# =============================================================================

def get_annotation_by_task_id(task_id: int) -> Optional[Dict[str, Any]]:
    """
    Get annotation record by Label Studio task ID.

    Args:
        task_id: Label Studio task ID.

    Returns:
        Annotation record or None.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT annotation_id, sample_id, task_type, status,
                       sample_sync_version_at_start
                FROM annotations
                WHERE label_studio_task_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id,)
            )
            row = cur.fetchone()
            if row:
                return {
                    'annotation_id': str(row[0]),
                    'sample_id': str(row[1]),
                    'task_type': row[2],
                    'status': row[3],
                    'sample_sync_version_at_start': row[4],
                }
    finally:
        conn.close()

    return None


def check_conflict(sample_id: str, expected_version: Optional[int]) -> bool:
    """
    Check if sample was modified since annotation started.

    Args:
        sample_id: Sample UUID.
        expected_version: Sync version when annotation started.

    Returns:
        True if conflict detected.
    """
    if expected_version is None:
        return False

    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sync_version FROM samples WHERE sample_id = %s",
                (sample_id,)
            )
            row = cur.fetchone()
            if row:
                return row[0] > expected_version
    finally:
        conn.close()

    return False


def unlock_sample(sample_id: str) -> bool:
    """
    Unlock a sample after annotation completes.

    Args:
        sample_id: Sample UUID.

    Returns:
        True if successful.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE samples
                SET locked_at = NULL,
                    locked_by = NULL,
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (sample_id,)
            )
            conn.commit()
            return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to unlock sample {sample_id}: {e}")
        return False
    finally:
        conn.close()


def extract_transcript_from_result(result: list) -> Optional[str]:
    """
    Extract corrected transcript from annotation result.

    Args:
        result: Label Studio annotation result.

    Returns:
        Corrected transcript text or None.
    """
    for item in result:
        if item.get('type') == 'textarea':
            value = item.get('value', {})
            if 'text' in value:
                text_list = value['text']
                if isinstance(text_list, list) and text_list:
                    return text_list[0]
                elif isinstance(text_list, str):
                    return text_list
        # Also check for 'corrected_transcript' name
        if item.get('from_name') == 'corrected_transcript':
            value = item.get('value', {})
            if 'text' in value:
                text_list = value['text']
                if isinstance(text_list, list) and text_list:
                    return text_list[0]
    return None


def extract_translation_from_result(result: list) -> Optional[str]:
    """
    Extract corrected translation from annotation result.

    Args:
        result: Label Studio annotation result.

    Returns:
        Corrected translation text or None.
    """
    for item in result:
        if item.get('from_name') == 'corrected_translation':
            value = item.get('value', {})
            if 'text' in value:
                text_list = value['text']
                if isinstance(text_list, list) and text_list:
                    return text_list[0]
                elif isinstance(text_list, str):
                    return text_list
    return None


def record_annotation_to_db(
    annotation_id: str,
    sample_id: str,
    task_type: str,
    result: list,
    annotator_id: Optional[int],
    has_conflict: bool = False,
) -> bool:
    """
    Record completed annotation to database.

    Args:
        annotation_id: Annotation UUID.
        sample_id: Sample UUID.
        task_type: Type of annotation task.
        result: Annotation result data.
        annotator_id: Label Studio user ID.
        has_conflict: Whether conflict was detected.

    Returns:
        True if successful.
    """
    try:
        # Update annotation status
        update_annotation_status(
            annotation_id=annotation_id,
            status='completed',
            result={'data': result, 'has_conflict': has_conflict},
        )

        # Process based on task type
        if task_type == 'transcript_verification':
            corrected_text = extract_transcript_from_result(result)
            if corrected_text:
                insert_transcript_revision(
                    sample_id=sample_id,
                    transcript_text=corrected_text,
                    revision_type='human_corrected',
                    created_by=f'annotator_{annotator_id}' if annotator_id else 'annotator',
                )

        elif task_type == 'translation_review':
            corrected_translation = extract_translation_from_result(result)
            if corrected_translation:
                insert_translation_revision(
                    sample_id=sample_id,
                    transcript_revision_id=None,  # Would need to look up
                    translation_text=corrected_translation,
                    revision_type='human_corrected',
                    translator='human',
                    created_by=f'annotator_{annotator_id}' if annotator_id else 'annotator',
                )

        # Transition sample state (unless conflict)
        if not has_conflict:
            transition_state(
                sample_id=sample_id,
                new_state='REVIEWED',
                executor='webhook_server',
            )

        # Unlock sample
        unlock_sample(sample_id)

        # Log the operation
        log_processing(
            operation='annotation_completed',
            success=True,
            sample_id=sample_id,
            new_state='REVIEWED' if not has_conflict else None,
            executor='webhook_server',
            output_summary={
                'task_type': task_type,
                'annotator_id': annotator_id,
                'has_conflict': has_conflict,
            },
        )

        return True

    except Exception as e:
        logger.error(f"Failed to record annotation: {e}")
        return False


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    x_label_studio_signature: Optional[str] = Header(None),
):
    """
    Handle Label Studio webhook callbacks.

    Processes annotation events and updates the database accordingly.
    """
    # Parse raw body for signature verification
    body = await request.body()
    
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    action = payload.get('action', 'UNKNOWN')
    logger.info(f"Received webhook: action={action}")

    # Handle different actions
    if action == 'ANNOTATION_CREATED':
        return await handle_annotation_created(payload)
    elif action == 'ANNOTATION_UPDATED':
        return await handle_annotation_updated(payload)
    elif action == 'TASK_CREATED':
        return await handle_task_created(payload)
    else:
        logger.debug(f"Ignoring action: {action}")
        return {"status": "ignored", "action": action}


async def handle_annotation_created(payload: dict) -> dict:
    """
    Handle new annotation submission.

    Args:
        payload: Webhook payload.

    Returns:
        Response dictionary.
    """
    task_data = payload.get('task', {})
    annotation_data = payload.get('annotation', {})

    task_id = task_data.get('id')
    sample_id = task_data.get('data', {}).get('sample_id')
    result = annotation_data.get('result', [])
    annotator_id = annotation_data.get('completed_by')

    if not task_id or not sample_id:
        logger.warning(f"Missing task_id or sample_id in webhook payload")
        return {"status": "error", "message": "Missing required fields"}

    logger.info(f"Processing annotation for task {task_id}, sample {sample_id}")

    # Look up annotation record
    annotation_record = get_annotation_by_task_id(task_id)
    
    if not annotation_record:
        logger.warning(f"No annotation record found for task {task_id}")
        return {"status": "error", "message": "Annotation record not found"}

    # Check for conflicts
    has_conflict = check_conflict(
        sample_id=sample_id,
        expected_version=annotation_record.get('sample_sync_version_at_start'),
    )

    if has_conflict:
        logger.warning(f"Conflict detected for sample {sample_id}")
        # Still record the annotation, but flag the conflict

    # Record to database
    success = record_annotation_to_db(
        annotation_id=annotation_record['annotation_id'],
        sample_id=sample_id,
        task_type=annotation_record['task_type'],
        result=result,
        annotator_id=annotator_id,
        has_conflict=has_conflict,
    )

    if success:
        return {
            "status": "success",
            "task_id": task_id,
            "sample_id": sample_id,
            "has_conflict": has_conflict,
        }
    else:
        return {"status": "error", "message": "Failed to record annotation"}


async def handle_annotation_updated(payload: dict) -> dict:
    """
    Handle annotation update.

    Args:
        payload: Webhook payload.

    Returns:
        Response dictionary.
    """
    # For updates, we'll process similarly to creates
    # Could add merge logic here for handling updates to existing annotations
    return await handle_annotation_created(payload)


async def handle_task_created(payload: dict) -> dict:
    """
    Handle new task creation in Label Studio.

    Args:
        payload: Webhook payload.

    Returns:
        Response dictionary.
    """
    task_data = payload.get('task', {})
    task_id = task_data.get('id')

    logger.info(f"Task created in Label Studio: {task_id}")

    return {"status": "received", "task_id": task_id}


@app.get("/api/conflicts")
async def list_conflicts():
    """
    List all annotations with detected conflicts.

    Returns:
        List of conflict records.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    a.annotation_id,
                    a.sample_id,
                    a.task_type,
                    a.conflict_detected,
                    a.conflict_resolution,
                    a.completed_at,
                    s.external_id,
                    s.sync_version
                FROM annotations a
                JOIN samples s ON a.sample_id = s.sample_id
                WHERE a.conflict_detected = TRUE
                ORDER BY a.completed_at DESC
                LIMIT 100
                """
            )
            columns = [desc[0] for desc in cur.description]
            conflicts = [dict(zip(columns, row)) for row in cur.fetchall()]
            
            # Convert UUIDs to strings
            for c in conflicts:
                c['annotation_id'] = str(c['annotation_id'])
                c['sample_id'] = str(c['sample_id'])

            return {"conflicts": conflicts, "count": len(conflicts)}

    finally:
        conn.close()


@app.post("/api/resolve-conflict/{annotation_id}")
async def resolve_conflict(
    annotation_id: str,
    resolution: str = "human_wins",
):
    """
    Resolve an annotation conflict.

    Args:
        annotation_id: Annotation UUID.
        resolution: Resolution type ('human_wins', 'crawler_wins', 'merged').

    Returns:
        Resolution result.
    """
    valid_resolutions = ['human_wins', 'crawler_wins', 'merged', 'pending_reflow']
    if resolution not in valid_resolutions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution. Must be one of: {valid_resolutions}"
        )

    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE annotations
                SET conflict_resolution = %s,
                    updated_at = NOW()
                WHERE annotation_id = %s
                RETURNING sample_id
                """,
                (resolution, annotation_id)
            )
            row = cur.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="Annotation not found")

            sample_id = str(row[0])

            # If human_wins, transition sample to REVIEWED
            if resolution == 'human_wins':
                transition_state(
                    sample_id=sample_id,
                    new_state='REVIEWED',
                    executor='conflict_resolution',
                )

            conn.commit()

            return {
                "status": "resolved",
                "annotation_id": annotation_id,
                "resolution": resolution,
                "sample_id": sample_id,
            }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/stats")
async def get_stats():
    """
    Get annotation statistics.

    Returns:
        Statistics dictionary.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            # Total annotations by status
            cur.execute(
                """
                SELECT status, COUNT(*) 
                FROM annotations 
                GROUP BY status
                """
            )
            status_counts = dict(cur.fetchall())

            # Annotations by task type
            cur.execute(
                """
                SELECT task_type, COUNT(*) 
                FROM annotations 
                GROUP BY task_type
                """
            )
            task_type_counts = dict(cur.fetchall())

            # Conflicts
            cur.execute(
                """
                SELECT COUNT(*) FROM annotations WHERE conflict_detected = TRUE
                """
            )
            conflict_count = cur.fetchone()[0]

            # Gold standard samples
            cur.execute(
                """
                SELECT COUNT(*) FROM samples WHERE is_gold_standard = TRUE
                """
            )
            gold_count = cur.fetchone()[0]

            return {
                "by_status": status_counts,
                "by_task_type": task_type_counts,
                "conflicts": conflict_count,
                "gold_standards": gold_count,
                "timestamp": datetime.now().isoformat(),
            }

    finally:
        conn.close()


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )

"""
Data utilities for the NLP pipeline.

Provides database connectivity (PostgreSQL) and helper functions
for data processing in the speech translation pipeline.

Schema Version: 2.0 (Multi-table design with revision tracking)
"""

import os
import re
import warnings
from typing import Optional, Dict, Any, List

import psycopg2
from psycopg2.extras import Json, RealDictCursor


# =============================================================================
# DATABASE CONNECTION
# =============================================================================

def get_pg_connection() -> psycopg2.extensions.connection:
    """
    Establishes a connection to the PostgreSQL database.

    Reads connection string from DATABASE_URL environment variable.
    Falls back to default Docker Compose credentials if not set.

    Returns:
        psycopg2 connection object.

    Raises:
        ConnectionError: If database connection fails.
    """
    database_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://admin:secret_password@localhost:5432/data_factory'
    )

    try:
        conn = psycopg2.connect(database_url)
        return conn
    except psycopg2.Error as e:
        raise ConnectionError(f"Error connecting to PostgreSQL: {e}")


# =============================================================================
# SOURCE OPERATIONS
# =============================================================================

def get_or_create_source(
    source_type: str,
    external_id: str,
    name: Optional[str] = None,
    url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get existing source or create new one.

    Args:
        source_type: Type of source ('youtube_with_transcript', 'youtube_without_transcript',
                     'substack', 'manual_upload').
        external_id: External identifier (YouTube channel ID, Substack slug).
        name: Human-readable name of the source.
        url: Base URL of the source.
        metadata: Additional metadata as JSONB.

    Returns:
        The UUID of the source.

    Raises:
        Exception: If operation fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT get_or_create_source(%s::source_type, %s, %s, %s, %s)",
                (source_type, external_id, name, url, Json(metadata or {}))
            )
            source_id = cur.fetchone()[0]
            conn.commit()
            return str(source_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to get/create source: {e}")
    finally:
        conn.close()


# =============================================================================
# SAMPLE OPERATIONS
# =============================================================================

def insert_sample(
    content_type: str,
    pipeline_type: str,
    audio_file_path: Optional[str] = None,
    text_file_path: Optional[str] = None,
    external_id: Optional[str] = None,
    source_id: Optional[str] = None,
    parent_sample_id: Optional[str] = None,
    segment_index: Optional[int] = None,
    start_time_ms: Optional[int] = None,
    end_time_ms: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    cs_ratio: Optional[float] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
    acoustic_metadata: Optional[Dict[str, Any]] = None,
    linguistic_metadata: Optional[Dict[str, Any]] = None,
    priority: int = 0
) -> str:
    """
    Insert a new sample into the samples table.

    Args:
        content_type: 'audio_primary' or 'text_primary'.
        pipeline_type: Pipeline this sample follows.
        audio_file_path: Path to audio file (relative to project root).
        text_file_path: Path to text file (relative to project root).
        external_id: External identifier (video ID, article slug).
        source_id: UUID of the parent source.
        parent_sample_id: UUID of parent sample (for segments).
        segment_index: Index within parent (0-based).
        start_time_ms: Segment start time in milliseconds.
        end_time_ms: Segment end time in milliseconds.
        duration_seconds: Duration in seconds.
        cs_ratio: Code-switching ratio (0.0 to 1.0).
        source_metadata: Source-related metadata.
        acoustic_metadata: Audio properties metadata.
        linguistic_metadata: Language/speaker metadata.
        priority: Processing priority (higher = more urgent).

    Returns:
        The UUID of the inserted sample.

    Raises:
        ValueError: If neither audio_file_path nor text_file_path is provided.
        Exception: If insert fails.
    """
    if audio_file_path is None and text_file_path is None:
        raise ValueError(
            "At least one of audio_file_path or text_file_path must be provided"
        )

    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO samples (
                    content_type,
                    pipeline_type,
                    audio_file_path,
                    text_file_path,
                    external_id,
                    source_id,
                    parent_sample_id,
                    segment_index,
                    start_time_ms,
                    end_time_ms,
                    duration_seconds,
                    cs_ratio,
                    source_metadata,
                    acoustic_metadata,
                    linguistic_metadata,
                    priority,
                    processing_state
                ) VALUES (
                    %s::content_type,
                    %s::source_type,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    'RAW'::processing_state
                )
                RETURNING sample_id
                """,
                (
                    content_type,
                    pipeline_type,
                    audio_file_path,
                    text_file_path,
                    external_id,
                    source_id,
                    parent_sample_id,
                    segment_index,
                    start_time_ms,
                    end_time_ms,
                    duration_seconds,
                    cs_ratio,
                    Json(source_metadata or {}),
                    Json(acoustic_metadata or {}),
                    Json(linguistic_metadata or {}),
                    priority
                )
            )
            sample_id = cur.fetchone()[0]
            conn.commit()
            return str(sample_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert sample: {e}")
    finally:
        conn.close()


def sample_exists(
    audio_file_path: Optional[str] = None,
    text_file_path: Optional[str] = None,
    external_id: Optional[str] = None
) -> bool:
    """
    Check if a sample with the given file path or external_id already exists.

    Args:
        audio_file_path: Audio file path to check.
        text_file_path: Text file path to check.
        external_id: External ID to check.

    Returns:
        True if sample exists, False otherwise.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            conditions = []
            params = []

            if audio_file_path:
                conditions.append("audio_file_path = %s")
                params.append(audio_file_path)
            if text_file_path:
                conditions.append("text_file_path = %s")
                params.append(text_file_path)
            if external_id:
                conditions.append("external_id = %s")
                params.append(external_id)

            if not conditions:
                return False

            query = (
                f"SELECT 1 FROM samples WHERE ({' OR '.join(conditions)}) "
                "AND is_deleted = FALSE LIMIT 1"
            )
            cur.execute(query, params)
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a sample by its ID.

    Args:
        sample_id: UUID of the sample.

    Returns:
        Sample data as dictionary, or None if not found.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM v_sample_current_state WHERE sample_id = %s",
                (sample_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else None
    finally:
        conn.close()


def transition_state(
    sample_id: str,
    new_state: str,
    executor: str = "system"
) -> bool:
    """
    Transition a sample to a new processing state.

    Args:
        sample_id: UUID of the sample.
        new_state: New processing state.
        executor: Who/what initiated the transition.

    Returns:
        True if successful.

    Raises:
        Exception: If transition fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT transition_sample_state(%s, %s::processing_state, %s)",
                (sample_id, new_state, executor)
            )
            result = cur.fetchone()[0]
            conn.commit()
            return result
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to transition state: {e}")
    finally:
        conn.close()


# =============================================================================
# TRANSCRIPT OPERATIONS
# =============================================================================

def insert_transcript_revision(
    sample_id: str,
    transcript_text: str,
    revision_type: str,
    revision_source: Optional[str] = None,
    timestamps: Optional[List[Dict[str, Any]]] = None,
    created_by: str = "system"
) -> str:
    """
    Insert a new transcript revision.

    Args:
        sample_id: UUID of the sample.
        transcript_text: The transcript content.
        revision_type: Type of revision ('raw', 'asr_generated',
                       'human_corrected', 'mfa_aligned').
        revision_source: Source of revision ('youtube_api', 'whisper',
                         'annotator_123').
        timestamps: List of timestamp objects [{start_ms, end_ms, text}, ...].
        created_by: User/system that created this revision.

    Returns:
        The UUID of the inserted revision.

    Raises:
        Exception: If insert fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT add_transcript_revision(%s, %s, %s, %s, %s, %s)",
                (
                    sample_id,
                    transcript_text,
                    revision_type,
                    revision_source,
                    Json(timestamps) if timestamps else None,
                    created_by
                )
            )
            revision_id = cur.fetchone()[0]
            conn.commit()
            return str(revision_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert transcript revision: {e}")
    finally:
        conn.close()


def get_latest_transcript(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest transcript revision for a sample.

    Args:
        sample_id: UUID of the sample.

    Returns:
        Transcript revision data as dictionary, or None if not found.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM transcript_revisions
                WHERE sample_id = %s
                ORDER BY version DESC
                LIMIT 1
                """,
                (sample_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else None
    finally:
        conn.close()


# =============================================================================
# TRANSLATION OPERATIONS
# =============================================================================

def insert_translation_revision(
    sample_id: str,
    translation_text: str,
    target_language: str,
    revision_type: str,
    source_transcript_revision_id: Optional[str] = None,
    revision_source: Optional[str] = None,
    confidence_score: Optional[float] = None,
    created_by: str = "system"
) -> str:
    """
    Insert a new translation revision.

    Args:
        sample_id: UUID of the sample.
        translation_text: The translation content.
        target_language: Target language code ('vi' for Vietnamese).
        revision_type: Type of revision ('llm_generated', 'human_corrected',
                       'final').
        source_transcript_revision_id: UUID of source transcript revision.
        revision_source: Source of revision ('gpt-4', 'annotator_456').
        confidence_score: Confidence score (0.0 to 1.0).
        created_by: User/system that created this revision.

    Returns:
        The UUID of the inserted revision.

    Raises:
        Exception: If insert fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT add_translation_revision(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    sample_id,
                    translation_text,
                    target_language,
                    revision_type,
                    source_transcript_revision_id,
                    revision_source,
                    confidence_score,
                    created_by
                )
            )
            revision_id = cur.fetchone()[0]
            conn.commit()
            return str(revision_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert translation revision: {e}")
    finally:
        conn.close()


def get_latest_translation(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest translation revision for a sample.

    Args:
        sample_id: UUID of the sample.

    Returns:
        Translation revision data as dictionary, or None if not found.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM translation_revisions
                WHERE sample_id = %s
                ORDER BY version DESC
                LIMIT 1
                """,
                (sample_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else None
    finally:
        conn.close()


# =============================================================================
# REVIEW QUEUE OPERATIONS
# =============================================================================

def get_review_queue(
    task_type: Optional[str] = None,
    pipeline_type: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get samples from the review queue.

    Args:
        task_type: Filter by task type ('transcript_verification',
                   'timestamp_alignment', 'translation_review',
                   'quality_assessment').
        pipeline_type: Filter by pipeline type.
        limit: Maximum number of results.

    Returns:
        List of sample dictionaries ordered by priority.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params = []

            if task_type:
                conditions.append("suggested_task_type = %s::annotation_task")
                params.append(task_type)
            if pipeline_type:
                conditions.append("pipeline_type = %s::source_type")
                params.append(pipeline_type)

            where_clause = (
                f"WHERE {' AND '.join(conditions)}" if conditions else ""
            )
            params.append(limit)

            cur.execute(
                f"""
                SELECT * FROM v_review_queue
                {where_clause}
                LIMIT %s
                """,
                params
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_pipeline_stats() -> List[Dict[str, Any]]:
    """
    Get pipeline statistics.

    Returns:
        List of statistics grouped by pipeline_type and processing_state.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM v_pipeline_stats")
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# =============================================================================
# LINEAGE OPERATIONS
# =============================================================================

def insert_lineage(
    ancestor_sample_id: str,
    descendant_sample_id: str,
    derivation_type: str,
    derivation_step: int = 1,
    processing_params: Optional[Dict[str, Any]] = None
) -> str:
    """
    Insert a lineage relationship between samples.

    Args:
        ancestor_sample_id: UUID of the ancestor (source) sample.
        descendant_sample_id: UUID of the descendant (derived) sample.
        derivation_type: Type of derivation ('segmentation', 'enhancement',
                         'tts_generation').
        derivation_step: Distance in derivation chain (1 = direct).
        processing_params: Parameters used for derivation.

    Returns:
        The UUID of the inserted lineage record.

    Raises:
        Exception: If insert fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sample_lineage (
                    ancestor_sample_id,
                    descendant_sample_id,
                    derivation_type,
                    derivation_step,
                    processing_params
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING lineage_id
                """,
                (
                    ancestor_sample_id,
                    descendant_sample_id,
                    derivation_type,
                    derivation_step,
                    Json(processing_params or {})
                )
            )
            lineage_id = cur.fetchone()[0]
            conn.commit()
            return str(lineage_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert lineage: {e}")
    finally:
        conn.close()


def get_sample_lineage(sample_id: str) -> List[Dict[str, Any]]:
    """
    Get the full lineage chain for a sample.

    Args:
        sample_id: UUID of the sample.

    Returns:
        List of ancestor samples in order of derivation.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM get_sample_lineage(%s)", (sample_id,))
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# =============================================================================
# ANNOTATION OPERATIONS
# =============================================================================

def insert_annotation(
    sample_id: str,
    task_type: str,
    label_studio_project_id: Optional[int] = None,
    label_studio_task_id: Optional[int] = None,
    assigned_to: Optional[str] = None
) -> str:
    """
    Insert a new annotation task.

    Args:
        sample_id: UUID of the sample.
        task_type: Type of task ('transcript_verification', 'timestamp_alignment',
                   'translation_review', 'quality_assessment').
        label_studio_project_id: Label Studio project ID.
        label_studio_task_id: Label Studio task ID.
        assigned_to: Annotator user ID.

    Returns:
        The UUID of the inserted annotation.

    Raises:
        Exception: If insert fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO annotations (
                    sample_id,
                    task_type,
                    label_studio_project_id,
                    label_studio_task_id,
                    assigned_to,
                    assigned_at
                ) VALUES (
                    %s, %s::annotation_task, %s, %s, %s,
                    CASE WHEN %s IS NOT NULL THEN NOW() ELSE NULL END
                )
                RETURNING annotation_id
                """,
                (
                    sample_id,
                    task_type,
                    label_studio_project_id,
                    label_studio_task_id,
                    assigned_to,
                    assigned_to
                )
            )
            annotation_id = cur.fetchone()[0]
            conn.commit()
            return str(annotation_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert annotation: {e}")
    finally:
        conn.close()


def update_annotation_status(
    annotation_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    time_spent_seconds: Optional[int] = None,
    confidence_score: Optional[float] = None
) -> bool:
    """
    Update an annotation's status and result.

    Args:
        annotation_id: UUID of the annotation.
        status: New status ('pending', 'in_progress', 'completed', 'skipped',
                'disputed').
        result: Annotation result data.
        time_spent_seconds: Time spent on annotation.
        confidence_score: Annotator confidence.

    Returns:
        True if successful.

    Raises:
        Exception: If update fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE annotations SET
                    status = %s::annotation_status,
                    result = COALESCE(%s, result),
                    time_spent_seconds = COALESCE(%s, time_spent_seconds),
                    confidence_score = COALESCE(%s, confidence_score),
                    completed_at = CASE
                        WHEN %s = 'completed' THEN NOW()
                        ELSE completed_at
                    END
                WHERE annotation_id = %s
                """,
                (
                    status,
                    Json(result) if result else None,
                    time_spent_seconds,
                    confidence_score,
                    status,
                    annotation_id
                )
            )
            conn.commit()
            return True
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to update annotation: {e}")
    finally:
        conn.close()


# =============================================================================
# LOGGING OPERATIONS
# =============================================================================

def log_processing(
    operation: str,
    success: bool,
    sample_id: Optional[str] = None,
    previous_state: Optional[str] = None,
    new_state: Optional[str] = None,
    executor: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
    input_params: Optional[Dict[str, Any]] = None,
    output_summary: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> str:
    """
    Log a processing operation.

    Args:
        operation: Operation name ('state_transition', 'enhancement',
                   'segmentation').
        success: Whether the operation succeeded.
        sample_id: UUID of the sample (optional).
        previous_state: Previous processing state.
        new_state: New processing state.
        executor: Who/what executed the operation.
        execution_time_ms: Execution time in milliseconds.
        input_params: Input parameters.
        output_summary: Output summary.
        error_message: Error message if failed.

    Returns:
        The UUID of the log entry.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO processing_logs (
                    sample_id, operation, previous_state, new_state,
                    executor, execution_time_ms, input_params,
                    output_summary, error_message, success
                ) VALUES (
                    %s, %s,
                    %s::processing_state, %s::processing_state,
                    %s, %s, %s, %s, %s, %s
                )
                RETURNING log_id
                """,
                (
                    sample_id, operation, previous_state, new_state,
                    executor, execution_time_ms,
                    Json(input_params) if input_params else None,
                    Json(output_summary) if output_summary else None,
                    error_message, success
                )
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return str(log_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to log processing: {e}")
    finally:
        conn.close()


# =============================================================================
# LINGUISTIC ANALYSIS
# =============================================================================

def calculate_cs_ratio(text: str) -> float:
    """
    Crudely estimates the ratio of English words in a Vietnamese-English sentence.

    Logic:
    - Tokenizes text by whitespace.
    - Identifies Vietnamese words by the presence of Vietnamese diacritics.
    - Treats everything else as potentially English.

    Args:
        text: The code-switched input text.

    Returns:
        Percentage of English words (0.0 to 1.0).
    """
    if not text or not text.strip():
        return 0.0

    # Regex for Vietnamese specific characters (including lower and upper case)
    vn_chars_pattern = re.compile(
        r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ'
        r'òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]',
        re.IGNORECASE
    )

    words = text.strip().split()
    total_words = len(words)

    if total_words == 0:
        return 0.0

    english_like_count = 0

    for word in words:
        # Remove punctuation for cleaner check
        clean_word = re.sub(r'[^\w\s]', '', word)

        # Skip if the word became empty after removing punctuation
        if not clean_word:
            total_words -= 1
            continue

        # If it contains Vietnamese characters, it's Vietnamese.
        # If it doesn't, we count it as English (per crude heuristic).
        if not vn_chars_pattern.search(clean_word):
            english_like_count += 1

    if total_words == 0:
        return 0.0

    return round(english_like_count / total_words, 4)


# =============================================================================
# LEGACY COMPATIBILITY (Deprecated - to be removed in future versions)
# =============================================================================

def insert_raw_sample(
    file_path: str,
    source_metadata: Dict[str, Any],
    acoustic_meta: Dict[str, Any],
    linguistic_meta: Optional[Dict[str, Any]] = None,
    transcript_raw: Optional[str] = None
) -> str:
    """
    DEPRECATED: Use insert_sample() instead.

    Legacy function for backwards compatibility with old ingestion scripts.
    """
    warnings.warn(
        "insert_raw_sample is deprecated. Use insert_sample() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    # Determine pipeline type based on subtitle availability
    has_transcript = transcript_raw is not None
    pipeline_type = (
        'youtube_with_transcript' if has_transcript
        else 'youtube_without_transcript'
    )

    # Insert sample
    sample_id = insert_sample(
        content_type='audio_primary',
        pipeline_type=pipeline_type,
        audio_file_path=file_path,
        external_id=source_metadata.get('channel_id'),
        duration_seconds=acoustic_meta.get('duration'),
        cs_ratio=linguistic_meta.get('cs_ratio') if linguistic_meta else None,
        source_metadata=source_metadata,
        acoustic_metadata=acoustic_meta,
        linguistic_metadata=linguistic_meta or {}
    )

    # Insert transcript revision if available
    if transcript_raw:
        insert_transcript_revision(
            sample_id=sample_id,
            transcript_text=transcript_raw,
            revision_type='raw',
            revision_source='youtube_api'
        )

    return sample_id

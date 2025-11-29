"""
Data utilities v3 for the NLP pipeline.

Provides database connectivity (PostgreSQL) and helper functions
for data processing in the simplified YouTube-only speech translation pipeline.

Schema Version: 3.0 (Simplified pipeline with segments and translations)

Changes from v2:
- Removed Substack/TTS pipeline support
- Added subtitle_type tracking (manual vs auto-generated)
- Added segment operations
- Added segment_translation operations
- Updated source_type enum values
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
        source_type: Type of source ('youtube_manual_transcript',
                     'youtube_auto_transcript', 'manual_upload').
        external_id: External identifier (YouTube channel ID).
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
# SAMPLE OPERATIONS (V3)
# =============================================================================

def insert_sample(
    audio_file_path: str,
    external_id: str,
    subtitle_type: str,
    pipeline_type: str,
    source_id: Optional[str] = None,
    text_file_path: Optional[str] = None,
    subtitle_language: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    cs_ratio: Optional[float] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
    acoustic_metadata: Optional[Dict[str, Any]] = None,
    priority: int = 0
) -> str:
    """
    Insert a new sample into the samples table (v3 schema).

    Args:
        audio_file_path: Path to audio file (relative to project root).
        external_id: External identifier (video ID).
        subtitle_type: 'manual', 'auto_generated', or 'none'.
        pipeline_type: Pipeline this sample follows.
        source_id: UUID of the parent source.
        text_file_path: Path to text/transcript file.
        subtitle_language: Language code of the subtitle.
        duration_seconds: Duration in seconds.
        cs_ratio: Code-switching ratio (0.0 to 1.0).
        source_metadata: Source-related metadata.
        acoustic_metadata: Audio properties metadata.
        priority: Processing priority (higher = more urgent).

    Returns:
        The UUID of the inserted sample.

    Raises:
        ValueError: If audio_file_path is not provided.
        Exception: If insert fails.
    """
    if not audio_file_path:
        raise ValueError("audio_file_path must be provided")

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
                    subtitle_type,
                    subtitle_language,
                    duration_seconds,
                    cs_ratio,
                    source_metadata,
                    acoustic_metadata,
                    priority,
                    processing_state
                ) VALUES (
                    'audio_primary'::content_type,
                    %s::source_type,
                    %s, %s, %s, %s,
                    %s::subtitle_type,
                    %s, %s, %s,
                    %s, %s, %s,
                    'RAW'::processing_state
                )
                RETURNING sample_id
                """,
                (
                    pipeline_type,
                    audio_file_path,
                    text_file_path,
                    external_id,
                    source_id,
                    subtitle_type,
                    subtitle_language,
                    duration_seconds,
                    cs_ratio,
                    Json(source_metadata or {}),
                    Json(acoustic_metadata or {}),
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
    external_id: Optional[str] = None
) -> bool:
    """
    Check if a sample with the given file path or external_id already exists.

    Args:
        audio_file_path: Audio file path to check.
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
                "SELECT * FROM samples WHERE sample_id = %s AND is_deleted = FALSE",
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
# TRANSCRIPT OPERATIONS (V3)
# =============================================================================

def insert_transcript_revision(
    sample_id: str,
    transcript_text: str,
    revision_type: str,
    revision_source: Optional[str] = None,
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    sentence_timestamps: Optional[List[Dict[str, Any]]] = None,
    created_by: str = "system"
) -> str:
    """
    Insert a new transcript revision (v3 schema).

    Args:
        sample_id: UUID of the sample.
        transcript_text: The transcript content.
        revision_type: Type of revision ('youtube_raw', 'human_corrected',
                       'whisperx_aligned').
        revision_source: Source of revision ('youtube_api', 'annotator_email',
                         'whisperx').
        word_timestamps: Word-level timestamps from WhisperX.
        sentence_timestamps: Sentence-level timestamps.
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
                "SELECT add_transcript_revision(%s, %s, %s, %s, %s, %s, %s)",
                (
                    sample_id,
                    transcript_text,
                    revision_type,
                    revision_source,
                    Json(word_timestamps) if word_timestamps else None,
                    Json(sentence_timestamps) if sentence_timestamps else None,
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
# TRANSLATION OPERATIONS (V3)
# =============================================================================

def insert_translation_revision(
    sample_id: str,
    translation_text: str,
    revision_type: str,
    source_transcript_revision_id: Optional[str] = None,
    sentence_translations: Optional[List[Dict[str, Any]]] = None,
    revision_source: Optional[str] = None,
    api_model: Optional[str] = None,
    api_cost_usd: Optional[float] = None,
    created_by: str = "system"
) -> str:
    """
    Insert a new translation revision (v3 schema).

    Args:
        sample_id: UUID of the sample.
        translation_text: The translation content.
        revision_type: Type of revision ('gemini_draft', 'human_corrected',
                       'final').
        source_transcript_revision_id: UUID of source transcript revision.
        sentence_translations: Per-sentence translation mapping.
        revision_source: Source of revision ('gemini-1.5-flash').
        api_model: API model used.
        api_cost_usd: Estimated API cost.
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
                "SELECT add_translation_revision(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    sample_id,
                    translation_text,
                    revision_type,
                    source_transcript_revision_id,
                    Json(sentence_translations) if sentence_translations else None,
                    revision_source,
                    api_model,
                    api_cost_usd,
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
# SEGMENT OPERATIONS (V3 - NEW)
# =============================================================================

def get_segments(sample_id: str) -> List[Dict[str, Any]]:
    """
    Get all segments for a sample.

    Args:
        sample_id: UUID of the sample.

    Returns:
        List of segment dictionaries ordered by index.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM segments
                WHERE sample_id = %s
                ORDER BY segment_index
                """,
                (sample_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_segment(segment_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a segment by its ID.

    Args:
        segment_id: UUID of the segment.

    Returns:
        Segment data as dictionary, or None if not found.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM segments WHERE segment_id = %s",
                (segment_id,)
            )
            result = cur.fetchone()
            return dict(result) if result else None
    finally:
        conn.close()


def update_segment_verification(
    segment_id: str,
    is_verified: bool,
    has_issues: bool = False,
    issue_notes: Optional[str] = None
) -> bool:
    """
    Update segment verification status.

    Args:
        segment_id: UUID of the segment.
        is_verified: Whether the segment is verified.
        has_issues: Whether the segment has issues.
        issue_notes: Notes about issues.

    Returns:
        True if successful.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE segments
                SET is_verified = %s,
                    has_issues = %s,
                    issue_notes = %s,
                    updated_at = NOW()
                WHERE segment_id = %s
                """,
                (is_verified, has_issues, issue_notes, segment_id)
            )
            conn.commit()
            return True
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to update segment: {e}")
    finally:
        conn.close()


# =============================================================================
# PIPELINE STATS & QUEUE OPERATIONS
# =============================================================================

def get_pipeline_stats() -> List[Dict[str, Any]]:
    """
    Get pipeline statistics.

    Returns:
        List of statistics grouped by processing_state and subtitle_type.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM v_pipeline_stats")
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_samples_by_state(
    state: str,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get samples in a specific processing state.

    Args:
        state: Processing state to filter by.
        limit: Maximum number of results.

    Returns:
        List of sample dictionaries.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM v_sample_overview
                WHERE processing_state = %s::processing_state
                ORDER BY priority DESC, created_at ASC
                LIMIT %s
                """,
                (state, limit)
            )
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error:
        # View might not exist yet, fall back to direct query
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM samples
                WHERE processing_state = %s::processing_state
                  AND is_deleted = FALSE
                ORDER BY priority DESC, created_at ASC
                LIMIT %s
                """,
                (state, limit)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# =============================================================================
# LOGGING OPERATIONS
# =============================================================================

def log_processing(
    operation: str,
    success: bool,
    sample_id: Optional[str] = None,
    segment_id: Optional[str] = None,
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
        operation: Operation name ('state_transition', 'whisperx_alignment', etc.).
        success: Whether the operation succeeded.
        sample_id: UUID of the sample (optional).
        segment_id: UUID of the segment (optional).
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
                    sample_id, segment_id, operation, previous_state, new_state,
                    executor, execution_time_ms, input_params,
                    output_summary, error_message, success
                ) VALUES (
                    %s, %s, %s,
                    %s::processing_state, %s::processing_state,
                    %s, %s, %s, %s, %s, %s
                )
                RETURNING log_id
                """,
                (
                    sample_id, segment_id, operation, previous_state, new_state,
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
# ANNOTATION OPERATIONS (V3)
# =============================================================================

def insert_annotation(
    task_type: str,
    sample_id: Optional[str] = None,
    segment_id: Optional[str] = None,
    label_studio_project_id: Optional[int] = None,
    label_studio_task_id: Optional[int] = None,
    assigned_to: Optional[str] = None
) -> str:
    """
    Insert a new annotation task.

    Args:
        task_type: Type of task ('transcript_correction', 'segment_verification',
                   'translation_review').
        sample_id: UUID of the sample (for transcript correction).
        segment_id: UUID of the segment (for segment/translation review).
        label_studio_project_id: Label Studio project ID.
        label_studio_task_id: Label Studio task ID.
        assigned_to: Annotator user ID.

    Returns:
        The UUID of the inserted annotation.

    Raises:
        ValueError: If neither sample_id nor segment_id is provided.
        Exception: If insert fails.
    """
    if not sample_id and not segment_id:
        raise ValueError("Either sample_id or segment_id must be provided")

    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO annotations (
                    sample_id,
                    segment_id,
                    task_type,
                    label_studio_project_id,
                    label_studio_task_id,
                    assigned_to,
                    assigned_at
                ) VALUES (
                    %s, %s, %s::annotation_task, %s, %s, %s,
                    CASE WHEN %s IS NOT NULL THEN NOW() ELSE NULL END
                )
                RETURNING annotation_id
                """,
                (
                    sample_id,
                    segment_id,
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
    time_spent_seconds: Optional[int] = None
) -> bool:
    """
    Update an annotation's status and result.

    Args:
        annotation_id: UUID of the annotation.
        status: New status ('pending', 'in_progress', 'completed', 'skipped',
                'disputed').
        result: Annotation result data.
        time_spent_seconds: Time spent on annotation.

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
                    completed_at = CASE
                        WHEN %s = 'completed' THEN NOW()
                        ELSE completed_at
                    END,
                    updated_at = NOW()
                WHERE annotation_id = %s
                """,
                (
                    status,
                    Json(result) if result else None,
                    time_spent_seconds,
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
# LEGACY COMPATIBILITY (Deprecated)
# =============================================================================

def insert_raw_sample(*args, **kwargs):
    """DEPRECATED: Use insert_sample() instead."""
    warnings.warn(
        "insert_raw_sample is deprecated. Use insert_sample() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    raise NotImplementedError(
        "insert_raw_sample is no longer supported. Use insert_sample() with v3 schema."
    )

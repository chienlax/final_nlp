"""
SQLite Database Utilities.

Provides connection management, context managers, and helper functions
for the simplified NLP pipeline database.

Usage:
    from db import get_connection, get_db

    # Context manager (auto-commit/rollback)
    with get_db() as db:
        db.execute("INSERT INTO videos ...")

    # Direct connection (manual management)
    conn = get_connection()
    cursor = conn.cursor()
    ...
    conn.close()
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

# Configure logging
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "lab_data.db"
SCHEMA_PATH = PROJECT_ROOT / "init_scripts" / "sqlite_schema.sql"

# Constants
MAX_SEGMENT_DURATION_MS = 25000  # 25 seconds - warn if exceeded


def get_connection(
    db_path: Optional[Path] = None,
    read_only: bool = False
) -> sqlite3.Connection:
    """
    Get a SQLite connection with optimized settings.

    Args:
        db_path: Path to database file. Uses default if not provided.
        read_only: If True, open in read-only mode.

    Returns:
        sqlite3.Connection with WAL mode and row factory enabled.
    """
    path = db_path or DEFAULT_DB_PATH

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build connection URI
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)

    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    # Return rows as dictionaries
    conn.row_factory = sqlite3.Row

    return conn


@contextmanager
def get_db(
    db_path: Optional[Path] = None,
    read_only: bool = False
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for database connections.

    Automatically commits on success, rolls back on exception.

    Args:
        db_path: Path to database file.
        read_only: If True, open in read-only mode.

    Yields:
        sqlite3.Connection with auto-commit/rollback.

    Example:
        with get_db() as db:
            db.execute("INSERT INTO videos ...")
    """
    conn = get_connection(db_path, read_only)
    try:
        yield conn
        if not read_only:
            conn.commit()
    except Exception:
        if not read_only:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_database(db_path: Optional[Path] = None) -> None:
    """
    Initialize the database with schema.

    Creates tables, indexes, triggers, and views from sqlite_schema.sql.

    Args:
        db_path: Path to database file.
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with get_db(db_path) as db:
        # Temporarily disable FK constraints during schema creation
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(schema_sql)
        db.execute("PRAGMA foreign_keys = ON")
        logger.info(f"Database initialized: {db_path or DEFAULT_DB_PATH}")


def ensure_schema_upgrades(db_path: Optional[Path] = None) -> None:
    """Apply additive schema updates for reviewer/chunks without data loss."""
    with get_db(db_path) as db:
        # Add reviewer column if missing
        cols = {row[1] for row in db.execute("PRAGMA table_info(videos)").fetchall()}
        if "reviewer" not in cols:
            db.execute("ALTER TABLE videos ADD COLUMN reviewer TEXT")

        # Add chunk_id to segments if missing
        seg_cols = {row[1] for row in db.execute("PRAGMA table_info(segments)").fetchall()}
        if "chunk_id" not in seg_cols:
            db.execute("ALTER TABLE segments ADD COLUMN chunk_id INTEGER")

        # Create chunks table if absent
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                audio_path TEXT NOT NULL,
                processing_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (processing_state IN ('pending', 'transcribed', 'reviewed', 'exported', 'rejected')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(video_id, chunk_index)
            );
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id);")
        db.execute("CREATE INDEX IF NOT EXISTS idx_segments_chunk ON segments(chunk_id);")


# =============================================================================
# VIDEO OPERATIONS
# =============================================================================

def insert_video(
    video_id: str,
    title: str,
    duration_seconds: float,
    audio_path: str,
    url: Optional[str] = None,
    channel_name: Optional[str] = None,
    reviewer: Optional[str] = None,
    source_type: str = "youtube",
    upload_metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None
) -> str:
    """
    Insert a new video record.

    Args:
        video_id: Unique video identifier (YouTube ID or custom).
        title: Video title.
        duration_seconds: Total audio duration.
        audio_path: Relative path to audio file.
        url: Source URL (optional for uploads).
        channel_name: Channel or uploader name.
        source_type: 'youtube' or 'upload'.
        upload_metadata: Additional metadata for uploads.
        db_path: Database path.

    Returns:
        The video_id.
    """
    with get_db(db_path) as db:
        db.execute(
            """
            INSERT INTO videos (
                video_id, url, title, channel_name, reviewer, duration_seconds,
                audio_path, source_type, upload_metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                url,
                title,
                channel_name,
                reviewer,
                duration_seconds,
                audio_path,
                source_type,
                json.dumps(upload_metadata) if upload_metadata else None,
            )
        )
        logger.info(f"Inserted video: {video_id} - {title}")
        return video_id


def get_video(
    video_id: str,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """
    Get a video by ID.

    Args:
        video_id: Video identifier.
        db_path: Database path.

    Returns:
        Video record as dict, or None if not found.
    """
    with get_db(db_path, read_only=True) as db:
        cursor = db.execute(
            "SELECT * FROM videos WHERE video_id = ?",
            (video_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_videos_by_state(
    state: str,
    limit: Optional[int] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Get videos by processing state.

    Args:
        state: Processing state ('pending', 'transcribed', 'reviewed', 'exported').
        limit: Maximum number of results.
        db_path: Database path.

    Returns:
        List of video records.
    """
    with get_db(db_path, read_only=True) as db:
        query = "SELECT * FROM videos WHERE processing_state = ? ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {limit}"

        cursor = db.execute(query, (state,))
        return [dict(row) for row in cursor.fetchall()]


def update_video_state(
    video_id: str,
    new_state: str,
    db_path: Optional[Path] = None
) -> None:
    """
    Update a video's processing state.

    Args:
        video_id: Video identifier.
        new_state: New processing state.
        db_path: Database path.
    """
    with get_db(db_path) as db:
        db.execute(
            "UPDATE videos SET processing_state = ? WHERE video_id = ?",
            (new_state, video_id)
        )
        logger.info(f"Updated video {video_id} state to: {new_state}")


# =============================================================================
# CHUNK OPERATIONS
# =============================================================================

def insert_chunk(
    video_id: str,
    chunk_index: int,
    start_ms: int,
    end_ms: int,
    audio_path: str,
    processing_state: str = "pending",
    db_path: Optional[Path] = None,
) -> int:
    """Insert a chunk record and return its id."""
    with get_db(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO chunks (
                video_id, chunk_index, start_ms, end_ms, audio_path, processing_state
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video_id, chunk_index, start_ms, end_ms, audio_path, processing_state)
        )
        return cursor.lastrowid


def get_chunks_by_video(
    video_id: str,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    with get_db(db_path, read_only=True) as db:
        cursor = db.execute(
            """
            SELECT chunk_id, video_id, chunk_index, start_ms, end_ms, audio_path, processing_state
            FROM chunks
            WHERE video_id = ?
            ORDER BY chunk_index ASC
            """,
            (video_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def update_chunk_state(
    chunk_id: int,
    new_state: str,
    db_path: Optional[Path] = None
) -> None:
    with get_db(db_path) as db:
        db.execute(
            "UPDATE chunks SET processing_state = ? WHERE chunk_id = ?",
            (new_state, chunk_id)
        )


def aggregate_chunk_state(
    video_id: str,
    db_path: Optional[Path] = None
) -> Optional[str]:
    """Return a consensus state if all chunks match; otherwise None."""
    chunks = get_chunks_by_video(video_id, db_path=db_path)
    if not chunks:
        return None
    states = {c.get("processing_state") for c in chunks}
    return states.pop() if len(states) == 1 else None


def get_chunk(
    chunk_id: int,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    with get_db(db_path, read_only=True) as db:
        cursor = db.execute(
            """
            SELECT chunk_id, video_id, chunk_index, start_ms, end_ms, audio_path, processing_state
            FROM chunks WHERE chunk_id = ?
            """,
            (chunk_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def update_video_reviewer(
    video_id: str,
    reviewer: Optional[str],
    db_path: Optional[Path] = None
) -> None:
    """Assign or clear reviewer for a video."""
    with get_db(db_path) as db:
        db.execute(
            "UPDATE videos SET reviewer = ? WHERE video_id = ?",
            (reviewer, video_id)
        )
        logger.info("Updated reviewer for %s -> %s", video_id, reviewer)


def update_video_denoised_path(
    video_id: str,
    denoised_path: str,
    db_path: Optional[Path] = None
) -> None:
    """
    Update a video's denoised audio path.

    Args:
        video_id: Video identifier.
        denoised_path: Path to denoised audio file.
        db_path: Database path.
    """
    with get_db(db_path) as db:
        db.execute(
            "UPDATE videos SET denoised_audio_path = ? WHERE video_id = ?",
            (denoised_path, video_id)
        )
        logger.info(f"Updated denoised path for {video_id}")


# =============================================================================
# SEGMENT OPERATIONS
# =============================================================================

def insert_segments(
    video_id: str,
    segments: List[Dict[str, Any]],
    chunk_id: Optional[int] = None,
    db_path: Optional[Path] = None
) -> int:
    """
    Insert multiple segments for a video.

    Each segment dict should have: text, start, end, translation.
    Duration is computed automatically (not stored).

    Args:
        video_id: Video identifier.
        segments: List of segment dictionaries from Gemini output.
        db_path: Database path.

    Returns:
        Number of segments inserted.
    """
    with get_db(db_path) as db:
        # Clear existing segments for this video
        if chunk_id is None:
            db.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        else:
            db.execute(
                "DELETE FROM segments WHERE video_id = ? AND chunk_id = ?",
                (video_id, chunk_id)
            )

        # Insert new segments
        inserted = 0

        for idx, seg in enumerate(segments):
            # Convert seconds to milliseconds
            start_ms = int(seg["start"] * 1000)
            end_ms = int(seg["end"] * 1000)

            # Skip invalid timestamps (end must be strictly greater than start)
            if end_ms <= start_ms or start_ms < 0:
                logger.warning(
                    "[SKIP] Invalid segment timestamps for video %s idx %s: start_ms=%s end_ms=%s",
                    video_id, idx, start_ms, end_ms
                )
                continue

            db.execute(
                """
                INSERT INTO segments (
                    video_id, chunk_id, segment_index, start_ms, end_ms,
                    transcript, translation
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    chunk_id,
                    idx,
                    start_ms,
                    end_ms,
                    seg["text"],
                    seg["translation"],
                )
            )

            inserted += 1

        logger.info(f"Inserted {inserted} segments for video {video_id}")
        return inserted


def get_segments(
    video_id: str,
    chunk_id: Optional[int] = None,
    include_rejected: bool = False,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Get all segments for a video.

    Args:
        video_id: Video identifier.
        include_rejected: Include rejected segments.
        db_path: Database path.

    Returns:
        List of segment records.
    """
    with get_db(db_path, read_only=True) as db:
        query = """
            SELECT 
                segment_id,
                video_id,
                segment_index,
                start_ms,
                end_ms,
                (end_ms - start_ms) AS duration_ms,
                transcript,
                translation,
                reviewed_transcript,
                reviewed_translation,
                reviewed_start_ms,
                reviewed_end_ms,
                is_reviewed,
                is_rejected,
                reviewer_notes
            FROM segments 
            WHERE video_id = ?
        """
        params: List[Any] = [video_id]
        if chunk_id is not None:
            query += " AND (chunk_id = ? OR chunk_id IS NULL)"
            params.append(chunk_id)
        if not include_rejected:
            query += " AND is_rejected = 0"
        query += " ORDER BY segment_index ASC"

        cursor = db.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def get_segment(
    segment_id: int,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """
    Get a single segment by ID.

    Args:
        segment_id: Segment identifier.
        db_path: Database path.

    Returns:
        Segment record as dict, or None if not found.
    """
    with get_db(db_path, read_only=True) as db:
        cursor = db.execute(
            """
            SELECT 
                segment_id,
                video_id,
                segment_index,
                start_ms,
                end_ms,
                (end_ms - start_ms) AS duration_ms,
                transcript,
                translation,
                reviewed_transcript,
                reviewed_translation,
                reviewed_start_ms,
                reviewed_end_ms,
                is_reviewed,
                is_rejected,
                reviewer_notes
            FROM segments 
            WHERE segment_id = ?
            """,
            (segment_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def update_segment_review(
    segment_id: int,
    reviewed_transcript: Optional[str] = None,
    reviewed_translation: Optional[str] = None,
    reviewed_start_ms: Optional[int] = None,
    reviewed_end_ms: Optional[int] = None,
    is_rejected: bool = False,
    reviewer_notes: Optional[str] = None,
    db_path: Optional[Path] = None
) -> None:
    """
    Update a segment with review data.

    Args:
        segment_id: Segment identifier.
        reviewed_transcript: Corrected transcript.
        reviewed_translation: Corrected translation.
        reviewed_start_ms: Corrected start time.
        reviewed_end_ms: Corrected end time.
        is_rejected: Mark as rejected.
        reviewer_notes: Optional notes.
        db_path: Database path.
    """
    with get_db(db_path) as db:
        db.execute(
            """
            UPDATE segments SET
                reviewed_transcript = ?,
                reviewed_translation = ?,
                reviewed_start_ms = ?,
                reviewed_end_ms = ?,
                is_reviewed = 1,
                is_rejected = ?,
                reviewer_notes = ?,
                reviewed_at = datetime('now')
            WHERE segment_id = ?
            """,
            (
                reviewed_transcript,
                reviewed_translation,
                reviewed_start_ms,
                reviewed_end_ms,
                is_rejected,
                reviewer_notes,
                segment_id,
            )
        )
        logger.debug(f"Updated segment {segment_id} review")


def reject_segment(
    segment_id: int,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None
) -> None:
    """
    Mark a segment as rejected.

    Args:
        segment_id: Segment identifier.
        notes: Reason for rejection.
        db_path: Database path.
    """
    with get_db(db_path) as db:
        db.execute(
            """
            UPDATE segments SET
                is_reviewed = 1,
                is_rejected = 1,
                reviewer_notes = ?,
                reviewed_at = datetime('now')
            WHERE segment_id = ?
            """,
            (notes, segment_id)
        )
        logger.info(f"Rejected segment {segment_id}")


def split_segment(
    segment_id: int,
    split_time_ms: int,
    transcript_first: str,
    transcript_second: str,
    translation_first: str,
    translation_second: str,
    db_path: Optional[Path] = None
) -> tuple:
    """
    Split a segment into two at the specified time.

    Args:
        segment_id: Segment to split.
        split_time_ms: Time to split at (becomes end of first, start of second).
        transcript_first: Transcript for first segment.
        transcript_second: Transcript for second segment.
        translation_first: Translation for first segment.
        translation_second: Translation for second segment.
        db_path: Database path.

    Returns:
        Tuple of (first_segment_id, second_segment_id).
    """
    with get_db(db_path) as db:
        # Get original segment
        cursor = db.execute(
            "SELECT * FROM segments WHERE segment_id = ?",
            (segment_id,)
        )
        original = dict(cursor.fetchone())

        video_id = original["video_id"]
        original_index = original["segment_index"]
        start_ms = original["start_ms"]
        end_ms = original["end_ms"]

        # Validate split time
        if not (start_ms < split_time_ms < end_ms):
            raise ValueError(
                f"Split time {split_time_ms}ms must be between "
                f"{start_ms}ms and {end_ms}ms"
            )

        # Shift all subsequent segments up by 1
        db.execute(
            """
            UPDATE segments 
            SET segment_index = segment_index + 1
            WHERE video_id = ? AND segment_index > ?
            """,
            (video_id, original_index)
        )

        # Update original segment (becomes first half)
        db.execute(
            """
            UPDATE segments SET
                end_ms = ?,
                transcript = ?,
                translation = ?,
                reviewed_transcript = NULL,
                reviewed_translation = NULL,
                reviewed_start_ms = NULL,
                reviewed_end_ms = NULL,
                is_reviewed = 0,
                is_rejected = 0,
                reviewer_notes = 'Split from original'
            WHERE segment_id = ?
            """,
            (split_time_ms, transcript_first, translation_first, segment_id)
        )

        # Insert second half
        cursor = db.execute(
            """
            INSERT INTO segments (
                video_id, segment_index, start_ms, end_ms,
                transcript, translation, reviewer_notes
            ) VALUES (?, ?, ?, ?, ?, ?, 'Split from original')
            """,
            (
                video_id,
                original_index + 1,
                split_time_ms,
                end_ms,
                transcript_second,
                translation_second,
            )
        )
        second_id = cursor.lastrowid

        logger.info(f"Split segment {segment_id} at {split_time_ms}ms -> {segment_id}, {second_id}")
        return segment_id, second_id


# =============================================================================
# STATISTICS & QUERIES
# =============================================================================

def get_video_progress(
    video_id: str,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Get review progress for a video.

    Args:
        video_id: Video identifier.
        db_path: Database path.

    Returns:
        Progress statistics dict.
    """
    with get_db(db_path, read_only=True) as db:
        cursor = db.execute(
            "SELECT * FROM v_video_progress WHERE video_id = ?",
            (video_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_long_segments(
    video_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Get segments exceeding 25 seconds.

    Args:
        video_id: Filter by video (optional).
        db_path: Database path.

    Returns:
        List of long segment records.
    """
    with get_db(db_path, read_only=True) as db:
        query = "SELECT * FROM v_long_segments"
        params: tuple = ()

        if video_id:
            query += " WHERE video_id = ?"
            params = (video_id,)

        query += " ORDER BY duration_seconds DESC"

        cursor = db.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_export_ready_segments(
    video_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Get segments ready for export (reviewed, not rejected).

    Args:
        video_id: Filter by video (optional).
        db_path: Database path.

    Returns:
        List of export-ready segment records.
    """
    with get_db(db_path, read_only=True) as db:
        query = "SELECT * FROM v_export_ready"
        params: tuple = ()

        if video_id:
            query += " WHERE video_id = ?"
            params = (video_id,)

        query += " ORDER BY video_id, segment_index"

        cursor = db.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_database_stats(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Get overall database statistics.

    Args:
        db_path: Database path.

    Returns:
        Statistics dict.
    """
    with get_db(db_path, read_only=True) as db:
        stats: Dict[str, Any] = {}

        # Video counts by state
        cursor = db.execute(
            """
            SELECT processing_state, COUNT(*) as count
            FROM videos
            GROUP BY processing_state
            """
        )
        stats["videos_by_state"] = {row["processing_state"]: row["count"] for row in cursor}

        # Total videos
        cursor = db.execute("SELECT COUNT(*) as count FROM videos")
        stats["total_videos"] = cursor.fetchone()["count"]

        # Total segments
        cursor = db.execute("SELECT COUNT(*) as count FROM segments")
        stats["total_segments"] = cursor.fetchone()["count"]

        # Reviewed segments
        cursor = db.execute(
            "SELECT COUNT(*) as count FROM segments WHERE is_reviewed = 1"
        )
        stats["reviewed_segments"] = cursor.fetchone()["count"]

        # Rejected segments
        cursor = db.execute(
            "SELECT COUNT(*) as count FROM segments WHERE is_rejected = 1"
        )
        stats["rejected_segments"] = cursor.fetchone()["count"]

        # Total duration (hours)
        cursor = db.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) / 3600.0 as hours FROM videos"
        )
        stats["total_hours"] = round(cursor.fetchone()["hours"], 2)

        # Long segments count
        cursor = db.execute("SELECT COUNT(*) as count FROM v_long_segments")
        stats["long_segments"] = cursor.fetchone()["count"]

        return stats


# =============================================================================
# JSON VALIDATION (for uploads)
# =============================================================================

def validate_transcript_json(data: Union[Dict, List]) -> tuple:
    """
    Validate transcript JSON against expected schema.

    Expected format (without duration - computed on import):
    [
        {"text": "...", "start": 0.0, "end": 4.2, "translation": "..."},
        ...
    ]

    Or wrapped:
    {"sentences": [...]}

    Args:
        data: Parsed JSON data.

    Returns:
        Tuple of (is_valid, list of error messages).
    """
    errors: List[str] = []

    # Handle both wrapped and flat formats
    if isinstance(data, dict):
        if "sentences" not in data:
            errors.append("Missing 'sentences' key in JSON object")
            return False, errors
        sentences = data["sentences"]
    elif isinstance(data, list):
        sentences = data
    else:
        errors.append("JSON must be an object with 'sentences' or an array")
        return False, errors

    if not isinstance(sentences, list):
        errors.append("'sentences' must be an array")
        return False, errors

    if len(sentences) == 0:
        errors.append("'sentences' array is empty")
        return False, errors

    # Required fields (no duration - computed on import)
    required_fields = {"text", "start", "end", "translation"}

    for idx, sent in enumerate(sentences):
        if not isinstance(sent, dict):
            errors.append(f"Sentence {idx}: must be an object")
            continue

        # Check required fields
        missing = required_fields - set(sent.keys())
        if missing:
            errors.append(f"Sentence {idx}: missing fields {missing}")

        # Validate types
        if "text" in sent and not isinstance(sent["text"], str):
            errors.append(f"Sentence {idx}: 'text' must be a string")

        if "translation" in sent and not isinstance(sent["translation"], str):
            errors.append(f"Sentence {idx}: 'translation' must be a string")

        if "start" in sent:
            if not isinstance(sent["start"], (int, float)):
                errors.append(f"Sentence {idx}: 'start' must be a number")
            elif sent["start"] < 0:
                errors.append(f"Sentence {idx}: 'start' cannot be negative")

        if "end" in sent:
            if not isinstance(sent["end"], (int, float)):
                errors.append(f"Sentence {idx}: 'end' must be a number")

        # Validate start < end
        if "start" in sent and "end" in sent:
            if isinstance(sent["start"], (int, float)) and isinstance(sent["end"], (int, float)):
                if sent["end"] <= sent["start"]:
                    errors.append(f"Sentence {idx}: 'end' must be greater than 'start'")

    return len(errors) == 0, errors


def parse_transcript_json(data: Union[Dict, List]) -> List[Dict[str, Any]]:
    """
    Parse and normalize transcript JSON.

    Handles both wrapped {"sentences": [...]} and flat [...] formats.
    Removes 'duration' field if present (computed on demand).

    Args:
        data: Validated JSON data.

    Returns:
        List of normalized sentence dicts with keys: text, start, end, translation.
    """
    # Extract sentences array
    if isinstance(data, dict):
        sentences = data["sentences"]
    else:
        sentences = data

    # Normalize: remove duration, ensure consistent keys
    normalized = []
    for sent in sentences:
        normalized.append({
            "text": sent["text"].strip(),
            "start": float(sent["start"]),
            "end": float(sent["end"]),
            "translation": sent["translation"].strip(),
        })

    return normalized

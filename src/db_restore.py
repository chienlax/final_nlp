"""
Database Restore Script for DVC Sync.

Imports JSONL files from DVC into PostgreSQL using last-write-wins
conflict resolution based on updated_at timestamps.

Usage:
    python src/db_restore.py              # Import with last-write-wins
    python src/db_restore.py --force      # Overwrite all (ignore timestamps)
    python src/db_restore.py --dry-run    # Preview without applying

Reads from: data/db_sync/
"""

import argparse
import gzip
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import Json, execute_values

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('db_restore')

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_SYNC_DIR = PROJECT_ROOT / 'data' / 'db_sync'


def get_pg_connection() -> psycopg2.extensions.connection:
    """
    Establishes a connection to the PostgreSQL database.

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


def read_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Read rows from a JSONL file (supports gzip).

    Args:
        file_path: Path to the JSONL file.

    Returns:
        List of row dictionaries.
    """
    rows = []

    if file_path.suffix == '.gz':
        open_func = gzip.open
        mode = 'rt'
    else:
        open_func = open
        mode = 'r'

    with open_func(file_path, mode, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    return rows


def get_latest_files_by_table(sync_dir: Path) -> Dict[str, Path]:
    """
    Get the latest export file for each table.

    Args:
        sync_dir: Directory containing JSONL export files.

    Returns:
        Dictionary mapping table names to their latest file paths.
    """
    table_files: Dict[str, List[Tuple[datetime, Path]]] = {}

    for file_path in sync_dir.glob('*.jsonl*'):
        # Parse filename: {table}_{timestamp}.jsonl[.gz]
        name = file_path.name
        if name.endswith('.gz'):
            name = name[:-3]  # Remove .gz
        if name.endswith('.jsonl'):
            name = name[:-6]  # Remove .jsonl

        parts = name.rsplit('_', 2)  # Split from right: table_date_time
        if len(parts) >= 3:
            table = '_'.join(parts[:-2])  # Handle tables with underscores
            timestamp_str = f"{parts[-2]}_{parts[-1]}"
            try:
                timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                if table not in table_files:
                    table_files[table] = []
                table_files[table].append((timestamp, file_path))
            except ValueError:
                logger.warning(f"Could not parse timestamp from: {file_path.name}")

    # Get latest file for each table
    latest: Dict[str, Path] = {}
    for table, files in table_files.items():
        files.sort(key=lambda x: x[0], reverse=True)
        latest[table] = files[0][1]
        logger.debug(f"Latest file for {table}: {files[0][1].name}")

    return latest


def log_conflict(
    conn: psycopg2.extensions.connection,
    sample_id: str,
    table_name: str,
    local_data: Dict[str, Any],
    remote_data: Dict[str, Any],
    winner: str
) -> None:
    """
    Log a sync conflict to the sync_conflicts table.

    Args:
        conn: Database connection.
        sample_id: ID of the conflicting sample.
        table_name: Table where conflict occurred.
        local_data: Local version of the data.
        remote_data: Remote (incoming) version of the data.
        winner: Which version won ('local' or 'remote').
    """
    with conn.cursor() as cur:
        # Check if sync_conflicts table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'sync_conflicts'
            )
        """)
        if not cur.fetchone()[0]:
            return

        cur.execute("""
            INSERT INTO sync_conflicts (
                sample_id, table_name, local_data, remote_data, winner
            ) VALUES (%s, %s, %s, %s, %s)
        """, (
            sample_id, table_name,
            Json(local_data), Json(remote_data), winner
        ))


def restore_sources(
    conn: psycopg2.extensions.connection,
    rows: List[Dict[str, Any]],
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    Restore sources table with conflict resolution.

    Args:
        conn: Database connection.
        rows: List of source rows to restore.
        force: If True, overwrite all (ignore timestamps).
        dry_run: If True, don't actually apply changes.

    Returns:
        Tuple of (inserted, updated, skipped) counts.
    """
    inserted = updated = skipped = 0

    for row in rows:
        source_id = row.get('source_id')
        remote_updated_at = row.get('updated_at')

        if isinstance(remote_updated_at, str):
            remote_updated_at = datetime.fromisoformat(remote_updated_at)

        with conn.cursor() as cur:
            # Check if exists and get local updated_at
            cur.execute(
                "SELECT updated_at FROM sources WHERE source_id = %s",
                (source_id,)
            )
            result = cur.fetchone()

            if result is None:
                # Insert new row
                if not dry_run:
                    cur.execute("""
                        INSERT INTO sources (
                            source_id, source_type, external_id, name, url,
                            metadata, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_id) DO NOTHING
                    """, (
                        source_id, row.get('source_type'), row.get('external_id'),
                        row.get('name'), row.get('url'),
                        Json(row.get('metadata', {})),
                        row.get('created_at'), row.get('updated_at')
                    ))
                inserted += 1
            else:
                local_updated_at = result[0]

                # Last-write-wins: remote wins if newer or force mode
                if force or (remote_updated_at and remote_updated_at > local_updated_at):
                    if not dry_run:
                        cur.execute("""
                            UPDATE sources SET
                                source_type = %s,
                                external_id = %s,
                                name = %s,
                                url = %s,
                                metadata = %s,
                                updated_at = %s
                            WHERE source_id = %s
                        """, (
                            row.get('source_type'), row.get('external_id'),
                            row.get('name'), row.get('url'),
                            Json(row.get('metadata', {})),
                            row.get('updated_at'), source_id
                        ))
                    updated += 1
                else:
                    skipped += 1

    return inserted, updated, skipped


def restore_samples(
    conn: psycopg2.extensions.connection,
    rows: List[Dict[str, Any]],
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    Restore samples table with conflict resolution.

    Args:
        conn: Database connection.
        rows: List of sample rows to restore.
        force: If True, overwrite all (ignore timestamps).
        dry_run: If True, don't actually apply changes.

    Returns:
        Tuple of (inserted, updated, skipped) counts.
    """
    inserted = updated = skipped = 0

    for row in rows:
        sample_id = row.get('sample_id')
        remote_updated_at = row.get('updated_at')

        if isinstance(remote_updated_at, str):
            remote_updated_at = datetime.fromisoformat(remote_updated_at)

        with conn.cursor() as cur:
            # Check if exists and get local data
            cur.execute("""
                SELECT updated_at, sync_version FROM samples
                WHERE sample_id = %s
            """, (sample_id,))
            result = cur.fetchone()

            if result is None:
                # Insert new row
                if not dry_run:
                    cur.execute("""
                        INSERT INTO samples (
                            sample_id, source_id, parent_sample_id, external_id,
                            content_type, audio_file_path, text_file_path,
                            pipeline_type, processing_state, segment_index,
                            start_time_ms, end_time_ms, current_transcript_version,
                            current_translation_version, duration_seconds, sample_rate,
                            cs_ratio, source_metadata, acoustic_metadata,
                            linguistic_metadata, processing_metadata, quality_score,
                            priority, label_studio_project_id, label_studio_task_id,
                            dvc_commit_hash, audio_file_md5, sync_version,
                            locked_at, locked_by, is_gold_standard, gold_score,
                            created_at, updated_at, processed_at, is_deleted, deleted_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (sample_id) DO NOTHING
                    """, (
                        sample_id, row.get('source_id'), row.get('parent_sample_id'),
                        row.get('external_id'), row.get('content_type'),
                        row.get('audio_file_path'), row.get('text_file_path'),
                        row.get('pipeline_type'), row.get('processing_state'),
                        row.get('segment_index'), row.get('start_time_ms'),
                        row.get('end_time_ms'), row.get('current_transcript_version'),
                        row.get('current_translation_version'), row.get('duration_seconds'),
                        row.get('sample_rate'), row.get('cs_ratio'),
                        Json(row.get('source_metadata', {})),
                        Json(row.get('acoustic_metadata', {})),
                        Json(row.get('linguistic_metadata', {})),
                        Json(row.get('processing_metadata', {})),
                        row.get('quality_score'), row.get('priority'),
                        row.get('label_studio_project_id'),
                        row.get('label_studio_task_id'),
                        row.get('dvc_commit_hash'), row.get('audio_file_md5'),
                        row.get('sync_version'), row.get('locked_at'),
                        row.get('locked_by'), row.get('is_gold_standard'),
                        row.get('gold_score'), row.get('created_at'),
                        row.get('updated_at'), row.get('processed_at'),
                        row.get('is_deleted'), row.get('deleted_at')
                    ))
                inserted += 1
            else:
                local_updated_at = result[0]

                # Last-write-wins: remote wins if newer or force mode
                if force or (remote_updated_at and remote_updated_at > local_updated_at):
                    # Log conflict before overwriting
                    if not dry_run and not force:
                        log_conflict(
                            conn, sample_id, 'samples',
                            {'updated_at': local_updated_at.isoformat() if local_updated_at else None},
                            {'updated_at': remote_updated_at.isoformat() if remote_updated_at else None},
                            'remote'
                        )

                    if not dry_run:
                        cur.execute("""
                            UPDATE samples SET
                                source_id = %s, parent_sample_id = %s,
                                external_id = %s, content_type = %s,
                                audio_file_path = %s, text_file_path = %s,
                                pipeline_type = %s, processing_state = %s,
                                segment_index = %s, start_time_ms = %s,
                                end_time_ms = %s, current_transcript_version = %s,
                                current_translation_version = %s, duration_seconds = %s,
                                sample_rate = %s, cs_ratio = %s,
                                source_metadata = %s, acoustic_metadata = %s,
                                linguistic_metadata = %s, processing_metadata = %s,
                                quality_score = %s, priority = %s,
                                label_studio_project_id = %s, label_studio_task_id = %s,
                                dvc_commit_hash = %s, audio_file_md5 = %s,
                                sync_version = %s, locked_at = %s, locked_by = %s,
                                is_gold_standard = %s, gold_score = %s,
                                updated_at = %s, processed_at = %s,
                                is_deleted = %s, deleted_at = %s
                            WHERE sample_id = %s
                        """, (
                            row.get('source_id'), row.get('parent_sample_id'),
                            row.get('external_id'), row.get('content_type'),
                            row.get('audio_file_path'), row.get('text_file_path'),
                            row.get('pipeline_type'), row.get('processing_state'),
                            row.get('segment_index'), row.get('start_time_ms'),
                            row.get('end_time_ms'), row.get('current_transcript_version'),
                            row.get('current_translation_version'), row.get('duration_seconds'),
                            row.get('sample_rate'), row.get('cs_ratio'),
                            Json(row.get('source_metadata', {})),
                            Json(row.get('acoustic_metadata', {})),
                            Json(row.get('linguistic_metadata', {})),
                            Json(row.get('processing_metadata', {})),
                            row.get('quality_score'), row.get('priority'),
                            row.get('label_studio_project_id'),
                            row.get('label_studio_task_id'),
                            row.get('dvc_commit_hash'), row.get('audio_file_md5'),
                            row.get('sync_version'), row.get('locked_at'),
                            row.get('locked_by'), row.get('is_gold_standard'),
                            row.get('gold_score'), row.get('updated_at'),
                            row.get('processed_at'), row.get('is_deleted'),
                            row.get('deleted_at'), sample_id
                        ))
                    updated += 1
                else:
                    skipped += 1

    return inserted, updated, skipped


def restore_transcript_revisions(
    conn: psycopg2.extensions.connection,
    rows: List[Dict[str, Any]],
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    Restore transcript_revisions table (append-only, no updates).

    Args:
        conn: Database connection.
        rows: List of revision rows to restore.
        force: Ignored for append-only tables.
        dry_run: If True, don't actually apply changes.

    Returns:
        Tuple of (inserted, updated=0, skipped) counts.
    """
    inserted = skipped = 0

    for row in rows:
        revision_id = row.get('revision_id')

        with conn.cursor() as cur:
            # Check if exists
            cur.execute(
                "SELECT 1 FROM transcript_revisions WHERE revision_id = %s",
                (revision_id,)
            )
            if cur.fetchone() is not None:
                skipped += 1
                continue

            # Insert new revision
            if not dry_run:
                cur.execute("""
                    INSERT INTO transcript_revisions (
                        revision_id, sample_id, version, transcript_text,
                        revision_type, revision_source, timestamps,
                        metadata, created_at, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (revision_id) DO NOTHING
                """, (
                    revision_id, row.get('sample_id'), row.get('version'),
                    row.get('transcript_text'), row.get('revision_type'),
                    row.get('revision_source'),
                    Json(row.get('timestamps')) if row.get('timestamps') else None,
                    Json(row.get('metadata', {})),
                    row.get('created_at'), row.get('created_by')
                ))
            inserted += 1

    return inserted, 0, skipped


def restore_translation_revisions(
    conn: psycopg2.extensions.connection,
    rows: List[Dict[str, Any]],
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    Restore translation_revisions table (append-only, no updates).

    Args:
        conn: Database connection.
        rows: List of revision rows to restore.
        force: Ignored for append-only tables.
        dry_run: If True, don't actually apply changes.

    Returns:
        Tuple of (inserted, updated=0, skipped) counts.
    """
    inserted = skipped = 0

    for row in rows:
        revision_id = row.get('revision_id')

        with conn.cursor() as cur:
            # Check if exists
            cur.execute(
                "SELECT 1 FROM translation_revisions WHERE revision_id = %s",
                (revision_id,)
            )
            if cur.fetchone() is not None:
                skipped += 1
                continue

            # Insert new revision
            if not dry_run:
                cur.execute("""
                    INSERT INTO translation_revisions (
                        revision_id, sample_id, version, source_transcript_revision_id,
                        translation_text, source_language, target_language,
                        revision_type, revision_source, confidence_score,
                        bleu_score, metadata, created_at, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (revision_id) DO NOTHING
                """, (
                    revision_id, row.get('sample_id'), row.get('version'),
                    row.get('source_transcript_revision_id'),
                    row.get('translation_text'), row.get('source_language'),
                    row.get('target_language'), row.get('revision_type'),
                    row.get('revision_source'), row.get('confidence_score'),
                    row.get('bleu_score'), Json(row.get('metadata', {})),
                    row.get('created_at'), row.get('created_by')
                ))
            inserted += 1

    return inserted, 0, skipped


def restore_annotations(
    conn: psycopg2.extensions.connection,
    rows: List[Dict[str, Any]],
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    Restore annotations table with conflict resolution.

    Args:
        conn: Database connection.
        rows: List of annotation rows to restore.
        force: If True, overwrite all.
        dry_run: If True, don't actually apply changes.

    Returns:
        Tuple of (inserted, updated, skipped) counts.
    """
    inserted = updated = skipped = 0

    for row in rows:
        annotation_id = row.get('annotation_id')
        remote_updated_at = row.get('updated_at')

        if isinstance(remote_updated_at, str):
            remote_updated_at = datetime.fromisoformat(remote_updated_at)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT updated_at FROM annotations WHERE annotation_id = %s",
                (annotation_id,)
            )
            result = cur.fetchone()

            if result is None:
                if not dry_run:
                    cur.execute("""
                        INSERT INTO annotations (
                            annotation_id, sample_id, task_type, status,
                            assigned_to, assigned_at, label_studio_project_id,
                            label_studio_task_id, label_studio_annotation_id,
                            result, time_spent_seconds, confidence_score,
                            reviewer_id, review_result, reviewed_at,
                            sample_sync_version_at_start, conflict_detected,
                            conflict_resolution, created_at, updated_at, completed_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (annotation_id) DO NOTHING
                    """, (
                        annotation_id, row.get('sample_id'), row.get('task_type'),
                        row.get('status'), row.get('assigned_to'),
                        row.get('assigned_at'), row.get('label_studio_project_id'),
                        row.get('label_studio_task_id'),
                        row.get('label_studio_annotation_id'),
                        Json(row.get('result')) if row.get('result') else None,
                        row.get('time_spent_seconds'), row.get('confidence_score'),
                        row.get('reviewer_id'),
                        Json(row.get('review_result')) if row.get('review_result') else None,
                        row.get('reviewed_at'),
                        row.get('sample_sync_version_at_start'),
                        row.get('conflict_detected'), row.get('conflict_resolution'),
                        row.get('created_at'), row.get('updated_at'),
                        row.get('completed_at')
                    ))
                inserted += 1
            else:
                local_updated_at = result[0]
                if force or (remote_updated_at and remote_updated_at > local_updated_at):
                    if not dry_run:
                        cur.execute("""
                            UPDATE annotations SET
                                sample_id = %s, task_type = %s, status = %s,
                                assigned_to = %s, assigned_at = %s,
                                label_studio_project_id = %s, label_studio_task_id = %s,
                                label_studio_annotation_id = %s, result = %s,
                                time_spent_seconds = %s, confidence_score = %s,
                                reviewer_id = %s, review_result = %s, reviewed_at = %s,
                                sample_sync_version_at_start = %s,
                                conflict_detected = %s, conflict_resolution = %s,
                                updated_at = %s, completed_at = %s
                            WHERE annotation_id = %s
                        """, (
                            row.get('sample_id'), row.get('task_type'),
                            row.get('status'), row.get('assigned_to'),
                            row.get('assigned_at'), row.get('label_studio_project_id'),
                            row.get('label_studio_task_id'),
                            row.get('label_studio_annotation_id'),
                            Json(row.get('result')) if row.get('result') else None,
                            row.get('time_spent_seconds'), row.get('confidence_score'),
                            row.get('reviewer_id'),
                            Json(row.get('review_result')) if row.get('review_result') else None,
                            row.get('reviewed_at'),
                            row.get('sample_sync_version_at_start'),
                            row.get('conflict_detected'), row.get('conflict_resolution'),
                            row.get('updated_at'), row.get('completed_at'),
                            annotation_id
                        ))
                    updated += 1
                else:
                    skipped += 1

    return inserted, updated, skipped


def run_restore(
    force: bool = False,
    dry_run: bool = False
) -> Dict[str, Tuple[int, int, int]]:
    """
    Run the database restore process.

    Args:
        force: If True, overwrite all (ignore timestamps).
        dry_run: If True, only report what would be changed.

    Returns:
        Dictionary with (inserted, updated, skipped) per table.
    """
    if not DB_SYNC_DIR.exists():
        logger.warning(f"Sync directory does not exist: {DB_SYNC_DIR}")
        return {}

    # Get latest files for each table
    table_files = get_latest_files_by_table(DB_SYNC_DIR)

    if not table_files:
        logger.info("No JSONL files found to restore.")
        return {}

    logger.info(f"Found export files for tables: {list(table_files.keys())}")

    stats: Dict[str, Tuple[int, int, int]] = {}
    conn = get_pg_connection()

    try:
        # Restore in order (sources first, then samples, then revisions)
        restore_order = [
            'sources',
            'samples',
            'transcript_revisions',
            'translation_revisions',
            'annotations',
            'sample_lineage',
            'processing_logs',
        ]

        restore_functions = {
            'sources': restore_sources,
            'samples': restore_samples,
            'transcript_revisions': restore_transcript_revisions,
            'translation_revisions': restore_translation_revisions,
            'annotations': restore_annotations,
        }

        for table in restore_order:
            if table not in table_files:
                continue

            file_path = table_files[table]
            rows = read_jsonl_file(file_path)

            if not rows:
                logger.info(f"  {table}: 0 rows in file")
                continue

            if table in restore_functions:
                inserted, updated, skipped = restore_functions[table](
                    conn, rows, force=force, dry_run=dry_run
                )
                stats[table] = (inserted, updated, skipped)
                action = "[DRY-RUN] " if dry_run else ""
                logger.info(
                    f"  {action}{table}: {inserted} inserted, "
                    f"{updated} updated, {skipped} skipped"
                )
            else:
                # Skip tables without restore function (logs, lineage)
                logger.debug(f"  {table}: skipped (no restore function)")

        if not dry_run:
            conn.commit()
            logger.info("Changes committed to database.")
        else:
            conn.rollback()

        return stats

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Import JSONL database exports from DVC.'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite all records (ignore timestamps, brute-force sync)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview import without applying changes'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Database Restore from DVC")
    logger.info("=" * 60)

    if args.force:
        logger.warning("FORCE mode: All records will be overwritten!")

    try:
        stats = run_restore(force=args.force, dry_run=args.dry_run)

        if not stats:
            logger.info("Nothing to restore.")
            return 0

        # Summary
        total_inserted = sum(s[0] for s in stats.values())
        total_updated = sum(s[1] for s in stats.values())
        total_skipped = sum(s[2] for s in stats.values())

        logger.info("=" * 60)
        logger.info(
            f"Total: {total_inserted} inserted, {total_updated} updated, "
            f"{total_skipped} skipped"
        )

        return 0

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

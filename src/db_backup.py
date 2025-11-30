"""
Database Backup Script for DVC Sync.

Exports incremental database changes (samples, transcripts, translations)
to JSONL files for DVC tracking. Supports full export mode for initial sync.

Usage:
    python src/db_backup.py              # Incremental export (since last sync)
    python src/db_backup.py --full       # Full export (all data)
    python src/db_backup.py --dry-run    # Preview without writing

Exports to: data/db_sync/
"""

import argparse
import gzip
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('db_backup')

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_SYNC_DIR = PROJECT_ROOT / 'data' / 'db_sync'
LAST_SYNC_FILE = DB_SYNC_DIR / '.last_sync'
SYNC_HISTORY_FILE = DB_SYNC_DIR / '.sync_history'


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


def get_last_sync_time() -> Optional[datetime]:
    """
    Get the timestamp of the last successful sync.

    Returns:
        Last sync datetime or None if never synced.
    """
    if not LAST_SYNC_FILE.exists():
        return None

    try:
        content = LAST_SYNC_FILE.read_text().strip()
        return datetime.fromisoformat(content)
    except (ValueError, OSError) as e:
        logger.warning(f"Could not read last sync time: {e}")
        return None


def save_last_sync_time(sync_time: datetime) -> None:
    """
    Save the timestamp of the current sync.

    Args:
        sync_time: The datetime to save.
    """
    DB_SYNC_DIR.mkdir(parents=True, exist_ok=True)
    LAST_SYNC_FILE.write_text(sync_time.isoformat())


def append_sync_history(
    sync_time: datetime,
    stats: Dict[str, int],
    full_sync: bool
) -> None:
    """
    Append sync operation to history file.

    Args:
        sync_time: When the sync occurred.
        stats: Export statistics (counts per table).
        full_sync: Whether this was a full or incremental sync.
    """
    history_entry = {
        'timestamp': sync_time.isoformat(),
        'type': 'full' if full_sync else 'incremental',
        'stats': stats,
    }

    history_lines = []
    if SYNC_HISTORY_FILE.exists():
        history_lines = SYNC_HISTORY_FILE.read_text().strip().split('\n')
        # Keep last 100 entries
        history_lines = history_lines[-99:]

    history_lines.append(json.dumps(history_entry))
    SYNC_HISTORY_FILE.write_text('\n'.join(history_lines))


def json_serializer(obj: Any) -> Any:
    """
    Custom JSON serializer for objects not serializable by default.

    Args:
        obj: Object to serialize.

    Returns:
        Serializable representation.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, '__str__'):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_table(
    conn: psycopg2.extensions.connection,
    table_name: str,
    since: Optional[datetime] = None,
    batch_size: int = 1000
) -> Generator[Dict[str, Any], None, None]:
    """
    Export rows from a table, optionally filtered by updated_at.

    Args:
        conn: Database connection.
        table_name: Name of the table to export.
        since: Only export rows updated after this time (None = all rows).
        batch_size: Number of rows to fetch per batch.

    Yields:
        Row dictionaries.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Build query based on whether we're doing incremental or full export
        if since and table_name in ('samples', 'sources', 'annotations'):
            # Tables with updated_at column
            query = f"""
                SELECT * FROM {table_name}
                WHERE updated_at > %s
                ORDER BY updated_at ASC
            """
            cur.execute(query, (since,))
        elif since and table_name in ('transcript_revisions', 'translation_revisions'):
            # Revision tables use created_at
            query = f"""
                SELECT * FROM {table_name}
                WHERE created_at > %s
                ORDER BY created_at ASC
            """
            cur.execute(query, (since,))
        elif since and table_name == 'processing_logs':
            query = f"""
                SELECT * FROM {table_name}
                WHERE created_at > %s
                ORDER BY created_at ASC
            """
            cur.execute(query, (since,))
        elif since and table_name in ('segments', 'segment_translations'):
            query = f"""
                SELECT * FROM {table_name}
                WHERE created_at > %s
                ORDER BY created_at ASC
            """
            cur.execute(query, (since,))
        else:
            # Full export
            query = f"SELECT * FROM {table_name} ORDER BY created_at ASC"
            cur.execute(query)

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                yield dict(row)


def export_sync_conflicts(
    conn: psycopg2.extensions.connection,
    since: Optional[datetime] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Export sync conflicts table if it exists.

    Args:
        conn: Database connection.
        since: Only export conflicts created after this time.

    Yields:
        Conflict row dictionaries.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check if table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'sync_conflicts'
            )
        """)
        if not cur.fetchone()['exists']:
            return

        if since:
            cur.execute(
                "SELECT * FROM sync_conflicts WHERE created_at > %s ORDER BY created_at ASC",
                (since,)
            )
        else:
            cur.execute("SELECT * FROM sync_conflicts ORDER BY created_at ASC")

        for row in cur.fetchall():
            yield dict(row)


def write_jsonl_file(
    output_path: Path,
    rows: Generator[Dict[str, Any], None, None],
    compress: bool = True
) -> int:
    """
    Write rows to a JSONL file (optionally gzipped).

    Args:
        output_path: Path to write to.
        rows: Generator of row dictionaries.
        compress: Whether to gzip the output.

    Returns:
        Number of rows written.
    """
    count = 0
    final_path = output_path.with_suffix('.jsonl.gz' if compress else '.jsonl')

    if compress:
        with gzip.open(final_path, 'wt', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, default=json_serializer) + '\n')
                count += 1
    else:
        with open(final_path, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, default=json_serializer) + '\n')
                count += 1

    return count


def run_backup(
    full: bool = False,
    dry_run: bool = False,
    compress: bool = True
) -> Dict[str, int]:
    """
    Run the database backup process.

    Args:
        full: If True, export all data. If False, export only changes since last sync.
        dry_run: If True, only report what would be exported.
        compress: If True, gzip output files.

    Returns:
        Dictionary with export statistics.
    """
    sync_time = datetime.now(timezone.utc)
    last_sync = None if full else get_last_sync_time()

    if last_sync:
        logger.info(f"Incremental backup since: {last_sync.isoformat()}")
    else:
        logger.info("Full backup (no previous sync found or --full specified)")

    # Tables to export (must exist in database schema)
    tables = [
        'sources',
        'samples',
        'transcript_revisions',
        'translation_revisions',
        'annotations',
        'segments',
        'segment_translations',
        'processing_logs',
    ]

    stats: Dict[str, int] = {}
    conn = get_pg_connection()

    try:
        # Create output directory
        if not dry_run:
            DB_SYNC_DIR.mkdir(parents=True, exist_ok=True)

        # Generate timestamp for filenames
        timestamp = sync_time.strftime('%Y%m%d_%H%M%S')

        for table in tables:
            output_filename = f"{table}_{timestamp}"
            output_path = DB_SYNC_DIR / output_filename

            if dry_run:
                # Count rows that would be exported
                with conn.cursor() as cur:
                    if last_sync and table in ('samples', 'sources', 'annotations'):
                        cur.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE updated_at > %s",
                            (last_sync,)
                        )
                    elif last_sync and table in (
                        'transcript_revisions', 'translation_revisions',
                        'processing_logs', 'segments', 'segment_translations'
                    ):
                        cur.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE created_at > %s",
                            (last_sync,)
                        )
                    else:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                stats[table] = count
                logger.info(f"  [DRY-RUN] {table}: {count} rows would be exported")
            else:
                # Actually export
                rows = export_table(conn, table, since=last_sync)
                count = write_jsonl_file(output_path, rows, compress=compress)
                stats[table] = count
                if count > 0:
                    logger.info(f"  {table}: {count} rows exported")
                else:
                    # Remove empty files
                    final_path = output_path.with_suffix(
                        '.jsonl.gz' if compress else '.jsonl'
                    )
                    if final_path.exists():
                        final_path.unlink()

        # Export sync_conflicts if exists
        if dry_run:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'sync_conflicts'
                    )
                """)
                if cur.fetchone()[0]:
                    if last_sync:
                        cur.execute(
                            "SELECT COUNT(*) FROM sync_conflicts WHERE created_at > %s",
                            (last_sync,)
                        )
                    else:
                        cur.execute("SELECT COUNT(*) FROM sync_conflicts")
                    count = cur.fetchone()[0]
                    stats['sync_conflicts'] = count
                    logger.info(f"  [DRY-RUN] sync_conflicts: {count} rows would be exported")
        else:
            output_path = DB_SYNC_DIR / f"sync_conflicts_{timestamp}"
            rows = export_sync_conflicts(conn, since=last_sync)
            rows_list = list(rows)  # Need to consume to check if any
            if rows_list:
                count = write_jsonl_file(
                    output_path, iter(rows_list), compress=compress
                )
                stats['sync_conflicts'] = count
                logger.info(f"  sync_conflicts: {count} rows exported")

        # Update sync tracking files
        if not dry_run:
            save_last_sync_time(sync_time)
            append_sync_history(sync_time, stats, full_sync=full)
            logger.info(f"Sync checkpoint saved: {sync_time.isoformat()}")

        # Log summary
        total = sum(stats.values())
        logger.info(f"Total rows exported: {total}")

        return stats

    finally:
        conn.close()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Export PostgreSQL database for DVC tracking.'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Export all data (not just changes since last sync)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview export without writing files'
    )
    parser.add_argument(
        '--no-compress',
        action='store_true',
        help='Do not gzip output files'
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
    logger.info("Database Backup for DVC")
    logger.info("=" * 60)

    try:
        stats = run_backup(
            full=args.full,
            dry_run=args.dry_run,
            compress=not args.no_compress
        )

        if sum(stats.values()) == 0:
            logger.info("No changes to export.")

        return 0

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

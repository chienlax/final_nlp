"""
DVC Sync Daemon for automatic data synchronization.

Runs periodic sync operations to sync data and database state
between local storage and Google Drive via DVC.

Features:
- Syncs audio/text files via DVC
- Exports/imports PostgreSQL database incrementally
- Last-write-wins conflict resolution with audit trail
- Supports force-restore for brute-force sync

Usage:
    python src/sync_daemon.py              # Run continuous sync (every 5 minutes)
    python src/sync_daemon.py --once       # Run single sync and exit
    python src/sync_daemon.py --force-restore  # Force overwrite local DB
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('sync_daemon')

# Configuration from environment
SYNC_INTERVAL_MINUTES = int(os.getenv('SYNC_INTERVAL_MINUTES', '5'))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
DB_SYNC_DIR = DATA_DIR / 'db_sync'


def run_dvc_pull(verbose: bool = True, allow_overwrite: bool = True) -> bool:
    """
    Execute `dvc pull` to sync data from remote storage.

    Args:
        verbose: Whether to show detailed output.
        allow_overwrite: If True, use --force to overwrite local files.

    Returns:
        True if sync was successful, False otherwise.
    """
    logger.info("Starting DVC pull...")
    start_time = time.time()

    try:
        # Pull all DVC tracked data directories
        # - raw: ingested YouTube audio/transcripts
        # - db_sync: database backups
        # - review: sentence audio for Label Studio review (if exists)
        # - final: processed audio after review (if exists)
        # - dataset: exported training data (if exists)
        dvc_files = [
            'data/raw.dvc',
            'data/db_sync.dvc',
        ]
        # Add optional .dvc files if they exist
        optional_dvc = [
            'data/review.dvc',
            'data/final.dvc',
            'data/dataset.dvc',
        ]
        for dvc_file in optional_dvc:
            if (PROJECT_ROOT / dvc_file).exists():
                dvc_files.append(dvc_file)
        
        cmd = ['dvc', 'pull'] + dvc_files
        if allow_overwrite:
            cmd.append('--force')

        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout (extended for DB sync)
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"DVC pull completed successfully in {elapsed:.1f}s")
            if verbose and result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        logger.debug(f"  {line}")
            return True
        else:
            logger.error(f"DVC pull failed with code {result.returncode}")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("DVC pull timed out after 15 minutes")
        return False
    except FileNotFoundError:
        logger.error("DVC command not found. Is DVC installed?")
        return False
    except Exception as e:
        logger.error(f"DVC pull error: {e}")
        return False


def run_dvc_push(verbose: bool = True) -> bool:
    """
    Execute `dvc push` to upload local changes to remote storage.

    Args:
        verbose: Whether to show detailed output.

    Returns:
        True if push was successful, False otherwise.
    """
    logger.info("Starting DVC push...")
    start_time = time.time()

    try:
        result = subprocess.run(
            ['dvc', 'push'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout (extended for DB sync)
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"DVC push completed successfully in {elapsed:.1f}s")
            if verbose and result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        logger.debug(f"  {line}")
            return True
        else:
            logger.error(f"DVC push failed with code {result.returncode}")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("DVC push timed out after 15 minutes")
        return False
    except FileNotFoundError:
        logger.error("DVC command not found. Is DVC installed?")
        return False
    except Exception as e:
        logger.error(f"DVC push error: {e}")
        return False


def run_db_backup(full: bool = False) -> bool:
    """
    Run database backup script to export changes for DVC.

    Args:
        full: If True, export all data (not just incremental).

    Returns:
        True if backup was successful, False otherwise.
    """
    logger.info("Starting database backup...")
    start_time = time.time()

    try:
        cmd = [sys.executable, str(PROJECT_ROOT / 'src' / 'db_backup.py')]
        if full:
            cmd.append('--full')

        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"Database backup completed in {elapsed:.1f}s")
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line and 'exported' in line.lower():
                        logger.info(f"  {line}")
            return True
        else:
            logger.error(f"Database backup failed with code {result.returncode}")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Database backup timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Database backup error: {e}")
        return False


def run_db_restore(force: bool = False) -> bool:
    """
    Run database restore script to import changes from DVC.

    Args:
        force: If True, overwrite all (ignore timestamps).

    Returns:
        True if restore was successful, False otherwise.
    """
    # Check if there are files to restore
    if not DB_SYNC_DIR.exists() or not any(DB_SYNC_DIR.glob('*.jsonl*')):
        logger.debug("No database sync files found, skipping restore")
        return True

    logger.info("Starting database restore...")
    start_time = time.time()

    try:
        cmd = [sys.executable, str(PROJECT_ROOT / 'src' / 'db_restore.py')]
        if force:
            cmd.append('--force')

        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"Database restore completed in {elapsed:.1f}s")
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line and ('inserted' in line.lower() or 'updated' in line.lower()):
                        logger.info(f"  {line}")
            return True
        else:
            logger.error(f"Database restore failed with code {result.returncode}")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Database restore timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Database restore error: {e}")
        return False


def check_dvc_status() -> Optional[dict]:
    """
    Check DVC status to see if there are changes to sync.

    Returns:
        Dictionary with status info, or None if check failed.
    """
    try:
        result = subprocess.run(
            ['dvc', 'status'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            # Parse status output
            has_changes = bool(output and output != 'Data and calculation version is up to date.')
            return {
                'has_changes': has_changes,
                'output': output,
            }
        return None

    except Exception as e:
        logger.error(f"DVC status check failed: {e}")
        return None


def get_data_stats() -> dict:
    """
    Get statistics about current data directory.

    Returns:
        Dictionary with file counts and sizes.
    """
    stats = {
        'raw_audio': 0,
        'raw_text': 0,
        'review_samples': 0,
        'final_samples': 0,
        'dataset_samples': 0,
        'total_size_mb': 0,
    }

    # Raw data (ingested from YouTube)
    audio_dir = DATA_DIR / 'raw' / 'audio'
    text_dir = DATA_DIR / 'raw' / 'text'

    if audio_dir.exists():
        audio_files = list(audio_dir.glob('*.wav'))
        stats['raw_audio'] = len(audio_files)
        stats['total_size_mb'] += sum(f.stat().st_size for f in audio_files) / (1024 * 1024)

    if text_dir.exists():
        text_files = list(text_dir.glob('**/*.json'))
        stats['raw_text'] = len(text_files)
        stats['total_size_mb'] += sum(f.stat().st_size for f in text_files) / (1024 * 1024)

    # Review data (sentence audio for Label Studio)
    review_dir = DATA_DIR / 'review'
    if review_dir.exists():
        review_samples = [d for d in review_dir.iterdir() if d.is_dir()]
        stats['review_samples'] = len(review_samples)
        for sample_dir in review_samples:
            wav_files = list(sample_dir.glob('**/*.wav'))
            stats['total_size_mb'] += sum(f.stat().st_size for f in wav_files) / (1024 * 1024)

    # Final data (after review corrections)
    final_dir = DATA_DIR / 'final'
    if final_dir.exists():
        final_samples = [d for d in final_dir.iterdir() if d.is_dir()]
        stats['final_samples'] = len(final_samples)
        for sample_dir in final_samples:
            wav_files = list(sample_dir.glob('**/*.wav'))
            stats['total_size_mb'] += sum(f.stat().st_size for f in wav_files) / (1024 * 1024)

    # Dataset (exported for training)
    dataset_dir = DATA_DIR / 'dataset'
    if dataset_dir.exists():
        dataset_samples = [d for d in dataset_dir.iterdir() if d.is_dir()]
        stats['dataset_samples'] = len(dataset_samples)
        for sample_dir in dataset_samples:
            wav_files = list(sample_dir.glob('**/*.wav'))
            stats['total_size_mb'] += sum(f.stat().st_size for f in wav_files) / (1024 * 1024)

    stats['total_size_mb'] = round(stats['total_size_mb'], 2)
    return stats


def run_sync_loop(interval_minutes: int = 5, force_restore: bool = False):
    """
    Run continuous sync loop with database backup/restore.

    Args:
        interval_minutes: Minutes between sync operations.
        force_restore: If True, force overwrite local DB on each restore.
    """
    logger.info("=" * 60)
    logger.info("DVC Sync Daemon Starting")
    logger.info("=" * 60)
    logger.info(f"Sync interval: {interval_minutes} minutes")
    logger.info(f"Force restore: {force_restore}")
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Data directory: {DATA_DIR}")

    sync_count = 0
    error_count = 0

    while True:
        sync_count += 1
        logger.info(f"\n--- Sync #{sync_count} at {datetime.now().isoformat()} ---")

        # Check current data stats
        stats = get_data_stats()
        logger.info(
            f"Current data: raw={stats['raw_audio']} audio/{stats['raw_text']} text, "
            f"review={stats['review_samples']}, final={stats['final_samples']}, "
            f"dataset={stats['dataset_samples']}, total={stats['total_size_mb']} MB"
        )

        sync_success = True

        # Step 1: Backup local database before pull (to preserve local changes)
        logger.info("[1/4] Backing up local database...")
        if not run_db_backup():
            logger.warning("Database backup failed, continuing with sync...")

        # Step 2: DVC pull (get remote changes)
        logger.info("[2/4] Pulling remote changes...")
        if not run_dvc_pull():
            sync_success = False
            error_count += 1

        # Step 3: Restore database from pulled files (merge remote changes)
        if sync_success:
            logger.info("[3/4] Restoring database from remote...")
            if not run_db_restore(force=force_restore):
                logger.warning("Database restore failed")

        # Step 4: Push local changes (including fresh DB backup)
        if sync_success:
            logger.info("[4/4] Pushing local changes...")
            # Re-backup to include any merged changes
            run_db_backup()
            if not run_dvc_push():
                logger.warning("DVC push failed")

        if sync_success:
            # Check stats after sync
            new_stats = get_data_stats()
            changes = []
            if new_stats['raw_audio'] != stats['raw_audio']:
                changes.append(f"raw_audio: {stats['raw_audio']} -> {new_stats['raw_audio']}")
            if new_stats['review_samples'] != stats['review_samples']:
                changes.append(f"review: {stats['review_samples']} -> {new_stats['review_samples']}")
            if new_stats['final_samples'] != stats['final_samples']:
                changes.append(f"final: {stats['final_samples']} -> {new_stats['final_samples']}")
            if new_stats['dataset_samples'] != stats['dataset_samples']:
                changes.append(f"dataset: {stats['dataset_samples']} -> {new_stats['dataset_samples']}")
            if changes:
                logger.info(f"Changes detected: {', '.join(changes)}")
        else:
            logger.warning(f"Sync failed. Total errors: {error_count}")

        # Sleep until next sync
        logger.info(f"Next sync in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


def run_once(force_restore: bool = False):
    """
    Run a single sync operation and exit.

    Args:
        force_restore: If True, force overwrite local DB.
    """
    logger.info("=" * 60)
    logger.info("DVC Sync - Single Run")
    logger.info("=" * 60)

    # Show current stats
    stats = get_data_stats()
    logger.info(
        f"Before sync: raw={stats['raw_audio']} audio/{stats['raw_text']} text, "
        f"review={stats['review_samples']}, final={stats['final_samples']}, "
        f"dataset={stats['dataset_samples']}, total={stats['total_size_mb']} MB"
    )

    # Check status
    status = check_dvc_status()
    if status:
        logger.info(f"DVC status: {'Changes pending' if status['has_changes'] else 'Up to date'}")

    # Step 1: Backup local database
    logger.info("[1/4] Backing up local database...")
    run_db_backup()

    # Step 2: Pull remote changes
    logger.info("[2/4] Pulling remote changes...")
    pull_success = run_dvc_pull()

    if pull_success:
        # Step 3: Restore database
        logger.info("[3/4] Restoring database from remote...")
        run_db_restore(force=force_restore)

        # Step 4: Push changes
        logger.info("[4/4] Pushing local changes...")
        run_db_backup()  # Re-backup after restore
        run_dvc_push()

        new_stats = get_data_stats()
        logger.info(
            f"After sync: raw={new_stats['raw_audio']} audio/{new_stats['raw_text']} text, "
            f"review={new_stats['review_samples']}, final={new_stats['final_samples']}, "
            f"dataset={new_stats['dataset_samples']}, total={new_stats['total_size_mb']} MB"
        )
        logger.info("Sync completed successfully!")
        return 0
    else:
        logger.error("Sync failed!")
        return 1


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='DVC Sync Daemon for automatic data and database synchronization.'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run single sync and exit (default: continuous loop)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=SYNC_INTERVAL_MINUTES,
        help=f'Sync interval in minutes (default: {SYNC_INTERVAL_MINUTES})'
    )
    parser.add_argument(
        '--push',
        action='store_true',
        help='Run dvc push instead of full sync'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Check DVC status and exit'
    )
    parser.add_argument(
        '--force-restore',
        action='store_true',
        help='Force overwrite local database (ignore timestamps)'
    )
    parser.add_argument(
        '--backup-only',
        action='store_true',
        help='Only run database backup (no DVC operations)'
    )
    parser.add_argument(
        '--restore-only',
        action='store_true',
        help='Only run database restore (no DVC operations)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        status = check_dvc_status()
        if status:
            print(f"Has changes: {status['has_changes']}")
            if status['output']:
                print(status['output'])
            return 0
        return 1

    if args.backup_only:
        success = run_db_backup(full=False)
        return 0 if success else 1

    if args.restore_only:
        success = run_db_restore(force=args.force_restore)
        return 0 if success else 1

    if args.push:
        # Backup DB before push
        run_db_backup()
        success = run_dvc_push(verbose=args.verbose)
        return 0 if success else 1

    if args.once:
        return run_once(force_restore=args.force_restore)

    # Run continuous sync loop
    run_sync_loop(
        interval_minutes=args.interval,
        force_restore=args.force_restore
    )


if __name__ == "__main__":
    sys.exit(main() or 0)

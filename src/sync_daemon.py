"""
DVC Sync Daemon for automatic data synchronization.

Runs periodic `dvc pull` operations to sync data from Google Drive,
ensuring Label Studio has access to the latest audio files.

Usage:
    python src/sync_daemon.py          # Run continuous sync (every 5 minutes)
    python src/sync_daemon.py --once   # Run single sync and exit
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


def run_dvc_pull(verbose: bool = True) -> bool:
    """
    Execute `dvc pull` to sync data from remote storage.

    Args:
        verbose: Whether to show detailed output.

    Returns:
        True if sync was successful, False otherwise.
    """
    logger.info("Starting DVC pull...")
    start_time = time.time()

    try:
        result = subprocess.run(
            ['dvc', 'pull'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
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
        logger.error("DVC pull timed out after 10 minutes")
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
            timeout=600,  # 10 minute timeout
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
        logger.error("DVC push timed out after 10 minutes")
        return False
    except FileNotFoundError:
        logger.error("DVC command not found. Is DVC installed?")
        return False
    except Exception as e:
        logger.error(f"DVC push error: {e}")
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
        'audio_files': 0,
        'text_files': 0,
        'total_size_mb': 0,
    }

    audio_dir = DATA_DIR / 'raw' / 'audio'
    text_dir = DATA_DIR / 'raw' / 'text'

    if audio_dir.exists():
        audio_files = list(audio_dir.glob('*.wav'))
        stats['audio_files'] = len(audio_files)
        stats['total_size_mb'] += sum(f.stat().st_size for f in audio_files) / (1024 * 1024)

    if text_dir.exists():
        text_files = list(text_dir.glob('**/*.json'))
        stats['text_files'] = len(text_files)
        stats['total_size_mb'] += sum(f.stat().st_size for f in text_files) / (1024 * 1024)

    stats['total_size_mb'] = round(stats['total_size_mb'], 2)
    return stats


def run_sync_loop(interval_minutes: int = 5):
    """
    Run continuous sync loop.

    Args:
        interval_minutes: Minutes between sync operations.
    """
    logger.info("=" * 60)
    logger.info("DVC Sync Daemon Starting")
    logger.info("=" * 60)
    logger.info(f"Sync interval: {interval_minutes} minutes")
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Data directory: {DATA_DIR}")

    sync_count = 0
    error_count = 0

    while True:
        sync_count += 1
        logger.info(f"\n--- Sync #{sync_count} at {datetime.now().isoformat()} ---")

        # Check current data stats
        stats = get_data_stats()
        logger.info(f"Current data: {stats['audio_files']} audio, {stats['text_files']} text, {stats['total_size_mb']} MB")

        # Run DVC pull
        success = run_dvc_pull()

        if success:
            # Check stats after sync
            new_stats = get_data_stats()
            if new_stats['audio_files'] != stats['audio_files']:
                logger.info(f"Audio files changed: {stats['audio_files']} -> {new_stats['audio_files']}")
            if new_stats['text_files'] != stats['text_files']:
                logger.info(f"Text files changed: {stats['text_files']} -> {new_stats['text_files']}")
        else:
            error_count += 1
            logger.warning(f"Sync failed. Total errors: {error_count}")

        # Sleep until next sync
        logger.info(f"Next sync in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


def run_once():
    """Run a single sync operation and exit."""
    logger.info("=" * 60)
    logger.info("DVC Sync - Single Run")
    logger.info("=" * 60)

    # Show current stats
    stats = get_data_stats()
    logger.info(f"Before sync: {stats['audio_files']} audio, {stats['text_files']} text, {stats['total_size_mb']} MB")

    # Check status
    status = check_dvc_status()
    if status:
        logger.info(f"DVC status: {'Changes pending' if status['has_changes'] else 'Up to date'}")

    # Run pull
    success = run_dvc_pull()

    if success:
        new_stats = get_data_stats()
        logger.info(f"After sync: {new_stats['audio_files']} audio, {new_stats['text_files']} text, {new_stats['total_size_mb']} MB")
        logger.info("Sync completed successfully!")
        return 0
    else:
        logger.error("Sync failed!")
        return 1


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='DVC Sync Daemon for automatic data synchronization.'
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
        help='Run dvc push instead of pull'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Check DVC status and exit'
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

    if args.push:
        success = run_dvc_push(verbose=args.verbose)
        return 0 if success else 1

    if args.once:
        return run_once()

    # Run continuous sync loop
    run_sync_loop(interval_minutes=args.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)

#!/usr/bin/env python3
"""
Export final samples to DVC-tracked dataset directory (v2).

Exports samples that have completed unified review (FINAL state) into a
structured format suitable for training data preparation. Uses sentence-level
audio files created by apply_review.py.

Output Structure:
    dataset/
        ├── audio/
        │   ├── train/{sample_id}_{sentence_idx:04d}.wav
        │   ├── dev/{sample_id}_{sentence_idx:04d}.wav
        │   └── test/{sample_id}_{sentence_idx:04d}.wav
        ├── train.tsv           # Training manifest (HuggingFace format)
        ├── dev.tsv             # Development manifest
        ├── test.tsv            # Test manifest
        └── db/
            └── metadata.sqlite # SQLite for filtering/analysis

Usage:
    python src/export_reviewed.py                    # Export all FINAL samples
    python src/export_reviewed.py --limit 100
    python src/export_reviewed.py --split 80:10:10  # Train:Dev:Test ratio
    python src/export_reviewed.py --dry-run
"""

import argparse
import json
import logging
import random
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('export_reviewed')

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.data_utils import get_pg_connection

# Default output directory
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / 'dataset'
DEFAULT_FINAL_ROOT = PROJECT_ROOT / 'data' / 'final'


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_final_samples(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get samples in FINAL state with review statistics.

    Args:
        limit: Maximum number of samples to return.

    Returns:
        List of sample dictionaries.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.audio_file_path,
                    s.duration_seconds,
                    s.cs_ratio,
                    s.is_gold_standard,
                    s.source_metadata,
                    s.processing_metadata,
                    s.created_at,
                    s.updated_at,
                    tr.transcript_text,
                    tr.sentence_timestamps,
                    tl.translation_text
                FROM samples s
                LEFT JOIN transcript_revisions tr 
                    ON s.sample_id = tr.sample_id 
                    AND tr.version = s.current_transcript_version
                LEFT JOIN translation_revisions tl 
                    ON s.sample_id = tl.sample_id 
                    AND tl.version = s.current_translation_version
                WHERE s.processing_state = 'FINAL'
                  AND s.is_deleted = FALSE
                ORDER BY s.updated_at DESC
            """

            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]

    finally:
        conn.close()


def get_sentence_data(sample_id: str) -> List[Dict[str, Any]]:
    """
    Get final sentence data for a sample.

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
                    COALESCE(sr.reviewed_transcript, sr.original_transcript) AS transcript,
                    COALESCE(sr.reviewed_translation, sr.original_translation) AS translation,
                    COALESCE(sr.reviewed_start_ms, sr.original_start_ms) AS start_ms,
                    COALESCE(sr.reviewed_end_ms, sr.original_end_ms) AS end_ms,
                    sr.is_rejected
                FROM sentence_reviews sr
                WHERE sr.sample_id = %s
                  AND sr.is_rejected = FALSE
                ORDER BY sr.sentence_idx ASC
                """,
                (sample_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def parse_split_ratio(split_str: str) -> Tuple[float, float, float]:
    """
    Parse split ratio string like "80:10:10".

    Args:
        split_str: Colon-separated ratio string.

    Returns:
        Tuple of (train, dev, test) ratios as decimals.
    """
    parts = split_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid split ratio: {split_str}. Expected format: train:dev:test")

    train, dev, test = [int(p) for p in parts]
    total = train + dev + test

    return train / total, dev / total, test / total


def assign_split(
    samples: List[Dict[str, Any]],
    split_ratios: Tuple[float, float, float],
    seed: int = 42
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Assign samples to train/dev/test splits.

    Args:
        samples: List of sample dictionaries.
        split_ratios: Tuple of (train, dev, test) ratios.
        seed: Random seed for reproducibility.

    Returns:
        Dictionary with 'train', 'dev', 'test' keys.
    """
    random.seed(seed)
    shuffled = samples.copy()
    random.shuffle(shuffled)

    n = len(shuffled)
    train_end = int(n * split_ratios[0])
    dev_end = train_end + int(n * split_ratios[1])

    return {
        'train': shuffled[:train_end],
        'dev': shuffled[train_end:dev_end],
        'test': shuffled[dev_end:],
    }


def export_sample_sentences(
    sample: Dict[str, Any],
    final_root: Path,
    output_dir: Path,
    split: str,
    dry_run: bool = False
) -> List[Dict[str, Any]]:
    """
    Export sentence audio files for a sample.

    Args:
        sample: Sample dictionary.
        final_root: Directory containing final audio files.
        output_dir: Base output directory.
        split: Split name ('train', 'dev', 'test').
        dry_run: If True, don't copy files.

    Returns:
        List of exported sentence metadata.
    """
    sample_id = str(sample['sample_id'])
    external_id = sample['external_id']

    # Get sentence data
    sentences = get_sentence_data(sample_id)
    if not sentences:
        logger.warning(f"No sentences found for sample {sample_id}")
        return []

    # Source directory
    source_dir = final_root / sample_id / 'sentences'
    if not source_dir.exists() and not dry_run:
        logger.warning(f"Final audio directory not found: {source_dir}")
        return []

    # Destination directory
    dest_dir = output_dir / 'audio' / split
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    
    for idx, sent in enumerate(sentences):
        sentence_idx = sent['sentence_idx']
        
        # Source file (indexed by position in final, not original index)
        source_file = source_dir / f"{idx:04d}.wav"
        
        # Destination file: {sample_id}_{idx}.wav (short sample_id for filename)
        short_id = external_id if len(external_id) <= 11 else sample_id[:8]
        dest_filename = f"{short_id}_{idx:04d}.wav"
        dest_file = dest_dir / dest_filename

        if not dry_run:
            if source_file.exists():
                shutil.copy2(source_file, dest_file)
            else:
                logger.warning(f"Source file not found: {source_file}")
                continue

        # Calculate duration
        duration_ms = sent['end_ms'] - sent['start_ms']

        exported.append({
            'sample_id': sample_id,
            'external_id': external_id,
            'sentence_idx': sentence_idx,
            'final_idx': idx,
            'audio_path': f"audio/{split}/{dest_filename}",
            'transcript': sent['transcript'],
            'translation': sent['translation'],
            'duration_ms': duration_ms,
            'split': split,
        })

    return exported


def create_manifest_files(
    exported: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
    dry_run: bool = False
) -> None:
    """
    Create TSV manifest files for each split.

    Format (HuggingFace compatible):
        audio_path<TAB>transcript<TAB>translation<TAB>duration_ms

    Args:
        exported: Dictionary with split -> sentences mapping.
        output_dir: Output directory.
        dry_run: If True, don't write files.
    """
    for split, sentences in exported.items():
        if not sentences:
            continue

        manifest_path = output_dir / f"{split}.tsv"

        if dry_run:
            logger.info(f"[DRY RUN] Would create {manifest_path} with {len(sentences)} entries")
            continue

        with open(manifest_path, 'w', encoding='utf-8') as f:
            # Header
            f.write("audio_path\ttranscript\ttranslation\tduration_ms\n")

            # Data rows
            for sent in sentences:
                # Escape tabs and newlines in text
                transcript = sent['transcript'].replace('\t', ' ').replace('\n', ' ')
                translation = sent['translation'].replace('\t', ' ').replace('\n', ' ')

                f.write(f"{sent['audio_path']}\t{transcript}\t{translation}\t{sent['duration_ms']}\n")

        logger.info(f"Created manifest: {manifest_path} ({len(sentences)} entries)")


def create_sqlite_db(
    exported: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
    dry_run: bool = False
) -> None:
    """
    Create SQLite database for metadata and filtering.

    Args:
        exported: Dictionary with split -> sentences mapping.
        output_dir: Output directory.
        dry_run: If True, don't create database.
    """
    if dry_run:
        logger.info("[DRY RUN] Would create SQLite database")
        return

    db_dir = output_dir / 'db'
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / 'metadata.sqlite'

    # Remove existing database
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create table
    cursor.execute('''
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT NOT NULL,
            external_id TEXT NOT NULL,
            sentence_idx INTEGER NOT NULL,
            final_idx INTEGER NOT NULL,
            audio_path TEXT NOT NULL,
            transcript TEXT NOT NULL,
            translation TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            split TEXT NOT NULL
        )
    ''')

    # Create indexes
    cursor.execute('CREATE INDEX idx_sample_id ON sentences(sample_id)')
    cursor.execute('CREATE INDEX idx_split ON sentences(split)')
    cursor.execute('CREATE INDEX idx_duration ON sentences(duration_ms)')

    # Insert data
    all_sentences = []
    for split, sentences in exported.items():
        all_sentences.extend(sentences)

    cursor.executemany('''
        INSERT INTO sentences 
        (sample_id, external_id, sentence_idx, final_idx, audio_path, 
         transcript, translation, duration_ms, split)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', [
        (s['sample_id'], s['external_id'], s['sentence_idx'], s['final_idx'],
         s['audio_path'], s['transcript'], s['translation'], s['duration_ms'], s['split'])
        for s in all_sentences
    ])

    conn.commit()
    conn.close()

    logger.info(f"Created SQLite database: {db_path} ({len(all_sentences)} sentences)")


def create_summary_json(
    exported: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
    dry_run: bool = False
) -> None:
    """
    Create summary JSON file with dataset statistics.

    Args:
        exported: Dictionary with split -> sentences mapping.
        output_dir: Output directory.
        dry_run: If True, don't write file.
    """
    if dry_run:
        logger.info("[DRY RUN] Would create summary.json")
        return

    summary = {
        'generated_at': datetime.now().isoformat(),
        'splits': {},
        'totals': {
            'sentences': 0,
            'samples': 0,
            'duration_ms': 0,
        }
    }

    all_samples = set()

    for split, sentences in exported.items():
        if not sentences:
            continue

        split_samples = set(s['sample_id'] for s in sentences)
        split_duration = sum(s['duration_ms'] for s in sentences)

        summary['splits'][split] = {
            'sentences': len(sentences),
            'samples': len(split_samples),
            'duration_ms': split_duration,
            'duration_hours': round(split_duration / 3600000, 2),
        }

        summary['totals']['sentences'] += len(sentences)
        summary['totals']['duration_ms'] += split_duration
        all_samples.update(split_samples)

    summary['totals']['samples'] = len(all_samples)
    summary['totals']['duration_hours'] = round(summary['totals']['duration_ms'] / 3600000, 2)

    summary_path = output_dir / 'summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Created summary: {summary_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Export FINAL samples to training dataset directory.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Export all FINAL samples with default 80:10:10 split
    python export_reviewed.py

    # Export with custom split
    python export_reviewed.py --split 70:15:15

    # Limit number of samples
    python export_reviewed.py --limit 100

    # Dry run to preview
    python export_reviewed.py --dry-run

    # Custom output directory
    python export_reviewed.py --output-dir /path/to/dataset
        """
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of samples to export'
    )
    parser.add_argument(
        '--split',
        type=str,
        default='80:10:10',
        help='Train:Dev:Test split ratio (default: 80:10:10)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f'Output directory (default: {DEFAULT_OUTPUT_DIR})'
    )
    parser.add_argument(
        '--final-root',
        type=Path,
        default=DEFAULT_FINAL_ROOT,
        help=f'Final audio root directory (default: {DEFAULT_FINAL_ROOT})'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for split assignment (default: 42)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview export without writing files'
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
    logger.info("Export Final Samples (v2)")
    logger.info("=" * 60)
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Final audio root: {args.final_root}")
    logger.info(f"Split ratio: {args.split}")
    logger.info(f"Random seed: {args.seed}")
    if args.limit:
        logger.info(f"Limit: {args.limit}")
    if args.dry_run:
        logger.info("DRY RUN MODE - No files will be written")
    logger.info("")

    # Parse split ratio
    try:
        split_ratios = parse_split_ratio(args.split)
    except ValueError as e:
        logger.error(str(e))
        return 1

    # Fetch FINAL samples
    samples = get_final_samples(limit=args.limit)
    logger.info(f"Found {len(samples)} samples in FINAL state")

    if not samples:
        logger.info("No samples to export.")
        return 0

    # Assign splits
    splits = assign_split(samples, split_ratios, seed=args.seed)
    logger.info(f"Split assignment: train={len(splits['train'])}, "
                f"dev={len(splits['dev'])}, test={len(splits['test'])}")

    # Create output directory
    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    # Export sentences by split
    exported = {'train': [], 'dev': [], 'test': []}

    for split_name, split_samples in splits.items():
        logger.info(f"\nExporting {split_name} split ({len(split_samples)} samples)...")

        for sample in split_samples:
            sample_id = str(sample['sample_id'])
            logger.debug(f"  Processing {sample['external_id']}...")

            sentences = export_sample_sentences(
                sample=sample,
                final_root=args.final_root,
                output_dir=args.output_dir,
                split=split_name,
                dry_run=args.dry_run
            )

            exported[split_name].extend(sentences)

        logger.info(f"  Exported {len(exported[split_name])} sentences")

    # Create manifest files
    logger.info("\nCreating manifest files...")
    create_manifest_files(exported, args.output_dir, dry_run=args.dry_run)

    # Create SQLite database
    logger.info("Creating SQLite database...")
    create_sqlite_db(exported, args.output_dir, dry_run=args.dry_run)

    # Create summary
    logger.info("Creating summary...")
    create_summary_json(exported, args.output_dir, dry_run=args.dry_run)

    # Final summary
    total_sentences = sum(len(s) for s in exported.values())
    total_duration_ms = sum(s['duration_ms'] for split in exported.values() for s in split)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Export Complete")
    logger.info("=" * 60)
    logger.info(f"Total samples: {len(samples)}")
    logger.info(f"Total sentences: {total_sentences}")
    logger.info(f"Total duration: {total_duration_ms / 3600000:.2f} hours")
    logger.info(f"  Train: {len(exported['train'])} sentences")
    logger.info(f"  Dev: {len(exported['dev'])} sentences")
    logger.info(f"  Test: {len(exported['test'])} sentences")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

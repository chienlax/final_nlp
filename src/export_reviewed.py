"""
Export reviewed samples to DVC-tracked output directory.

Exports samples that have completed human review into a structured
format suitable for training data preparation.

Output Structure:
    data/reviewed/{task_type}/{sample_id}/
        ├── audio.wav           # Original audio file
        ├── transcript.json     # Final reviewed transcript
        ├── translation.json    # Final reviewed translation (if applicable)
        └── metadata.json       # Sample metadata and review info

Usage:
    python src/export_reviewed.py                    # Export all reviewed samples
    python src/export_reviewed.py --task-type transcript_correction
    python src/export_reviewed.py --limit 100
    python src/export_reviewed.py --dry-run
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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

# Output directory
OUTPUT_DIR = PROJECT_ROOT / 'data' / 'reviewed'


def get_reviewed_samples(
    task_type: Optional[str] = None,
    limit: Optional[int] = None,
    skip_exported: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch samples that have completed human review.

    Args:
        task_type: Filter by annotation task type.
        limit: Maximum number of samples to return.
        skip_exported: Skip samples already exported.

    Returns:
        List of sample dictionaries with review information.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    s.sample_id,
                    s.external_id,
                    s.content_type,
                    s.pipeline_type::TEXT,
                    s.processing_state::TEXT,
                    s.audio_file_path,
                    s.text_file_path,
                    s.duration_seconds,
                    s.cs_ratio,
                    s.source_metadata,
                    s.dvc_commit_hash,
                    s.is_gold_standard,
                    s.gold_score,
                    s.created_at,
                    s.updated_at,
                    -- Latest transcript
                    tr.transcript_text,
                    tr.revision_type AS transcript_revision_type,
                    tr.timestamps AS transcript_timestamps,
                    tr.created_at AS transcript_created_at,
                    tr.created_by AS transcript_created_by,
                    -- Latest translation
                    tl.translation_text,
                    tl.target_language,
                    tl.revision_type AS translation_revision_type,
                    tl.created_at AS translation_created_at,
                    tl.created_by AS translation_created_by,
                    -- Annotation info
                    a.task_type::TEXT,
                    a.completed_at AS annotation_completed_at,
                    a.assigned_to AS annotator_id
                FROM samples s
                LEFT JOIN LATERAL (
                    SELECT * FROM transcript_revisions 
                    WHERE sample_id = s.sample_id 
                    ORDER BY version DESC LIMIT 1
                ) tr ON TRUE
                LEFT JOIN LATERAL (
                    SELECT * FROM translation_revisions 
                    WHERE sample_id = s.sample_id 
                    ORDER BY version DESC LIMIT 1
                ) tl ON TRUE
                LEFT JOIN annotations a ON s.sample_id = a.sample_id 
                    AND a.status = 'completed'
                WHERE s.processing_state = 'REVIEWED'
                  AND s.is_deleted = FALSE
            """

            params = []

            if task_type:
                query += " AND a.task_type = %s::annotation_task"
                params.append(task_type)

            if skip_exported:
                query += " AND NOT COALESCE((s.processing_metadata->>'exported')::BOOLEAN, FALSE)"

            query += " ORDER BY s.updated_at DESC"

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    finally:
        conn.close()


def export_sample(
    sample: Dict[str, Any],
    base_output_dir: Path,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Export a single reviewed sample to the output directory.

    Args:
        sample: Sample dictionary from database.
        base_output_dir: Base output directory.
        dry_run: If True, don't write files.

    Returns:
        Path to exported directory, or None if failed.
    """
    sample_id = str(sample['sample_id'])
    task_type = sample.get('task_type', 'general')
    
    # Create output directory structure
    output_dir = base_output_dir / task_type / sample_id

    if dry_run:
        logger.info(f"[DRY RUN] Would export sample {sample_id} to {output_dir}")
        return output_dir

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy audio file if exists
        if sample.get('audio_file_path'):
            src_audio = PROJECT_ROOT / sample['audio_file_path']
            if src_audio.exists():
                dst_audio = output_dir / 'audio.wav'
                shutil.copy2(src_audio, dst_audio)
                logger.debug(f"  Copied audio: {dst_audio}")
            else:
                logger.warning(f"  Audio file not found: {src_audio}")

        # Export transcript
        if sample.get('transcript_text'):
            transcript_data = {
                'text': sample['transcript_text'],
                'revision_type': sample.get('transcript_revision_type'),
                'timestamps': sample.get('transcript_timestamps'),
                'created_at': _serialize_datetime(sample.get('transcript_created_at')),
                'created_by': sample.get('transcript_created_by'),
            }
            transcript_path = output_dir / 'transcript.json'
            with open(transcript_path, 'w', encoding='utf-8') as f:
                json.dump(transcript_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"  Wrote transcript: {transcript_path}")

        # Export translation
        if sample.get('translation_text'):
            translation_data = {
                'text': sample['translation_text'],
                'target_language': sample.get('target_language'),
                'revision_type': sample.get('translation_revision_type'),
                'created_at': _serialize_datetime(sample.get('translation_created_at')),
                'created_by': sample.get('translation_created_by'),
            }
            translation_path = output_dir / 'translation.json'
            with open(translation_path, 'w', encoding='utf-8') as f:
                json.dump(translation_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"  Wrote translation: {translation_path}")

        # Export metadata
        metadata = {
            'sample_id': sample_id,
            'external_id': sample.get('external_id'),
            'content_type': sample.get('content_type'),
            'pipeline_type': sample.get('pipeline_type'),
            'duration_seconds': float(sample['duration_seconds']) if sample.get('duration_seconds') else None,
            'cs_ratio': float(sample['cs_ratio']) if sample.get('cs_ratio') else None,
            'source_metadata': sample.get('source_metadata'),
            'dvc_commit_hash': sample.get('dvc_commit_hash'),
            'is_gold_standard': sample.get('is_gold_standard', False),
            'gold_score': float(sample['gold_score']) if sample.get('gold_score') else None,
            'annotation': {
                'task_type': task_type,
                'annotator_id': sample.get('annotator_id'),
                'completed_at': _serialize_datetime(sample.get('annotation_completed_at')),
            },
            'exported_at': datetime.now().isoformat(),
        }
        metadata_path = output_dir / 'metadata.json'
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.debug(f"  Wrote metadata: {metadata_path}")

        return output_dir

    except Exception as e:
        logger.error(f"Failed to export sample {sample_id}: {e}")
        return None


def mark_sample_exported(sample_id: str) -> bool:
    """
    Mark a sample as exported in the database.

    Args:
        sample_id: UUID of the sample.

    Returns:
        True if successful.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE samples
                SET processing_metadata = COALESCE(processing_metadata, '{}') || 
                    jsonb_build_object(
                        'exported', TRUE,
                        'exported_at', %s
                    ),
                    updated_at = NOW()
                WHERE sample_id = %s
                """,
                (datetime.now().isoformat(), sample_id)
            )
            conn.commit()
            return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to mark sample {sample_id} as exported: {e}")
        return False
    finally:
        conn.close()


def _serialize_datetime(dt) -> Optional[str]:
    """Convert datetime to ISO string."""
    if dt is None:
        return None
    if hasattr(dt, 'isoformat'):
        return dt.isoformat()
    return str(dt)


def generate_manifest(output_dir: Path) -> Path:
    """
    Generate a manifest file listing all exported samples.

    Args:
        output_dir: Base output directory.

    Returns:
        Path to manifest file.
    """
    manifest = {
        'generated_at': datetime.now().isoformat(),
        'total_samples': 0,
        'task_types': {},
        'samples': [],
    }

    for task_type_dir in output_dir.iterdir():
        if not task_type_dir.is_dir():
            continue

        task_type = task_type_dir.name
        manifest['task_types'][task_type] = 0

        for sample_dir in task_type_dir.iterdir():
            if not sample_dir.is_dir():
                continue

            # Read metadata if exists
            metadata_path = sample_dir / 'metadata.json'
            if metadata_path.exists():
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                manifest['samples'].append({
                    'sample_id': metadata.get('sample_id'),
                    'task_type': task_type,
                    'external_id': metadata.get('external_id'),
                    'duration_seconds': metadata.get('duration_seconds'),
                    'cs_ratio': metadata.get('cs_ratio'),
                    'is_gold_standard': metadata.get('is_gold_standard', False),
                })

                manifest['total_samples'] += 1
                manifest['task_types'][task_type] += 1

    manifest_path = output_dir / 'manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"Generated manifest: {manifest_path}")
    return manifest_path


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Export reviewed samples to DVC-tracked output directory.'
    )
    parser.add_argument(
        '--task-type',
        choices=['transcript_verification', 'timestamp_alignment', 
                 'translation_review', 'quality_assessment'],
        help='Filter by annotation task type'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of samples to export'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=OUTPUT_DIR,
        help=f'Output directory (default: {OUTPUT_DIR})'
    )
    parser.add_argument(
        '--include-exported',
        action='store_true',
        help='Include samples that have already been exported'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview export without writing files'
    )
    parser.add_argument(
        '--no-manifest',
        action='store_true',
        help='Skip manifest generation'
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
    logger.info("Export Reviewed Samples")
    logger.info("=" * 60)
    logger.info(f"Output directory: {args.output_dir}")
    if args.task_type:
        logger.info(f"Task type filter: {args.task_type}")
    if args.limit:
        logger.info(f"Limit: {args.limit}")
    if args.dry_run:
        logger.info("DRY RUN MODE - No files will be written")
    logger.info("")

    # Fetch reviewed samples
    samples = get_reviewed_samples(
        task_type=args.task_type,
        limit=args.limit,
        skip_exported=not args.include_exported,
    )

    logger.info(f"Found {len(samples)} reviewed samples to export")

    if not samples:
        logger.info("No samples to export.")
        return 0

    # Export each sample
    stats = {'exported': 0, 'failed': 0}

    for sample in samples:
        sample_id = str(sample['sample_id'])
        logger.info(f"Exporting {sample_id}...")

        output_path = export_sample(
            sample=sample,
            base_output_dir=args.output_dir,
            dry_run=args.dry_run,
        )

        if output_path:
            stats['exported'] += 1
            # Mark as exported (unless dry run)
            if not args.dry_run:
                mark_sample_exported(sample_id)
        else:
            stats['failed'] += 1

    # Generate manifest
    if not args.dry_run and not args.no_manifest:
        generate_manifest(args.output_dir)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Export complete: {stats['exported']} exported, {stats['failed']} failed")
    logger.info("=" * 60)

    return 0 if stats['failed'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

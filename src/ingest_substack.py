"""
Substack ingestion orchestrator for the NLP pipeline.

Downloads articles from Substack blogs and ingests them into the database
for the text-first processing pipeline.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.data_utils import (
    get_pg_connection,
    get_or_create_source,
    insert_sample,
    insert_transcript_revision,
    log_processing,
)
from utils.substack_utils import (
    extract_blog_slug,
    list_downloaded_articles,
    run_downloader,
)
from utils.text_utils import (
    contains_code_switching,
    extract_cs_chunks,
    load_teencode_dict,
    normalize_text,
)


# Constants
DEFAULT_DOWNLOAD_DIR = Path("data/substack_downloads")
DEFAULT_URLS_FILE = Path("data/substack_urls.txt")
DEFAULT_TEENCODE_FILE = Path("data/teencode.txt")


def load_urls_from_file(file_path: Path) -> List[str]:
    """
    Load Substack URLs from a file.

    Args:
        file_path: Path to URLs file (one URL per line).

    Returns:
        List of valid URLs.
    """
    if not file_path.exists():
        print(f"Error: URLs file not found at {file_path}")
        return []

    urls: List[str] = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and 'substack.com' in line:
                    urls.append(line)
    except Exception as e:
        print(f"Error reading URLs file: {e}")

    return urls


def process_article(
    article_path: Path,
    source_url: str,
    teencode_dict: dict,
    conn,
    dry_run: bool = False
) -> Optional[int]:
    """
    Process a single downloaded article and ingest into database.

    Args:
        article_path: Path to article markdown file.
        source_url: Original Substack URL.
        teencode_dict: Teencode replacement dictionary.
        conn: Database connection.
        dry_run: If True, don't commit to database.

    Returns:
        Sample ID if successful, None otherwise.
    """
    try:
        # Read article content
        with open(article_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()

        if not raw_content.strip():
            print(f"  Skipping empty article: {article_path.name}")
            return None

        # Extract title from first line (usually # Title)
        lines = raw_content.strip().split('\n')
        title = article_path.stem
        if lines and lines[0].startswith('#'):
            title = lines[0].lstrip('#').strip()

        # Normalize text
        normalized_content = normalize_text(
            raw_content,
            teencode_dict=teencode_dict,
            lowercase=False,  # Keep original case for readability
            remove_urls=True,
            remove_emojis=True
        )

        # Check for code-switching
        has_cs = contains_code_switching(normalized_content)

        # Extract blog slug for source
        blog_slug = extract_blog_slug(source_url)

        if dry_run:
            print(f"  [DRY RUN] Would ingest: {title}")
            print(f"    - Blog: {blog_slug}")
            print(f"    - Has CS: {has_cs}")
            print(f"    - Content length: {len(raw_content)} chars")
            return None

        # Get or create source
        source_id = get_or_create_source(
            conn=conn,
            source_type='substack',
            external_id=source_url,
            source_url=source_url,
            metadata={'blog_slug': blog_slug, 'title': title}
        )

        # Insert sample (text-first, no audio)
        sample_id = insert_sample(
            conn=conn,
            source_id=source_id,
            content_type='text',
            pipeline_type='substack',
            file_path=str(article_path.resolve()),
            metadata={
                'title': title,
                'blog_slug': blog_slug,
                'has_code_switching': has_cs,
                'download_date': datetime.now().isoformat(),
            }
        )

        if sample_id:
            # Insert initial transcript revision (the raw text)
            insert_transcript_revision(
                conn=conn,
                sample_id=sample_id,
                transcript_text=raw_content,
                revision_type='original',
                confidence_score=1.0,
                metadata={
                    'source': 'substack_download',
                    'normalized_length': len(normalized_content),
                }
            )

            # Log processing step
            log_processing(
                conn=conn,
                sample_id=sample_id,
                step_name='ingestion',
                status='success',
                input_state='raw',
                output_state='raw',
                metadata={'source_file': str(article_path.name)}
            )

            print(f"  Ingested: {title} (ID: {sample_id})")
            return sample_id

    except Exception as e:
        print(f"  Error processing {article_path.name}: {e}")
        return None

    return None


def ingest_substack(
    urls: Optional[List[str]] = None,
    urls_file: Optional[Path] = None,
    download_dir: Optional[Path] = None,
    teencode_file: Optional[Path] = None,
    skip_download: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None
) -> dict:
    """
    Main entry point for Substack ingestion.

    Args:
        urls: List of Substack URLs to process.
        urls_file: Path to file containing URLs.
        download_dir: Directory for downloaded articles.
        teencode_file: Path to teencode dictionary.
        skip_download: Skip download step (process existing files).
        dry_run: Don't commit to database.
        limit: Maximum number of articles to process.

    Returns:
        Dictionary with ingestion statistics.
    """
    # Set defaults
    download_dir = download_dir or DEFAULT_DOWNLOAD_DIR
    teencode_file = teencode_file or DEFAULT_TEENCODE_FILE

    # Load URLs
    if urls is None:
        urls_file = urls_file or DEFAULT_URLS_FILE
        urls = load_urls_from_file(urls_file)

    if not urls and not skip_download:
        print("No URLs provided. Use --urls-file or --skip-download with existing files.")
        return {'error': 'No URLs provided', 'processed': 0}

    # Load teencode dictionary
    print(f"Loading teencode dictionary from {teencode_file}...")
    teencode_dict = load_teencode_dict(teencode_file)
    print(f"Loaded {len(teencode_dict)} teencode mappings.")

    # Download articles if not skipping
    if not skip_download:
        print(f"\nDownloading articles to {download_dir}...")
        for url in urls:
            print(f"  Downloading from: {url}")
            downloaded = run_downloader(
                urls=[url],
                output_dir=download_dir
            )
            if not downloaded:
                print(f"    Warning: Download may have failed for {url}")

    # List downloaded articles
    article_dicts = list_downloaded_articles(download_dir)
    articles = [Path(a['file_path']) for a in article_dicts]
    print(f"\nFound {len(articles)} articles to process.")

    if limit:
        articles = articles[:limit]
        print(f"Limited to {limit} articles.")

    # Connect to database
    stats = {
        'total': len(articles),
        'processed': 0,
        'ingested': 0,
        'skipped': 0,
        'errors': 0,
    }

    if dry_run:
        print("\n[DRY RUN MODE - No database changes will be made]")

    try:
        conn = get_pg_connection() if not dry_run else None

        for i, article_path in enumerate(articles):
            print(f"\n[{i + 1}/{len(articles)}] Processing: {article_path.name}")
            stats['processed'] += 1

            # Try to match article to URL (approximate matching)
            matched_url = None
            article_slug = article_path.stem.lower()
            for url in urls:
                if article_slug in url.lower():
                    matched_url = url
                    break

            if not matched_url:
                # Use generic URL based on blog structure
                matched_url = f"https://unknown.substack.com/p/{article_path.stem}"

            sample_id = process_article(
                article_path=article_path,
                source_url=matched_url,
                teencode_dict=teencode_dict,
                conn=conn,
                dry_run=dry_run
            )

            if sample_id:
                stats['ingested'] += 1
            elif dry_run:
                stats['ingested'] += 1  # Count as success in dry run
            else:
                stats['skipped'] += 1

        if conn:
            conn.close()

    except Exception as e:
        print(f"\nDatabase error: {e}")
        stats['errors'] += 1

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Ingest Substack articles into the NLP pipeline database.'
    )
    parser.add_argument(
        '--urls-file',
        type=Path,
        default=DEFAULT_URLS_FILE,
        help='Path to file containing Substack URLs (one per line)'
    )
    parser.add_argument(
        '--download-dir',
        type=Path,
        default=DEFAULT_DOWNLOAD_DIR,
        help='Directory for downloaded articles'
    )
    parser.add_argument(
        '--teencode-file',
        type=Path,
        default=DEFAULT_TEENCODE_FILE,
        help='Path to teencode dictionary file'
    )
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Skip download step and process existing files'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without committing to database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of articles to process'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Substack Ingestion Pipeline")
    print("=" * 60)

    stats = ingest_substack(
        urls_file=args.urls_file,
        download_dir=args.download_dir,
        teencode_file=args.teencode_file,
        skip_download=args.skip_download,
        dry_run=args.dry_run,
        limit=args.limit
    )

    print("\n" + "=" * 60)
    print("Ingestion Summary")
    print("=" * 60)
    print(f"Total articles found: {stats.get('total', 0)}")
    print(f"Articles processed:   {stats.get('processed', 0)}")
    print(f"Articles ingested:    {stats.get('ingested', 0)}")
    print(f"Articles skipped:     {stats.get('skipped', 0)}")
    print(f"Errors:               {stats.get('errors', 0)}")


if __name__ == "__main__":
    main()

"""
Substack downloading utilities.

Downloads blog posts from Substack using Python requests and BeautifulSoup,
following the project's data requirements for text-first pipeline.

.. deprecated::
    This module is deprecated as of v3. The project now focuses exclusively
    on YouTube videos with transcripts. This file is kept for reference only.
    See `ingest_youtube_v3.py` and `utils/data_utils_v3.py` for the current
    workflow.
"""

import warnings
warnings.warn(
    "substack_utils.py is deprecated. The Substack/TTS pipeline has been "
    "removed in v3. Use the YouTube-only workflow instead.",
    DeprecationWarning,
    stacklevel=2
)

import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup


# Project constants
OUTPUT_DIR = Path("data/raw/text/substack")
URLS_FILE = Path("data/substack_urls.txt")


def sanitize_filename(text: str, max_length: int = 100) -> str:
    """
    Sanitize a string to be used as a filename.

    Args:
        text: The text to sanitize.
        max_length: Maximum length of the resulting filename.

    Returns:
        Sanitized filename string.
    """
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', text)
    # Replace spaces and multiple dashes with single dash
    sanitized = re.sub(r'[\s_]+', '-', sanitized)
    sanitized = re.sub(r'-+', '-', sanitized)
    # Remove leading/trailing dashes
    sanitized = sanitized.strip('-')
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rsplit('-', 1)[0]

    return sanitized.lower()


def extract_blog_slug(url: str) -> str:
    """
    Extract the blog slug from a Substack URL.

    Handles both substack.com domains and custom domains.

    Args:
        url: Substack blog URL (e.g., https://myblog.substack.com or custom domain).

    Returns:
        Blog slug (e.g., 'myblog' or domain name for custom domains).
    """
    # Handle standard substack.com format:
    # https://myblog.substack.com
    # https://www.myblog.substack.com
    pattern = r'https?://(?:www\.)?([^.]+)\.substack\.com'
    match = re.match(pattern, url.strip())

    if match:
        return match.group(1)

    # Handle custom domains (e.g., https://www.brainhealthdecoded.com)
    custom_pattern = r'https?://(?:www\.)?([^/]+)'
    custom_match = re.match(custom_pattern, url.strip())
    if custom_match:
        domain = custom_match.group(1)
        # Remove .com, .org, etc.
        domain_slug = domain.split('.')[0]
        return sanitize_filename(domain_slug)

    # Fallback: use sanitized URL
    return sanitize_filename(url.replace('https://', '').replace('http://', ''))


def _download_single_article(url: str, output_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Download a single Substack article using requests and BeautifulSoup.

    Args:
        url: URL of the Substack article.
        output_dir: Directory to save the downloaded article.

    Returns:
        Metadata dictionary for the downloaded article, or None if failed.
    """
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(response.text, 'lxml')

    # Extract title
    title_elem = soup.find('h1', class_='post-title')
    if not title_elem:
        title_elem = soup.find('h1')
    title = title_elem.get_text(strip=True) if title_elem else "Untitled"

    # Extract article content
    # Substack uses different class names, try multiple selectors
    content_elem = soup.find('div', class_='body')
    if not content_elem:
        content_elem = soup.find('div', class_='post-content')
    if not content_elem:
        content_elem = soup.find('article')

    if not content_elem:
        print(f"  [WARNING] Could not find article content for {url}")
        return None

    # Extract text content, preserving some structure
    content_parts = []
    content_parts.append(f"# {title}\n")

    for elem in content_elem.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote']):
        text = elem.get_text(strip=True)
        if text:
            if elem.name.startswith('h'):
                level = int(elem.name[1])
                content_parts.append(f"\n{'#' * level} {text}\n")
            elif elem.name == 'li':
                content_parts.append(f"• {text}")
            elif elem.name == 'blockquote':
                content_parts.append(f"> {text}")
            else:
                content_parts.append(text)

    content = '\n\n'.join(content_parts)

    # Generate filename from title
    article_slug = sanitize_filename(title)
    if not article_slug:
        article_slug = 'article'

    # Save to file
    output_file = output_dir / f"{article_slug}.txt"
    output_file.write_text(content, encoding='utf-8')

    blog_slug = extract_blog_slug(url)

    return {
        'id': f"{blog_slug}_{article_slug}",
        'type': 'substack',
        'blog_slug': blog_slug,
        'article_slug': article_slug,
        'title': title,
        'url': url,
        'file_path': str(output_file),
        'captured_at': datetime.now().strftime('%Y-%m-%d'),
    }


def run_downloader(
    urls: Optional[List[str]] = None,
    urls_file: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Download Substack blog posts using Python requests.

    Reads URLs from a file or list and downloads each article.
    Output files are saved to the specified directory.

    Args:
        urls: List of Substack article URLs to download.
        urls_file: Path to file containing URLs (one per line).
        output_dir: Directory to save downloaded files.

    Returns:
        List of metadata dictionaries for downloaded articles.

    Raises:
        FileNotFoundError: If urls_file doesn't exist and urls not provided.
    """
    # Use defaults if not specified
    if output_dir is None:
        output_dir = OUTPUT_DIR

    # Load URLs from file if not provided directly
    if urls is None:
        if urls_file is None:
            urls_file = URLS_FILE

        if not urls_file.exists():
            raise FileNotFoundError(
                f"URLs file not found: {urls_file}. "
                "Please create it with Substack URLs (one per line)."
            )

        urls = [
            line.strip() for line in urls_file.read_text().splitlines()
            if line.strip() and not line.startswith('#')
        ]

    if not urls:
        print("No URLs to process.")
        return []

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(urls)} URL(s) to process.")
    downloaded_articles: List[Dict[str, Any]] = []

    for url in urls:
        blog_slug = extract_blog_slug(url)
        blog_output_dir = output_dir / blog_slug
        blog_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 40}")
        print(f"Downloading from: {url}")
        print(f"Output directory: {blog_output_dir}")
        print("=" * 40)

        article_metadata = _download_single_article(url, blog_output_dir)
        if article_metadata:
            downloaded_articles.append(article_metadata)
            print(f"  [SUCCESS] Downloaded: {article_metadata['title']}")
        else:
            print(f"  [FAILED] Could not download article from {url}")

    print(f"\nDownload complete. {len(downloaded_articles)} articles downloaded.")
    return downloaded_articles


def get_article_content(file_path: Path) -> str:
    """
    Read and return the content of a downloaded article.

    Args:
        file_path: Path to the text file.

    Returns:
        Article content as string.
    """
    return file_path.read_text(encoding='utf-8')


def list_downloaded_articles(output_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    List all downloaded articles in the output directory.

    Args:
        output_dir: Directory containing downloaded articles.

    Returns:
        List of metadata dictionaries for all articles.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR

    if not output_dir.exists():
        return []

    articles: List[Dict[str, Any]] = []

    for blog_dir in output_dir.iterdir():
        if not blog_dir.is_dir():
            continue

        blog_slug = blog_dir.name

        for txt_file in blog_dir.glob("*.txt"):
            article_slug = txt_file.stem
            articles.append({
                'id': f"{blog_slug}_{article_slug}",
                'type': 'substack',
                'blog_slug': blog_slug,
                'article_slug': article_slug,
                'file_path': str(txt_file),
            })

    return articles


if __name__ == "__main__":
    import sys

    # If URLs provided as arguments, use them; otherwise read from file
    if len(sys.argv) > 1:
        input_urls = sys.argv[1:]
        print(f"Processing {len(input_urls)} URL(s) from command line...")
        run_downloader(urls=input_urls)
    else:
        print(f"Reading URLs from {URLS_FILE}...")
        run_downloader()

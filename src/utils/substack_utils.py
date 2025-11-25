"""
Substack downloading utilities.

Downloads blog posts from Substack using sbstck-dl tool,
following the project's data requirements for text-first pipeline.
"""

import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


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

    Args:
        url: Substack blog URL (e.g., https://myblog.substack.com).

    Returns:
        Blog slug (e.g., 'myblog').
    """
    # Handle both formats:
    # https://myblog.substack.com
    # https://www.myblog.substack.com
    pattern = r'https?://(?:www\.)?([^.]+)\.substack\.com'
    match = re.match(pattern, url.strip())

    if match:
        return match.group(1)

    # Fallback: use sanitized URL
    return sanitize_filename(url.replace('https://', '').replace('http://', ''))


def run_downloader(
    urls: Optional[List[str]] = None,
    urls_file: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Download Substack blog posts using sbstck-dl.

    Reads URLs from a file or list and runs sbstck-dl for each.
    Output files are saved to the specified directory.

    Args:
        urls: List of Substack URLs to download.
        urls_file: Path to file containing URLs (one per line).
        output_dir: Directory to save downloaded files.

    Returns:
        List of metadata dictionaries for downloaded articles.

    Raises:
        FileNotFoundError: If urls_file doesn't exist and urls not provided.
        RuntimeError: If sbstck-dl is not installed.
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

        command = [
            "sbstck-dl",
            "download",
            "-u", url,
            "-f", "txt",
            "-o", str(blog_output_dir),
        ]

        try:
            result = subprocess.run(
                command,
                check=True,
                shell=True,
                capture_output=True,
                text=True
            )
            print(f"[SUCCESS] Downloaded from {url}")

            # Collect metadata for newly downloaded files
            for txt_file in blog_output_dir.glob("*.txt"):
                article_slug = txt_file.stem
                article_metadata = {
                    'id': f"{blog_slug}_{article_slug}",
                    'type': 'substack',
                    'blog_slug': blog_slug,
                    'article_slug': article_slug,
                    'url': url,
                    'file_path': str(txt_file),
                    'captured_at': datetime.now().strftime('%Y-%m-%d'),
                }
                downloaded_articles.append(article_metadata)

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to download from {url}: {e}")
            if e.stderr:
                print(f"  stderr: {e.stderr}")

        except FileNotFoundError:
            raise RuntimeError(
                "sbstck-dl command not found. "
                "Please install it: go install github.com/alexferrari88/sbstck-dl@latest"
            )

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

"""
Video downloading utilities for YouTube audio extraction.

Downloads YouTube videos as 16kHz mono WAV files, following the project's
audio specification for speech translation processing.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import yt_dlp

# Project constants
SAMPLE_RATE = 16000  # 16kHz as per data requirements
CHANNELS = 1  # Mono
MIN_DURATION = 120  # 2 minutes in seconds
MAX_DURATION = 7200  # 120 minutes in seconds

# Output directories (relative to project root)
OUTPUT_DIR = Path("data/raw/audio")
METADATA_FILE = Path("data/raw/metadata.jsonl")

# Global list to store video data for JSONL output
downloaded_videos_log: List[Dict[str, Any]] = []


def _duration_filter(info_dict: Dict[str, Any], *, incomplete: bool) -> Optional[str]:
    """
    Filter function for yt-dlp to skip videos outside 2-60 minute range.

    Args:
        info_dict: Video metadata dictionary from yt-dlp.
        incomplete: Whether the info_dict is incomplete (pre-extraction).

    Returns:
        None if video passes filter, error message string if rejected.
    """
    duration = info_dict.get('duration')
    if duration is None:
        return None  # Allow if duration unknown (will be checked post-download)

    if duration < MIN_DURATION:
        return f"Video too short: {duration}s < {MIN_DURATION}s (2 min)"
    if duration > MAX_DURATION:
        return f"Video too long: {duration}s > {MAX_DURATION}s (60 min)"
    return None


def progress_hook(d: Dict[str, Any]) -> None:
    """
    Callback function during download process.

    Captures metadata when a download finishes (before post-processing).

    Args:
        d: Progress dictionary from yt-dlp containing status and info.
    """
    if d['status'] == 'finished':
        info = d.get('info_dict', {})

        video_id = info.get('id', 'unknown')
        channel_id = info.get('channel_id', 'unknown')
        # Capture channel display name (try 'channel' first, fallback to 'uploader')
        channel_name = info.get('channel', info.get('uploader', ''))
        duration = info.get('duration', 0)

        # Construct metadata following the required JSONL schema
        video_data = {
            'id': video_id,
            'type': 'youtube',
            'url': info.get('webpage_url', ''),
            'duration': duration,
            'language_tags': ['vi', 'en'],  # Default for CS corpus
            'captured_at': datetime.now().strftime('%Y-%m-%d'),
            # Extended metadata for source_metadata JSONB
            'channel_id': channel_id,
            'channel_name': channel_name,  # YouTube channel display name
            'upload_date': info.get('upload_date', ''),
            'title': info.get('title', ''),
            # Acoustic metadata for acoustic_meta JSONB
            'acoustic_meta': {
                'sample_rate': SAMPLE_RATE,
                'channels': CHANNELS,
                'format': 'wav'
            },
            # File path relative to project root
            'file_path': str(OUTPUT_DIR / f"{video_id}.wav")
        }

        downloaded_videos_log.append(video_data)


def download_channels(url_list: List[str], download_transcript: bool = False) -> None:
    """
    Download audio from YouTube channels/videos as 16kHz mono WAV files.

    Uses FFmpeg for audio extraction and conversion to meet project specs:
    - Format: WAV
    - Sample Rate: 16kHz
    - Channels: Mono
    - Duration: 2-60 minutes (filtered)

    Args:
        url_list: List of YouTube channel or video URLs to download.
        download_transcript: If True, download manual Vietnamese transcripts (no auto-generated).
    """
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Base options
    ydl_opts = {
        # Format: Best Audio (Original)
        'format': 'bestaudio/best',

        # Duration filter: 2-60 minutes
        'match_filter': _duration_filter,

        # Post-processing: Extract audio and convert to 16kHz mono WAV
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            },
            {
                # Second pass: Resample to 16kHz mono
                'key': 'FFmpegMetadata',
            },
        ],

        # FFmpeg arguments for 16kHz mono conversion
        'postprocessor_args': {
            'ffmpeg': ['-ar', str(SAMPLE_RATE), '-ac', str(CHANNELS)],
        },

        # Output template: data/raw/audio/{video_id}.wav
        'outtmpl': str(OUTPUT_DIR / '%(id)s.%(ext)s'),

        # Add the hook to capture metadata
        'progress_hooks': [progress_hook],

        'ignoreerrors': True,
        'verbose': True,
    }

    # Add transcript options if requested
    if download_transcript:
        ydl_opts.update({
            'writesubtitles': True,
            'writeautomaticsub': False,  # STRICTLY Manual captions only (no auto-generated)
            'subtitleslangs': ['vi'],    # STRICTLY Vietnamese only
            'subtitlesformat': 'json3/vtt',  # Prefer JSON or VTT
        })

    # Run the download
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(url_list)


def fetch_playlist_metadata(url: str) -> List[Dict[str, Any]]:
    """
    Fetch metadata for a playlist or channel without downloading.
    
    Used for the GUI to list videos before downloading.
    
    Args:
        url: YouTube playlist, channel, or video URL.
        
    Returns:
        List of dictionaries containing video metadata (id, title, date, duration).
    """
    ydl_opts = {
        'extract_flat': 'in_playlist', # Extract video details but don't download
        'dump_single_json': True,
        'ignoreerrors': True,
        'quiet': True,
    }
    
    results = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return []
                
            # If it's a single video, info is the dict
            if 'entries' not in info:
                results.append(info)
            else:
                # It's a playlist/channel
                for entry in info['entries']:
                    if entry:
                        results.append(entry)
                        
    except Exception as e:
        print(f"Error fetching metadata: {e}")
        return []
        
    return results


def save_jsonl(append: bool = True) -> None:
    """
    Save downloaded video metadata to JSONL file.

    Creates/updates metadata.jsonl following the project's handover format.
    Supports append mode for incremental downloads with deduplication.

    Args:
        append: If True, append to existing file and deduplicate by video ID.
                If False, overwrite the file.
    """
    if not downloaded_videos_log:
        print("\nNo new videos were downloaded, so no metadata was generated.")
        return

    # Ensure parent directory exists
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing_data: Dict[str, Dict[str, Any]] = {}

    # Load existing metadata if appending
    if append and METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        existing_data[entry['id']] = entry
            print(f"Loaded {len(existing_data)} existing entries from {METADATA_FILE}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse existing metadata: {e}")

    # Merge new data (overwrites duplicates)
    for video in downloaded_videos_log:
        existing_data[video['id']] = video

    # Write all data
    print(f"\nWriting metadata to {METADATA_FILE}...")

    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            for entry in existing_data.values():
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        print(f"Successfully saved {len(existing_data)} entries to {METADATA_FILE.absolute()}")
    except Exception as e:
        print(f"Failed to save metadata: {e}")


if __name__ == "__main__":
    # Capture all arguments after the script name
    input_urls = sys.argv[1:]

    if len(input_urls) < 1:
        print("Usage: python video_downloading_utils.py <url1> <url2> ...")
        print("\nDownloads YouTube audio as 16kHz mono WAV files.")
        print("Only downloads videos between 2-60 minutes in duration.")
        sys.exit(1)

    print(f"Processing {len(input_urls)} URL(s)...")
    print(f"Output directory: {OUTPUT_DIR.absolute()}")

    # 1. Download
    download_channels(input_urls)

    # 2. Generate JSONL metadata
    save_jsonl(append=True)
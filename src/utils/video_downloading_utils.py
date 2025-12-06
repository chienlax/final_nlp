"""
Video downloading utilities for YouTube audio extraction.
"""

import json
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import yt_dlp

# Project constants
# Note: We still default to 16kHz for pipeline compatibility, 
# even if container is m4a
SAMPLE_RATE = 16000  
CHANNELS = 1 

# Output directories
OUTPUT_DIR = Path("data/raw/audio")
METADATA_FILE = Path("data/raw/metadata.jsonl")

# Global list to store video data for JSONL output
downloaded_videos_log: List[Dict[str, Any]] = []


def progress_hook(d: Dict[str, Any]) -> None:
    """Callback to capture metadata when download finishes."""
    if d['status'] == 'finished':
        info = d.get('info_dict', {})
        
        # Capture filename from yt-dlp (handling m4a/wav extensions)
        filename = Path(d['filename']).name
        
        video_data = {
            'id': info.get('id'),
            'type': 'youtube',
            'url': info.get('webpage_url', ''),
            'duration': info.get('duration', 0),
            'language_tags': ['vi', 'en'],
            'captured_at': datetime.now().strftime('%Y-%m-%d'),
            'channel_name': info.get('channel', info.get('uploader', '')),
            'title': info.get('title', ''),
            'file_path': str(OUTPUT_DIR / filename)
        }
        downloaded_videos_log.append(video_data)


def download_youtube_content(
    urls: List[str], 
    download_transcript: bool = True,
    force_m4a: bool = True
) -> List[str]:
    """
    Download content from YouTube (Single, Playlist, or Channel).
    
    Args:
        urls: List of YouTube URLs.
        download_transcript: If True, fetch ONLY manual Vietnamese transcripts.
        force_m4a: If True, download best audio as m4a.
    
    Returns:
        List of downloaded video IDs.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Configure yt-dlp options based on user requirements
    ydl_opts = {
        # Audio Format: Best audio, preferring m4a if requested
        'format': 'bestaudio[ext=m4a]/bestaudio' if force_m4a else 'bestaudio/best',
        
        # Path template
        'outtmpl': str(OUTPUT_DIR / '%(id)s.%(ext)s'),
        
        # Transcript Options
        'writesubtitles': download_transcript,
        'subtitleslangs': ['vi'],       # Only Vietnamese
        'writeautomaticsub': False,     # STRICTLY no auto-generated subs
        
        # Post-processing
        'postprocessors': [],
        
        # Metadata & Logging
        'progress_hooks': [progress_hook],
        'ignoreerrors': True,
        'quiet': False,
        'no_warnings': False,
    }

    # If we need to ensure audio is "original" (not dubbed), yt-dlp's default 
    # 'bestaudio' usually grabs the primary track.
    
    # Add audio conversion if strictly needed for pipeline (optional)
    # This ensures 16kHz mono even if container is m4a
    ydl_opts['postprocessors'].append({
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a' if force_m4a else 'wav',
    })

    # Clear previous logs
    downloaded_videos_log.clear()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(urls)
        
    # Save metadata
    save_jsonl(append=True)
    
    return [v['id'] for v in downloaded_videos_log]


def save_jsonl(append: bool = True) -> None:
    """Save downloaded video metadata to JSONL file."""
    if not downloaded_videos_log:
        return

    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_data = {}

    if append and METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        existing_data[entry['id']] = entry
        except Exception:
            pass

    for video in downloaded_videos_log:
        existing_data[video['id']] = video

    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        for entry in existing_data.values():
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
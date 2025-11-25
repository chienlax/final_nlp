"""
Transcript downloading utilities for YouTube videos.

Downloads YouTube transcripts with subtitle type detection (Manual vs Auto-generated),
following the project's data requirements for speech translation.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Output directories (relative to project root)
METADATA_FILE = Path("data/raw/metadata.jsonl")
TEXT_OUTPUT_DIR = Path("data/raw/text")


def get_transcript_info(video_id: str) -> Dict[str, Any]:
    """
    Fetch transcript with subtitle type detection.

    Checks if the transcript is manually created or auto-generated,
    and avoids auto-translated tracks as per data requirements.

    Args:
        video_id: YouTube video ID.

    Returns:
        Dictionary containing:
            - text: The transcript text (or None if unavailable)
            - subtitle_type: 'Manual', 'Auto-generated', or 'Not Available'
            - language: Language code of the transcript
            - error: Error message if failed (or None)
    """
    result = {
        'text': None,
        'subtitle_type': 'Not Available',
        'language': None,
        'error': None
    }

    try:
        # First, list all available transcripts to detect type
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try to find English transcript (manual first, then auto-generated)
        transcript = None

        # Priority 1: Manual English transcript
        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
            result['subtitle_type'] = 'Manual'
        except NoTranscriptFound:
            pass

        # Priority 2: Auto-generated English transcript
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
                result['subtitle_type'] = 'Auto-generated'
            except NoTranscriptFound:
                pass

        # Priority 3: Try Vietnamese transcripts
        if transcript is None:
            try:
                transcript = transcript_list.find_manually_created_transcript(['vi'])
                result['subtitle_type'] = 'Manual'
            except NoTranscriptFound:
                pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(['vi'])
                result['subtitle_type'] = 'Auto-generated'
            except NoTranscriptFound:
                pass

        if transcript is None:
            result['error'] = 'No English or Vietnamese transcript found'
            result['subtitle_type'] = 'Not Available'
            return result

        # Fetch the transcript content
        result['language'] = transcript.language_code
        transcript_data = transcript.fetch()

        # Format as plain text
        formatter = TextFormatter()
        result['text'] = formatter.format_transcript(transcript_data)

    except TranscriptsDisabled:
        result['error'] = 'Transcripts are disabled for this video'
        result['subtitle_type'] = 'Not Available'
    except Exception as e:
        result['error'] = str(e)
        result['subtitle_type'] = 'Error'

    return result


def download_transcripts_from_metadata() -> List[Dict[str, Any]]:
    """
    Download transcripts for all videos in metadata.jsonl.

    Reads video IDs from the metadata file, downloads transcripts,
    and updates the metadata with subtitle type information.

    Returns:
        List of updated metadata entries with transcript information.
    """
    # Validation
    if not METADATA_FILE.exists():
        print(f"Error: {METADATA_FILE} not found. Run video downloader first.")
        return []

    # Ensure text output directory exists
    TEXT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading metadata from {METADATA_FILE}...")

    # Load existing metadata
    metadata_entries: List[Dict[str, Any]] = []
    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                metadata_entries.append(json.loads(line))

    print(f"Processing {len(metadata_entries)} videos for transcripts...\n")

    # Process each entry
    for entry in metadata_entries:
        video_id = entry.get('id')
        if not video_id:
            continue

        transcript_filename = f"{video_id}_transcript.txt"
        file_path = TEXT_OUTPUT_DIR / transcript_filename

        # Check if we already have this transcript
        if file_path.exists():
            print(f"[EXISTS] Skipping: {transcript_filename}")
            # Ensure metadata has transcript info
            if 'transcript_file' not in entry:
                entry['transcript_file'] = str(file_path)
            continue

        # Fetch transcript with type detection
        transcript_info = get_transcript_info(video_id)

        # Update entry with transcript metadata
        entry['subtitle_type'] = transcript_info['subtitle_type']
        entry['transcript_language'] = transcript_info['language']

        if transcript_info['text']:
            # Save transcript to file
            with open(file_path, 'w', encoding='utf-8') as text_file:
                text_file.write(transcript_info['text'])

            entry['transcript_file'] = str(file_path)
            print(f"[SUCCESS] {transcript_info['subtitle_type']}: {transcript_filename}")
        else:
            entry['transcript_file'] = None
            print(f"[MISSING] {video_id}: {transcript_info['error']}")

    # Update metadata file with transcript information
    print(f"\nUpdating {METADATA_FILE} with transcript metadata...")

    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            for entry in metadata_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        print("Metadata update complete.")
    except PermissionError:
        print(f"Error: Could not write to {METADATA_FILE}. Is it open?")

    return metadata_entries


if __name__ == "__main__":
    download_transcripts_from_metadata()
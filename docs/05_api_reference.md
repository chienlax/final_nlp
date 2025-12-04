# API Reference

Developer documentation for scripts and utility modules.

---

## Table of Contents

1. [Core Modules](#1-core-modules)
2. [Ingestion](#2-ingestion)
3. [Preprocessing](#3-preprocessing)
4. [Review & Export](#4-review--export)
5. [Utilities](#5-utilities)

---

## 1. Core Modules

### db.py

**Location:** `src/db.py`

**Purpose:** SQLite database utilities with connection management, CRUD operations, and query helpers.

#### Connection Management

```python
from db import get_connection, get_db

# Context manager (auto-commit/rollback)
with get_db() as db:
    db.execute("INSERT INTO videos ...")

# Direct connection (manual management)
conn = get_connection()
cursor = conn.cursor()
# ... operations ...
conn.close()

# Read-only mode
with get_db(read_only=True) as db:
    cursor = db.execute("SELECT * FROM videos")
```

#### Configuration

```python
# Constants
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "lab_data.db"
SCHEMA_PATH = PROJECT_ROOT / "init_scripts" / "sqlite_schema.sql"
MAX_SEGMENT_DURATION_MS = 25000  # 25 seconds warning threshold

# Connection settings (applied automatically)
# - WAL mode for better concurrency
# - busy_timeout=5000 for lock handling
# - foreign_keys=ON for referential integrity
# - Row factory returns dicts
```

#### Database Initialization

```python
def init_database(db_path: Optional[Path] = None) -> None:
    """
    Initialize database with schema from sqlite_schema.sql.
    Creates tables, indexes, triggers, and views.
    """
```

#### Video Operations

```python
def insert_video(
    video_id: str,
    title: str,
    duration_seconds: float,
    audio_path: str,
    url: Optional[str] = None,
    channel_name: Optional[str] = None,
    source_type: str = "youtube",  # or "upload"
    upload_metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None
) -> str:
    """Insert a new video record. Returns video_id."""

def get_video(
    video_id: str,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Get video by ID. Returns None if not found."""

def get_videos_by_state(
    state: str,  # 'pending', 'transcribed', 'reviewed', 'exported'
    limit: Optional[int] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Get videos in specific processing state."""

def update_video_state(
    video_id: str,
    new_state: str,
    db_path: Optional[Path] = None
) -> None:
    """Update video processing state."""

def update_video_denoised_path(
    video_id: str,
    denoised_path: str,
    db_path: Optional[Path] = None
) -> None:
    """Set denoised audio path for video."""
```

#### Segment Operations

```python
def insert_segments(
    video_id: str,
    segments: List[Dict[str, Any]],  # [{text, start, end, translation}, ...]
    db_path: Optional[Path] = None
) -> int:
    """
    Insert segments for video (clears existing first).
    Converts seconds to milliseconds automatically.
    Returns count of inserted segments.
    """

def get_segments(
    video_id: str,
    include_rejected: bool = False,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Get all segments for video, ordered by index."""

def get_segment(
    segment_id: int,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Get single segment by ID."""

def update_segment_review(
    segment_id: int,
    reviewed_transcript: Optional[str] = None,
    reviewed_translation: Optional[str] = None,
    reviewed_start_ms: Optional[int] = None,
    reviewed_end_ms: Optional[int] = None,
    is_rejected: bool = False,
    reviewer_notes: Optional[str] = None,
    db_path: Optional[Path] = None
) -> None:
    """Update segment with review data."""

def reject_segment(
    segment_id: int,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None
) -> None:
    """Mark segment as rejected."""

def split_segment(
    segment_id: int,
    split_time_ms: int,
    transcript_first: str,
    transcript_second: str,
    translation_first: str,
    translation_second: str,
    db_path: Optional[Path] = None
) -> tuple:
    """
    Split segment at specified time.
    Returns (first_id, second_id).
    Automatically reindexes subsequent segments.
    """
```

#### Statistics & Queries

```python
def get_video_progress(
    video_id: str,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Get review progress stats for video (uses v_video_progress view)."""

def get_long_segments(
    video_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Get segments exceeding 25 seconds (uses v_long_segments view)."""

def get_export_ready_segments(
    video_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Get reviewed, non-rejected segments (uses v_export_ready view)."""

def get_database_stats(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Get overall database statistics.
    
    Returns:
        {
            'videos_by_state': {'pending': N, 'transcribed': N, ...},
            'total_videos': N,
            'total_segments': N,
            'reviewed_segments': N,
            'rejected_segments': N,
            'total_hours': N.NN,
            'long_segments': N
        }
    """
```

#### JSON Validation (for uploads)

```python
def validate_transcript_json(
    data: Union[Dict, List]
) -> tuple:
    """
    Validate transcript JSON format.
    
    Expected format:
    [
        {"text": "...", "start": 0.0, "end": 4.2, "translation": "..."},
        ...
    ]
    
    Or wrapped:
    {"sentences": [...]}
    
    Returns: (is_valid: bool, errors: List[str])
    """

def parse_transcript_json(
    data: Union[Dict, List]
) -> List[Dict[str, Any]]:
    """
    Parse and normalize validated transcript JSON.
    Returns list of dicts with: text, start, end, translation.
    """
```

---

## 2. Ingestion

### ingest_youtube.py

**Location:** `src/ingest_youtube.py`

**Purpose:** Download YouTube videos with transcripts and ingest into database.

#### Pipeline Steps

```
[STEP 1/4] Download audio (yt-dlp + ffmpeg → 16kHz mono WAV)
    ↓
[STEP 2/4] Download transcripts with timestamps
    ↓
[STEP 3/4] Calculate linguistic metrics (CS ratio)
    ↓
[STEP 4/4] Insert to database (pending state)
```

#### Key Behavior

- Rejects videos without transcripts
- Detects subtitle type: Manual vs auto-generated
- Creates video record in `pending` state

#### Output Files

| File | Location |
|------|----------|
| Audio | `data/raw/audio/{video_id}.wav` |
| Transcript | `data/raw/text/{video_id}_transcript.json` |
| Metadata | `data/raw/metadata.jsonl` |

---

## 3. Preprocessing

### denoise_audio.py

**Location:** `src/preprocessing/denoise_audio.py`

**Purpose:** Remove background noise from audio using DeepFilterNet.

#### Key Behavior

- Uses DeepFilterNet for high-quality noise reduction
- GPU-accelerated when available
- Processes all pending videos in batch
- Stores denoised audio alongside originals

#### Output

```
data/raw/audio/{video_id}.wav          # Original
data/raw/audio/{video_id}_denoised.wav # Denoised
```

---

### gemini_process.py

**Location:** `src/preprocessing/gemini_process.py`

**Purpose:** Unified transcription + translation using Gemini 2.5 Pro multimodal.

#### Features

- **Single-pass processing**: Audio → Transcript + Translation
- **Adaptive chunking**: Splits audio >10 minutes with 10s overlap
- **Deduplication**: Removes duplicates from chunk overlaps
- **Structured output**: Returns JSON with timestamps

#### Constants

```python
MAX_AUDIO_DURATION_SECONDS = 10 * 60  # 10 min chunking threshold
CHUNK_OVERLAP_SECONDS = 10            # Overlap between chunks
TEXT_SIMILARITY_THRESHOLD = 0.8       # Deduplication threshold
```

#### Output Schema

```json
{
  "sentences": [
    {
      "text": "Original transcription (code-switched)",
      "start": 5.2,
      "end": 8.7,
      "translation": "Pure Vietnamese translation"
    }
  ]
}
```

#### State Transition

`pending` → `transcribed` (after successful processing)

---

## 4. Review & Export

### review_app.py

**Location:** `src/review_app.py`

**Purpose:** Streamlit web application for human review of segments.

#### Features

- Video selection with progress tracking
- Segment-by-segment review interface
- Audio playback for each segment
- Edit transcript and translation
- Adjust timestamps
- Split long segments
- Approve/reject controls

#### Running

```powershell
streamlit run src/review_app.py --server.address 0.0.0.0
```

#### State Transitions

- Reviewing: `transcribed` → `reviewed`
- Approving segment: `is_reviewed = 1`
- Rejecting segment: `is_rejected = 1`

---

### export_final.py

**Location:** `src/export_final.py`

**Purpose:** Export reviewed segments as final dataset.

#### Output Structure

```
data/export/
├── manifest.json          # Dataset metadata
├── audio/
│   └── {video_id}/
│       ├── segment_000.wav
│       ├── segment_001.wav
│       └── ...
└── transcripts/
    └── {video_id}.json    # Segment text + translations
```

#### Manifest Format

```json
{
  "exported_at": "2025-01-15T10:30:00",
  "total_videos": 25,
  "total_segments": 1250,
  "total_duration_seconds": 4500.5,
  "videos": [
    {
      "video_id": "abc123",
      "title": "...",
      "segment_count": 45,
      "duration_seconds": 180.5
    }
  ]
}
```

#### State Transition

`reviewed` → `exported`

---

## 5. Utilities

### text_utils.py

**Location:** `src/utils/text_utils.py`

**Purpose:** Text processing and code-switching detection.

#### Functions

```python
def load_teencode_dict(file_path: Path = None) -> Dict[str, str]:
    """
    Load Vietnamese teencode dictionary from file.
    Default: data/teencode.txt
    """

def normalize_text(
    text: str,
    teencode_dict: Dict = None
) -> str:
    """
    Normalize Vietnamese text:
    - Expand teencode abbreviations
    - Fix diacritics
    - Clean whitespace
    """

def contains_code_switching(text: str) -> bool:
    """
    Detect code-switching using Intersection Rule:
    - Has ≥1 Vietnamese particle (và, là, của, etc.)
    - AND has ≥1 English stop word (the, and, is, etc.)
    """

def calculate_cs_ratio(text: str) -> float:
    """
    Calculate code-switching ratio (0.0 to 1.0).
    Higher = more code-switching detected.
    """
```

---

### video_downloading_utils.py

**Location:** `src/utils/video_downloading_utils.py`

**Purpose:** Download YouTube videos as WAV using yt-dlp.

#### Constants

```python
SAMPLE_RATE = 16000      # 16kHz (required for processing)
CHANNELS = 1             # Mono audio
MIN_DURATION = 120       # 2 minutes minimum
MAX_DURATION = 3600      # 60 minutes maximum
```

#### Functions

```python
def download_channels(url_list: List[str]) -> None:
    """
    Download audio from YouTube URLs.
    Handles channels, playlists, and individual videos.
    Outputs: 16kHz mono WAV files.
    """

def save_jsonl(append: bool = True) -> None:
    """Save video metadata to data/raw/metadata.jsonl."""
```

---

### setup_gdrive_auth.py

**Location:** `src/setup_gdrive_auth.py`

**Purpose:** Configure Google Drive authentication for DVC remote.

#### Usage

```powershell
python src/setup_gdrive_auth.py
```

Opens browser for OAuth authentication. Stores credentials in:
- `~/.cache/pydrive2fs/credentials.json`

---

## Database Schema Reference

### Tables

```sql
-- Videos table
videos (
    video_id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT NOT NULL,
    channel_name TEXT,
    duration_seconds REAL,
    audio_path TEXT,
    denoised_audio_path TEXT,
    source_type TEXT DEFAULT 'youtube',  -- 'youtube' | 'upload'
    upload_metadata TEXT,  -- JSON for uploads
    processing_state TEXT DEFAULT 'pending',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

-- Segments table
segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT REFERENCES videos(video_id),
    segment_index INTEGER,
    start_ms INTEGER,
    end_ms INTEGER,
    transcript TEXT,
    translation TEXT,
    reviewed_transcript TEXT,
    reviewed_translation TEXT,
    reviewed_start_ms INTEGER,
    reviewed_end_ms INTEGER,
    is_reviewed INTEGER DEFAULT 0,
    is_rejected INTEGER DEFAULT 0,
    reviewer_notes TEXT,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP
)
```

### Views

```sql
-- Video review progress
v_video_progress: video_id, title, total_segments, reviewed_count, 
                  rejected_count, progress_pct

-- Segments over 25 seconds
v_long_segments: segment_id, video_id, segment_index, duration_seconds,
                 transcript, translation

-- Export-ready segments (reviewed, not rejected)
v_export_ready: segment_id, video_id, video_title, segment_index,
                start_ms, end_ms, final_transcript, final_translation
```

### Processing States

| State | Description |
|-------|-------------|
| `pending` | Ingested, waiting for processing |
| `transcribed` | Gemini processing complete |
| `reviewed` | Human review complete |
| `exported` | Final export complete |

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🛠️ [Command Reference](03_command_reference.md) - All commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues

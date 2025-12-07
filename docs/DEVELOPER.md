# Developer Documentation

Technical reference for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Database Schema](#database-schema)
3. [API Reference](#api-reference)
4. [Known Limitations](#known-limitations)
5. [Database Sync](#database-sync)

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Local Machine                             │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Python Environment                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │   │
│  │  │ ingest_     │  │ chunk_      │  │ gemini_         │   │   │
│  │  │ youtube.py  │  │ audio.py    │  │ process.py      │   │   │
│  │  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘   │   │
│  │         │                │                   │            │   │
│  │         └────────────────┼───────────────────┘            │   │
│  │                          │                                 │   │
│  │                    ┌─────▼─────┐                          │   │
│  │                    │  db.py    │◄──── SQLite Utilities    │   │
│  │                    └─────┬─────┘                          │   │
│  │                          │                                 │   │
│  │                    ┌─────▼─────┐                          │   │
│  │                    │ lab_data  │◄──── SQLite Database     │   │
│  │                    │   .db     │      (WAL mode)          │   │
│  │                    └───────────┘                          │   │
│  │                          ▲                                 │   │
│  │                          │                                 │   │
│  │                   ┌──────┴──────┐                         │   │
│  │                   │  review_    │◄──── Streamlit UI       │   │
│  │                   │  app.py     │      (port 8501)        │   │
│  │                   └─────────────┘                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    File System                             │   │
│  │  data/raw/audio/          ◄── 16kHz mono WAV              │   │
│  │  data/raw/chunks/         ◄── 6-min chunks (5s overlap)   │   │
│  │  data/denoised/           ◄── DeepFilterNet output        │   │
│  │  data/export/             ◄── Final dataset               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                      PROCESSING STATES                            │
│                                                                   │
│   YouTube URL                                                     │
│       │                                                           │
│       ▼                                                           │
│   ┌─────────────────┐                                            │
│   │ ingest_youtube  │ → state: pending                           │
│   └────────┬────────┘                                            │
│            │                                                      │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │  chunk_audio    │ → Creates chunks (state: pending)          │
│   └────────┬────────┘                                            │
│            │                                                      │
│            ├─────────────────┐                                   │
│            │                 │                                    │
│            ▼                 ▼                                    │
│   ┌─────────────────┐   ┌─────────────────┐                     │
│   │ denoise_audio   │   │ gemini_process  │                     │
│   │ (optional)      │   │                 │                     │
│   └────────┬────────┘   │ state:          │                     │
│            │            │ transcribed     │                     │
│            ▼            └────────┬────────┘                     │
│   Updates audio_path           │                                │
│   keeps state=pending          │                                │
│            │                   │                                 │
│            └──────────┬────────┘                                │
│                       │                                          │
│                       ▼                                          │
│              ┌─────────────────┐                                 │
│              │  review_app     │                                 │
│              │  (Streamlit)    │                                 │
│              └────────┬────────┘                                │
│                       │                                          │
│                       ▼                                          │
│              state: reviewed → approved/rejected                │
│                       │                                          │
│                       ▼                                          │
│              ┌─────────────────┐                                 │
│              │  export_final   │                                 │
│              └────────┬────────┘                                │
│                       │                                          │
│                       ▼                                          │
│              state: exported                                     │
│              is_exported = 1                                     │
└──────────────────────────────────────────────────────────────────┘
```

### State Transitions

| State | Description | Triggered By | Next State |
|-------|-------------|--------------|------------|
| `pending` | Audio downloaded/chunked, ready for processing | `ingest_youtube.py`, `chunk_audio.py` | `transcribed` OR `rejected` |
| `transcribed` | Gemini processing complete | `gemini_process.py` | `reviewed` |
| `reviewed` | Human review complete | `review_app.py` | `approved` OR `rejected` |
| `approved` | Segment approved for export | `review_app.py` | `exported` |
| `rejected` | Segment marked unusable | `review_app.py` | (terminal state) |
| `exported` | Included in final dataset | `export_final.py` | (terminal state) |

**Note on Denoising:** `denoise_audio.py` modifies the `audio_path` field to point to the denoised file but keeps `state='pending'`. This ensures `gemini_process.py` can find and process the denoised audio.

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Audio Download** | yt-dlp | YouTube video extraction |
| **Audio Processing** | FFmpeg, pydub | Format conversion, chunking, trimming |
| **Denoising** | DeepFilterNet | Background noise removal |
| **Transcription** | Gemini 2.5 Flash | Multimodal API for audio → text |
| **Database** | SQLite (WAL mode) | Lightweight, portable storage |
| **Review UI** | Streamlit | Web-based annotation interface |
| **Data Versioning** | DVC + Google Drive | Large file versioning |
| **Remote Access** | Tailscale | Secure P2P network |

---

## Database Schema

### Tables

#### videos

Stores metadata for each YouTube video.

```sql
CREATE TABLE videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    title TEXT,
    channel_name TEXT,
    duration REAL,
    audio_path TEXT,
    state TEXT CHECK(state IN ('pending', 'transcribed', 'reviewed', 'exported', 'rejected')),
    reviewer TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Indices:**
- `idx_videos_state` on `state`
- `idx_videos_channel` on `channel_name`

**Fields:**
- `video_id`: YouTube video ID (e.g., `gBhbKX0pT_0`)
- `title`: Video title from YouTube metadata
- `channel_name`: Channel name from YouTube metadata
- `duration`: Video duration in seconds
- `audio_path`: Absolute path to downloaded WAV file
- `state`: Processing state (see state transitions above)
- `reviewer`: Assigned reviewer username (nullable)

---

#### chunks

Stores audio chunks created from videos.

```sql
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    audio_path TEXT,
    start_time REAL,
    end_time REAL,
    overlap_duration REAL,
    state TEXT CHECK(state IN ('pending', 'transcribed', 'reviewed', 'exported', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);
```

**Indices:**
- `idx_chunks_video_state` on `video_id, state`

**Fields:**
- `video_id`: Foreign key to `videos` table
- `chunk_index`: Sequential index (0, 1, 2, ...)
- `audio_path`: Path to chunk WAV file (or denoised version)
- `start_time`: Start time in original video (seconds)
- `end_time`: End time in original video (seconds)
- `overlap_duration`: Overlap with previous chunk (default 5s)
- `state`: Processing state (inherits from video)

**Chunking Parameters:**
- Chunk duration: 360 seconds (6 minutes)
- Overlap: 5 seconds
- Format: 16kHz mono WAV

---

#### segments

Stores transcription/translation segments created by Gemini.

```sql
CREATE TABLE segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    transcript_vi TEXT,
    translation_en TEXT,
    start_time REAL,
    end_time REAL,
    review_state TEXT DEFAULT 'pending' 
        CHECK(review_state IN ('pending', 'reviewed', 'approved', 'rejected')),
    is_exported INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);
```

**Indices:**
- `idx_segments_chunk` on `chunk_id`
- `idx_segments_video_state` on `video_id, review_state`
- `idx_segments_review_state` on `review_state`

**Fields:**
- `chunk_id`: Foreign key to `chunks` table
- `video_id`: Foreign key to `videos` table (denormalized for performance)
- `transcript_vi`: Vietnamese transcript
- `translation_en`: English translation
- `start_time`: Start time in chunk (seconds, converted from min:sec.ms)
- `end_time`: End time in chunk (seconds, converted from min:sec.ms)
- `review_state`: Segment-level state (independent of video/chunk state)
- `is_exported`: Flag indicating if segment has been exported (0/1)

**Timestamp Format:**
- Input (Gemini): `min:sec.ms` (e.g., `0:04.54`, `1:23.45`)
- Storage (DB): Float seconds (e.g., `4.54`, `83.45`)
- Display (Streamlit): `min:sec.ms` with 10ms precision

---

### Database Configuration

**File:** `data/lab_data.db`

**WAL Mode:** Write-Ahead Logging enabled for concurrent reads during Streamlit sessions.

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=10000;
```

**Connection Management:**
- Single-writer constraint (SQLite limitation)
- Streamlit holds read connections with caching
- Batch scripts should run when Streamlit is stopped

---

## API Reference

### db.py

**Location:** `src/db.py`

Core database utilities with connection management and CRUD operations.

#### Connection Functions

```python
from src.db import get_connection, get_db

# Context manager (auto-commit/rollback)
with get_db() as db:
    db.execute("INSERT INTO videos ...", params)
    result = db.execute("SELECT ...").fetchall()

# Direct connection (manual management)
conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT ...")
rows = cursor.fetchall()
conn.close()

# Read-only mode
conn = get_connection(read_only=True)
```

#### CRUD Functions

**Videos:**
```python
from src.db import (
    insert_video,
    get_video_by_id,
    get_videos_by_state,
    update_video_state,
    update_video_reviewer
)

# Insert
insert_video(
    video_id="gBhbKX0pT_0",
    title="Video Title",
    channel_name="Channel",
    duration=865.64,
    audio_path="data/raw/audio/gBhbKX0pT_0.wav",
    state="pending"
)

# Retrieve
video = get_video_by_id("gBhbKX0pT_0")  # Returns dict or None
videos = get_videos_by_state("pending")  # Returns list of dicts

# Update
update_video_state("gBhbKX0pT_0", "transcribed")
update_video_reviewer("gBhbKX0pT_0", "john_doe")
```

**Chunks:**
```python
from src.db import (
    insert_chunk,
    get_chunks_by_video,
    get_pending_chunks,
    update_chunk_audio_path
)

# Insert
chunk_id = insert_chunk(
    video_id="gBhbKX0pT_0",
    chunk_index=0,
    audio_path="data/raw/chunks/gBhbKX0pT_0/chunk_0.wav",
    start_time=0.0,
    end_time=360.0,
    overlap_duration=5.0,
    state="pending"
)

# Retrieve
chunks = get_chunks_by_video("gBhbKX0pT_0")  # All chunks for video
pending = get_pending_chunks()  # All pending chunks

# Update (for denoising)
update_chunk_audio_path(
    chunk_id=1,
    audio_path="data/denoised/gBhbKX0pT_0/chunk_0_denoised.wav"
)
```

**Segments:**
```python
from src.db import (
    insert_segment,
    get_segments_by_chunk,
    get_segments_by_video,
    update_segment,
    update_segment_review_state,
    bulk_update_review_state
)

# Insert
segment_id = insert_segment(
    chunk_id=1,
    video_id="gBhbKX0pT_0",
    transcript_vi="Transcript in Vietnamese",
    translation_en="English translation",
    start_time=0.0,
    end_time=4.54,
    review_state="pending"
)

# Retrieve
segments = get_segments_by_chunk(chunk_id=1)
segments = get_segments_by_video("gBhbKX0pT_0", review_state="pending")

# Update single segment
update_segment(
    segment_id=123,
    transcript_vi="Updated transcript",
    translation_en="Updated translation",
    start_time=0.5,
    end_time=5.0
)
update_segment_review_state(segment_id=123, review_state="approved")

# Bulk update (for entire video)
bulk_update_review_state(
    video_id="gBhbKX0pT_0",
    review_state="approved"
)
```

---

### gemini_process.py

**Location:** `src/preprocessing/gemini_process.py`

Transcribe and translate audio using Gemini multimodal API.

#### Key Functions

```python
from src.preprocessing.gemini_process import (
    process_chunk,
    parse_timestamp_to_seconds,
    validate_timestamps
)

# Process single chunk
segments = process_chunk(
    chunk_id=1,
    audio_path="data/raw/chunks/gBhbKX0pT_0/chunk_0.wav",
    model="gemini-2.5-flash-preview-09-2025"
)

# Timestamp parsing
seconds = parse_timestamp_to_seconds("1:23.45")  # Returns 83.45

# Timestamp validation
warnings = validate_timestamps(segments)  # Returns list of issues
```

#### Configuration

```python
DEFAULT_MODEL = "gemini-2.5-flash-preview-09-2025"

GENERATION_CONFIG = {
    "temperature": 0.2,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

# Expected output format from Gemini:
{
    "sentences": [
        {
            "start": "0:04.54",      # min:sec.ms format
            "end": "0:08.79",
            "transcript": "Vietnamese text",
            "translation": "English text"
        },
        ...
    ]
}
```

#### Timestamp Validation

Checks for:
- **Overlapping segments:** End time of segment N > start time of segment N+1
- **Large gaps:** Gap > 2 seconds between consecutive segments
- **Long segments:** Duration > 25 seconds (potential processing error)

Warnings are logged but don't block processing.

---

### review_app.py

**Location:** `src/review_app.py`

Streamlit web interface for reviewing transcriptions.

#### Cached Query Functions

```python
# Database query wrappers with caching
@st.cache_data(ttl=30, show_spinner=False)
def cached_get_videos_by_state(state: str):
    return get_videos_by_state(state)

@st.cache_data(ttl=10, show_spinner=False)
def cached_get_segments_by_video(video_id: str, review_state: str):
    return get_segments_by_video(video_id, review_state)

@st.cache_data(ttl=60, show_spinner=False)
def cached_get_channels():
    return get_all_channels()
```

**TTL (Time-to-Live):** Cached results expire after N seconds, reducing DB queries.

#### Custom Styling

```python
def apply_custom_css():
    st.markdown("""
    <style>
    :root {
        --primary-color: #1f77b4;
        --background-color: #ffffff;
        --text-color: #262730;
        /* ... more variables ... */
    }
    
    @media (prefers-color-scheme: dark) {
        :root {
            --background-color: #0e1117;
            --text-color: #fafafa;
            /* ... dark mode variables ... */
        }
    }
    </style>
    """, unsafe_allow_html=True)
```

**Light/Dark Mode:** Automatically switches based on OS preference.

#### Pagination

```python
SEGMENTS_PER_PAGE = 25

# Calculate pagination
total_segments = len(segments)
total_pages = (total_segments + SEGMENTS_PER_PAGE - 1) // SEGMENTS_PER_PAGE

# Slice segments for current page
start_idx = (current_page - 1) * SEGMENTS_PER_PAGE
end_idx = start_idx + SEGMENTS_PER_PAGE
page_segments = segments[start_idx:end_idx]
```

---

### Audio Utilities

#### Load Audio with Caching

```python
import streamlit as st
from pydub import AudioSegment

@st.cache_data(show_spinner=False)
def load_audio_file(audio_path: str) -> AudioSegment:
    """Load audio file with caching to prevent MediaFileHandler errors."""
    return AudioSegment.from_wav(audio_path)
```

**Why Caching?** Streamlit's `st.audio()` creates volatile file IDs. Caching the AudioSegment prevents "Missing file" errors on reruns.

#### Audio Playback with Segment Timing

```python
# Extract segment from audio
segment_audio = full_audio[start_ms:end_ms]

# Export to bytes
buffer = io.BytesIO()
segment_audio.export(buffer, format="wav")
buffer.seek(0)

# Display with Streamlit
st.audio(buffer, format="audio/wav")
```

---

## Known Limitations

### Database & Concurrency

#### SQLite Single-Writer Limitation

**Issue:** SQLite allows only one writer at a time. Concurrent writes will block.

**Impact:**
- Stop Streamlit before running batch processing scripts
- Only one batch process should run at a time

**Workaround:**
```powershell
# Stop Streamlit (Ctrl+C)
# Run batch process
python src/preprocessing/gemini_process.py --all
# Restart Streamlit
streamlit run src/review_app.py
```

**Status:** Known limitation of SQLite. WAL mode helps with concurrent reads.

#### Transaction Handling

**Issue:** Long-running transactions can cause `database is locked` errors.

**Solution:** Use context managers (`with get_db()`) to ensure automatic commit/rollback.

---

### Audio Processing

#### Chunking Edge Cases

**Issue:** Last chunk may be shorter than 6 minutes.

**Impact:** Gemini may produce fewer segments for short chunks.

**Status:** Expected behavior. Handled gracefully in code.

#### Denoising Performance

**Issue:** DeepFilterNet requires significant GPU resources. CPU-only processing is slow (~1 min/chunk).

**Workaround:** Skip denoising if GPU unavailable, or process in smaller batches.

#### Timestamp Drift

**Issue:** Due to 5-second overlap in chunks, timestamps are relative to chunk, not original video.

**Status:** **Known bug.** Timestamps in database are chunk-relative. Need to add `chunk.start_time` to get absolute timestamps.

**Planned Fix:** Update `export_final.py` to calculate absolute timestamps:
```python
absolute_start = chunk.start_time + segment.start_time
absolute_end = chunk.start_time + segment.end_time
```

---

### Gemini API

#### Model Limitations

**Model:** `gemini-2.5-flash-preview-09-2025`

**Limitations:**
- No support for `thinking_config` (Pro feature only)
- 10-minute audio limit (handled via chunking)
- Rate limits: 1500 RPD (requests per day) for free tier

**Timestamp Accuracy:**
- Gemini may hallucinate timestamps for unclear audio
- Large gaps (>2s) flagged as warnings, require human review
- Validation checks help but can't guarantee 100% accuracy

#### API Key Rotation

**Implementation:** Rotates between multiple keys in `.env` to avoid rate limits.

```python
# .env file:
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
```

**Status:** Works well. Add more keys to increase throughput.

---

### Review Interface

#### Streamlit Limitations

**Issue:** Streamlit reruns entire script on every interaction, causing performance issues.

**Solution:** Implemented caching with `@st.cache_data` decorators and pagination (25 segments/page).

**Remaining Issue:** Very large datasets (>1000 segments) may still be slow. Consider filtering by date range in future.

#### Audio Player Quirks

**Issue:** `st.audio()` creates volatile file IDs, causing `MediaFileHandler` errors on reruns.

**Solution:** Cache audio loading with `@st.cache_data(show_spinner=False)`.

**Status:** Fixed in current version.

#### Timestamp Precision

**Issue:** Streamlit `st.number_input()` has limited precision control.

**Workaround:** Set `step=0.01` (10ms precision) for timestamp editing. Users can't fine-tune to 1ms, but 10ms is sufficient for most cases.

---

### Data Quality

#### Code-Switching Complexity

**Issue:** Vietnamese-English code-switching is challenging for ASR/MT models. Gemini may:
- Misidentify language boundaries
- Translate code-switched terms incorrectly
- Skip English words in Vietnamese transcript

**Mitigation:** Human review in Streamlit is essential. Reviewers should verify:
- Language switches are correctly identified
- English words are transcribed accurately
- Translations preserve meaning

#### Background Noise

**Issue:** YouTube videos often have background music, multiple speakers, or echo.

**Mitigation:**
- Use DeepFilterNet for denoising (optional)
- Mark noisy segments as `rejected` in review

---

### Security

#### API Keys in .env

**Issue:** `.env` file contains sensitive API keys.

**Risk:** Accidental commit to Git exposes keys.

**Mitigation:**
- `.env` is in `.gitignore`
- Rotate keys if exposed
- Use environment variables in production

#### Local-Only Design

**Benefit:** No cloud deployment = no remote attack surface.

**Tradeoff:** Limited collaboration (requires Tailscale or manual DB sync).

---

## Database Sync

### Overview

This project uses a **hybrid sync strategy** for team collaboration:

1. **Automated Backups** (hourly) → Google Drive
2. **DVC Version Control** (manual snapshots) → Google Drive + Git

### Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│ Dev Machine     │         │  Google Drive    │         │  Lab Machine    │
│                 │         │                  │         │                 │
│ lab_data.db ────┼────────→│ Hourly Backups   │←────────┼──── lab_data.db │
│     ↓           │         │ (24 recent)      │         │        ↑        │
│ dvc add     ────┼────────→│                  │         │    dvc pull     │
│ dvc push        │         │ DVC Cache        │←────────┼──── (team sync) │
│                 │         │ (versioned)      │         │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
         ↓                           ↑
         └──────── git push ─────────┘
```

### Setup (One-Time)

#### Prerequisites

1. **Google OAuth Client Secret**: Required for DVC authentication
   - Obtain `client_secret_*.json` from project owner
   - Place in `.secrets/` folder
   - Must be added as test user in Google Cloud Console

2. **DVC Installed**: Automatically installed via `requirements.txt`

3. **Google Drive Remote**: Already configured in `.dvc/config`
   - Remote URL: `gdrive://1bn9HIlEzbBX_Vofb5Y3gp530_kH938wr`

#### Configure Authentication

```powershell
# Run OAuth authentication flow
python src/setup_gdrive_auth.py

# Follow browser prompts to authenticate
# Credentials saved to .secrets/
```

### Workflow: Manual Snapshots with DVC

**Use Case:** Commit major database changes (e.g., after processing 10 videos).

```powershell
# 1. Track database with DVC
dvc add data/lab_data.db

# This creates:
# - data/lab_data.db.dvc (pointer file)
# - Updates .gitignore

# 2. Push data to Google Drive
dvc push

# 3. Commit pointer file to Git
git add data/lab_data.db.dvc
git commit -m "Update database: added 10 videos"
git push origin main
```

**On Team Member's Machine:**

```powershell
# 1. Pull latest Git commits
git pull origin main

# 2. Pull database from Google Drive
dvc pull

# This downloads data/lab_data.db
```

### Workflow: Automated Backups

**Setup:** Configured by `setup.ps1` with Windows Task Scheduler.

**Schedule:** Every hour (0:00, 1:00, 2:00, ...)

**Backup Location:** `Google Drive/NLP_Backups/`

**Retention:** Last 24 hourly backups (older files auto-deleted)

**File Format:** `lab_data_2025-01-15_14-30.db`

**Manual Restore:**

```powershell
# 1. Download backup from Google Drive
# 2. Copy to data/lab_data.db
cp "Google Drive/NLP_Backups/lab_data_2025-01-15_14-30.db" data/lab_data.db
```

### Best Practices

#### When to Use DVC

✅ **Good for:**
- Committing major milestones (10+ videos processed)
- Sharing curated datasets with team
- Rolling back to known-good states

❌ **Not for:**
- Frequent small changes (use hourly backups instead)
- Real-time collaboration (use Tailscale + Streamlit)

#### Conflict Resolution

**Scenario:** Two team members modify database independently.

**Solution:** DVC doesn't auto-merge databases (binary file). Manual resolution required:

```powershell
# 1. Save your version
cp data/lab_data.db data/lab_data_mywork.db

# 2. Pull remote version
dvc pull

# 3. Merge manually (e.g., export your segments to CSV, import to pulled DB)
python src/export_final.py --db data/lab_data_mywork.db --output temp_export.csv
python src/import_segments.py --csv temp_export.csv

# 4. Commit merged version
dvc add data/lab_data.db
dvc push
git add data/lab_data.db.dvc
git commit -m "Merged database changes"
git push
```

**Prevention:** Coordinate database modifications (assign videos to team members).

---

## Contributing

### Code Style

- **PEP8 compliant**
- **Type hints required** (use `typing` module)
- **Docstrings required** for all functions/classes
- **Pathlib preferred** over `os.path`

### Adding New Features

1. Update schema in `init_scripts/sqlite_schema.sql`
2. Create migration script (e.g., `migrate_add_<feature>.py`)
3. Update API functions in `db.py`
4. Update UI in `review_app.py` (if user-facing)
5. Update documentation in `WORKFLOW.md` or `DEVELOPER.md`

### Testing Checklist

Before committing major changes:

```powershell
# 1. Backup database
cp data/lab_data.db data/lab_data_backup.db

# 2. Test full workflow
python src/ingest_youtube.py "TEST_URL"
python src/preprocessing/chunk_audio.py --all
python src/preprocessing/gemini_process.py --all
streamlit run src/review_app.py
python src/export_final.py

# 3. Check database state
python check_db_state.py

# 4. Verify exports
ls data/export/<latest_timestamp>/

# 5. Run migration scripts
python migrate_add_<feature>.py
```

---

## Appendix

### Audio Standards

- **Sample Rate:** 16kHz
- **Channels:** Mono
- **Format:** WAV (PCM)
- **Bit Depth:** 16-bit

### File Paths

All file paths in database are **absolute paths** (e.g., `C:\Users\...\data\raw\audio\gBhbKX0pT_0.wav`).

Use `pathlib.Path` for cross-platform compatibility:

```python
from pathlib import Path

audio_path = Path("data/raw/audio/gBhbKX0pT_0.wav").resolve()
```

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GEMINI_API_KEY_1` | Yes | - | Primary Gemini API key |
| `GEMINI_API_KEY_2` | No | - | Backup API key |
| `GEMINI_API_KEY_N` | No | - | Additional keys for rotation |
| `DB_PATH` | No | `data/lab_data.db` | SQLite database path |

### Gemini Model Versions

| Model | Features | Limitations |
|-------|----------|-------------|
| `gemini-2.5-flash-preview-09-2025` | Fast, multimodal, min:sec.ms timestamps | No thinking_config |
| `gemini-2.0-flash-exp` | Experimental, faster | Less accurate timestamps |
| `gemini-2.5-pro-preview` | Better accuracy, thinking_config | Slower, higher cost |

**Current Default:** `gemini-2.5-flash-preview-09-2025`

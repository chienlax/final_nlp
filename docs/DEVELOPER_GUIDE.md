# NLP Pipeline - Developer Guide

Technical reference for developers working on the Vietnamese-English Code-Switching Speech Translation pipeline.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Database Schema](#database-schema)
5. [NiceGUI Application](#nicegui-application)
6. [Core Modules](#core-modules)
7. [API Reference](#api-reference)
8. [Development Workflow](#development-workflow)
9. [Testing](#testing)
10. [Deployment](#deployment)

---

## Architecture Overview

### System Components

```
┌─────────────────┐
│  YouTube API    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Ingest Module   │─────▶│ Raw Audio    │
└────────┬────────┘      └──────┬───────┘
         │                      │
         ▼                      ▼
┌─────────────────┐      ┌──────────────┐
│ Preprocessing   │─────▶│ Denoised     │
│ - Denoise       │      └──────┬───────┘
│ - Chunk         │             │
│ - Segment       │             ▼
└────────┬────────┘      ┌──────────────┐
         │               │ Chunks       │
         ▼               └──────┬───────┘
┌─────────────────┐             │
│ Gemini API      │◀────────────┘
│ Transcription   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ SQLite Database │◀────▶│ NiceGUI Web  │
│ - Videos        │      │ Interface    │
│ - Chunks        │      │ - Review     │
│ - Segments      │      │ - Export     │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐
│ Export Module   │
│ - ZIP Archives  │
│ - JSON Metadata │
└─────────────────┘
```

### Data Flow

1. **Ingestion**: YouTube → Raw Audio (16kHz WAV)
2. **Preprocessing**: Denoise → Chunk → Segment
3. **Transcription**: Gemini API → Transcript + Translation
4. **Review**: Web UI → Human QA → Database
5. **Export**: Approved Segments → Training Dataset

---

## Technology Stack

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Backend** | Python | 3.10+ | Primary language |
| **Database** | SQLite | 3.x | Data persistence |
| **Web Framework** | NiceGUI | 1.x | UI framework |
| **Audio Processing** | librosa, soundfile | Latest | Audio I/O |
| **Transcription** | Google Gemini API | 1.5 | ASR + Translation |
| **YouTube** | yt-dlp | Latest | Video downloading |

### Python Dependencies

```txt
nicegui>=1.0.0
yt-dlp>=2023.0.0
librosa>=0.10.0
soundfile>=0.12.0
google-generativeai>=0.3.0
python-dotenv>=1.0.0
```

Install all: `pip install -r requirements.txt`

---

## Project Structure

```
final_nlp/
├── src/
│   ├── db.py                      # Database operations
│   ├── gui_app.py                 # NiceGUI web interface
│   ├── ingest_youtube.py          # YouTube downloader
│   ├── export_final.py            # Export utilities
│   ├── preprocessing/
│   │   ├── denoise_audio.py       # Noise reduction
│   │   ├── chunk_audio.py         # Audio chunking
│   │   └── gemini_process.py      # Transcription
│   └── utils/
│       └── video_downloading_utils.py
├── data/
│   ├── raw/                       # Downloaded audio
│   ├── denoised/                  # Processed audio
│   ├── chunks/                    # Chunked audio
│   ├── segments/                  # Individual segments
│   └── lab_data.db                # SQLite database
├── docs/
│   ├── USER_GUIDE.md              # End-user manual
│   ├── DEVELOPER_GUIDE.md         # This file
│   └── WORKFLOW.md                # Pipeline documentation
├── init_scripts/
│   ├── sqlite_schema.sql          # DB schema
│   └── migrations/                # Schema migrations
├── requirements.txt
└── setup.ps1                      # Windows setup script
```

---

## Database Schema

### Tables

#### `videos`

Stores YouTube video metadata.

```sql
CREATE TABLE videos (
    id TEXT PRIMARY KEY,           -- YouTube video ID
    title TEXT NOT NULL,           -- Video title
    channel_name TEXT,             -- Channel name
    duration REAL,                 -- Duration in seconds
    upload_date TEXT,              -- YYYY-MM-DD
    downloaded INTEGER DEFAULT 0,  -- Download status
    processed INTEGER DEFAULT 0,   -- Processing status
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `chunks`

Audio chunks split from videos.

```sql
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,           -- Format: {video_id}_chunk_{idx}
    video_id TEXT NOT NULL,        -- Foreign key to videos
    chunk_index INTEGER NOT NULL,  -- 0-based index
    start_time REAL NOT NULL,      -- Start time in video (seconds)
    end_time REAL NOT NULL,        -- End time in video (seconds)
    duration REAL NOT NULL,        -- Chunk duration
    audio_path TEXT,               -- Path to WAV file
    processed INTEGER DEFAULT 0,   -- Transcription status
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

#### `segments`

Individual transcription segments within chunks.

```sql
CREATE TABLE segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,        -- Foreign key to chunks
    video_id TEXT NOT NULL,        -- Foreign key to videos
    segment_index INTEGER NOT NULL,-- 0-based index within chunk
    start_time REAL NOT NULL,      -- Start time in chunk (seconds)
    end_time REAL NOT NULL,        -- End time in chunk (seconds)
    transcript TEXT,               -- Vietnamese/English code-switched
    translation TEXT,              -- English translation
    audio_path TEXT,               -- Path to segment WAV
    duration REAL,                 -- Segment duration
    review_state TEXT DEFAULT 'Pending',  -- Pending/Approved/Rejected
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id),
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

### Indexes

```sql
CREATE INDEX idx_segments_chunk ON segments(chunk_id);
CREATE INDEX idx_segments_video ON segments(video_id);
CREATE INDEX idx_segments_review_state ON segments(review_state);
CREATE INDEX idx_chunks_video ON chunks(video_id);
```

### Migrations

Located in `init_scripts/migrations/`.

Example migration (add review_state):

```python
# migrate_add_review_state.py
import sqlite3

def migrate(db_path='data/lab_data.db'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(segments)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'review_state' not in columns:
        cursor.execute("""
            ALTER TABLE segments 
            ADD COLUMN review_state TEXT DEFAULT 'Pending'
        """)
        conn.commit()
        print("✅ Added review_state column")
    else:
        print("⏭️ Column already exists")
    
    conn.close()

if __name__ == '__main__':
    migrate()
```

Run migrations:
```powershell
python init_scripts/migrations/migrate_add_review_state.py
```

---

## NiceGUI Application

### Framework Constraints

**NiceGUI Routing Modes**:

1. **App Mode** (`@ui.page` decorators):
   - ✅ URL routing (`/`, `/review`, etc.)
   - ❌ NO UI elements at module level
   - ❌ NO helper functions creating UI (even if called in pages)
   - **Rule**: ALL UI must be inside `@ui.page` decorated functions

2. **Script Mode** (no decorators):
   - ✅ UI at module level allowed
   - ✅ Helper functions allowed
   - ❌ NO URL routing with `@ui.page`
   - ✅ Tab-based navigation works

**Our Implementation**: Script Mode with tabs (no URL routing).

**Why**: The application uses helper functions and shared components (navigation, audio player), which triggers NiceGUI's global scope UI detection in App Mode.

### Architecture

```python
# src/gui_app.py structure

# 1. Imports and Configuration
from nicegui import ui, app
from pathlib import Path
import sqlite3

# 2. Constants
DATA_ROOT = Path(__file__).parent.parent / 'data'
DB_PATH = DATA_ROOT / 'lab_data.db'

# 3. State Management
@dataclass
class AppState:
    current_video: Optional[str] = None
    current_chunk: Optional[str] = None
    current_page: int = 1
    bulk_edit_mode: bool = False
    bulk_selected: Dict[int, bool] = field(default_factory=dict)

state = AppState()

# 4. Database Helpers
def get_videos():
    """Fetch all videos from database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM videos")
    results = cursor.fetchall()
    conn.close()
    return results

# 5. UI Components
def render_segment_row(segment: Dict, idx: int, state: AppState):
    """Render single segment row in data-grid layout."""
    # Implementation...

# 6. Content Functions (one per tab)
def dashboard_content():
    """Dashboard tab content."""
    # Implementation...

# 8. Entry Point
def main():
    app.add_static_files('/data', str(DATA_ROOT))
    ui.colors(primary='#22c55e')
    
    # Initialize database
    ensure_database_exists()
    
    # Render UI (script mode)
    main_page()
    
    # Start server
    ui.run(host='0.0.0.0', port=8501, title='NLP Review')

if __name__ == '__main__':
    main()
```

### State Management

**AppState Dataclass**:

```python
@dataclass
class AppState:
    current_video: Optional[str] = None       # Selected video ID
    current_chunk: Optional[str] = None       # Selected chunk ID
    current_page: int = 1                     # Pagination page
    bulk_edit_mode: bool = False              # Bulk edit toggle
    bulk_selected: Dict[int, bool] = field(default_factory=dict)  # Selected segments
```

**Usage**:

```python
# Global state instance
state = AppState()

# Access in UI functions
def review_content_sync():
    if state.bulk_edit_mode:
        # Show checkboxes
        pass
    else:
        # Hide checkboxes
        pass
```

### UI Patterns

#### Data-Grid Layout

```python
def render_segment_row(segment, idx, state):
    """Compact row with 4/5 columns."""
    with ui.row().classes('w-full items-center gap-2'):
        if state.bulk_edit_mode:
            # Checkbox column (5%)
            ui.checkbox(value=state.bulk_selected.get(segment['id'], False))
        
        # Timestamps column (12-15%)
        with ui.column().classes('w-[12%]'):
            ui.label(f"{segment['start']:.1f}s").classes('text-xs')
            ui.label(f"{segment['end']:.1f}s").classes('text-xs')
        
        # Transcript column (35-40%)
        with ui.column().classes('w-[40%]'):
            ui.textarea(value=segment['transcript'])
        
        # Translation column (35-40%)
        with ui.column().classes('w-[40%]'):
            ui.textarea(value=segment['translation'])
        
        # Actions column (8-10%)
        with ui.row().classes('w-[8%] gap-1'):
            ui.button(icon='play_arrow')  # Audio player
            ui.button(icon='save')        # Save
            ui.button(icon='check')       # Approve
            ui.button(icon='close')       # Reject
```

#### Inline Editing

```python
# Edit mode toggle
edit_mode = ui.state({'active': False})

# Display mode
if not edit_mode['active']:
    with ui.row():
        ui.label(segment['transcript'])
        ui.button('Edit', on_click=lambda: edit_mode.update({'active': True}))

# Edit mode
else:
    with ui.column():
        textarea = ui.textarea(value=segment['transcript'])
        with ui.row():
            ui.button('Save', on_click=lambda: save_and_exit(textarea.value))
            ui.button('Cancel', on_click=lambda: edit_mode.update({'active': False}))
```

#### Audio Player

```python
def create_audio_player(audio_path: str):
    """Styled audio player with gradient border."""
    full_path = f"/data/segments/{audio_path}"
    
    with ui.element('div').classes('p-1 rounded-lg bg-gradient-to-r from-green-400 to-blue-500'):
        ui.audio(full_path).classes('w-full rounded')
```

### Keyboard Shortcuts

```python
# Register global shortcuts
ui.keyboard(
    lambda e: handle_shortcut(e.key),
    events=['keydown'],
    active=lambda: state.current_chunk is not None
)

def handle_shortcut(key: str):
    """Handle keyboard events."""
    if key == 'Ctrl+S':
        save_current_segment()
    elif key == 'Ctrl+Enter':
        approve_current_segment()
    elif key == 'Ctrl+R':
        reject_current_segment()
```

---

## Core Modules

### `src/db.py`

**Purpose**: Database operations abstraction.

**Key Functions**:

```python
def get_videos() -> List[Dict]:
    """Fetch all videos."""
    
def get_chunks(video_id: str) -> List[Dict]:
    """Get chunks for video."""
    
def get_segments(chunk_id: str, page: int = 1, page_size: int = 20) -> List[Dict]:
    """Paginated segments."""
    
def update_segment(segment_id: int, **kwargs) -> bool:
    """Update segment fields."""
    
def update_review_state(segment_id: int, state: str) -> bool:
    """Set review state (Pending/Approved/Rejected)."""
    
def get_database_stats() -> Dict:
    """Aggregate statistics."""
```

**Usage**:

```python
from src.db import get_videos, update_segment

# Fetch data
videos = get_videos()

# Update
update_segment(
    segment_id=123,
    transcript="New transcript",
    translation="New translation"
)
```

### `src/preprocessing/denoise_audio.py`

**Purpose**: Noise reduction using spectral gating.

**Algorithm**:
1. Load audio with librosa
2. Compute noise profile (first 1s)
3. Apply spectral gate
4. Save denoised WAV

**Usage**:

```python
from src.preprocessing.denoise_audio import denoise_file

denoise_file(
    input_path='data/raw/audio/video_id/audio.wav',
    output_path='data/denoised/video_id/audio.wav',
    noise_duration=1.0,  # seconds for noise profile
    threshold_db=-20
)
```

**Parameters**:
- `noise_duration`: Seconds to use for noise profile (default: 1.0)
- `threshold_db`: Noise gate threshold (default: -20)
- `smoothing`: Temporal smoothing window (default: 0.5s)

### `src/preprocessing/chunk_audio.py`

**Purpose**: Split long audio into chunks.

**Strategy**:
- Fixed-duration chunks (default: 300s = 5min)
- Overlap: 0s (clean cuts)
- Output: `data/raw/chunks/{video_id}/chunk_{idx}.wav`

**Usage**:

```python
from src.preprocessing.chunk_audio import chunk_audio_file

chunk_audio_file(
    input_path='data/denoised/video_id/audio.wav',
    output_dir='data/raw/chunks/video_id',
    chunk_duration=300,  # seconds
    sr=16000
)
```

**Database Integration**:

```python
# After chunking, create DB entries
from src.db import create_chunk

for idx, chunk_path in enumerate(chunk_paths):
    create_chunk(
        chunk_id=f"{video_id}_chunk_{idx}",
        video_id=video_id,
        chunk_index=idx,
        start_time=idx * 300,
        end_time=(idx + 1) * 300,
        audio_path=str(chunk_path)
    )
```

### `src/preprocessing/gemini_process.py`

**Purpose**: Transcription + translation via Gemini API.

**Flow**:
1. Load chunk audio
2. Send to Gemini 1.5 Flash
3. Parse response (JSON)
4. Save segments to database

**Prompt Template**:

```python
PROMPT = """
You are a transcription assistant. Transcribe the following Vietnamese-English code-switched audio.

Output JSON:
{
  "segments": [
    {
      "start": 0.0,
      "end": 5.2,
      "transcript": "Xin chào everyone",
      "translation": "Hello everyone"
    }
  ]
}

Requirements:
- Accurate timestamps (seconds)
- Preserve code-switching in transcript
- Translate to fluent English
"""
```

**Usage**:

```python
from src.preprocessing.gemini_process import transcribe_chunk

transcribe_chunk(
    chunk_id='video_id_chunk_0',
    audio_path='data/raw/chunks/video_id/chunk_0.wav',
    api_key='YOUR_API_KEY'
)
```

**Error Handling**:

```python
try:
    result = transcribe_chunk(...)
except APIError as e:
    logger.error(f"Gemini API error: {e}")
    # Retry or log for manual review
```

---

## API Reference

### Database Functions (`src/db.py`)

#### `get_videos() -> List[Dict]`

Returns all videos.

**Returns**:
```python
[
    {
        'id': 'abc123',
        'title': 'Video Title',
        'channel_name': 'Channel Name',
        'duration': 600.0,
        'downloaded': 1,
        'processed': 1
    },
    ...
]
```

#### `get_segments(chunk_id: str, page: int, page_size: int) -> List[Dict]`

Returns paginated segments.

**Parameters**:
- `chunk_id`: Chunk ID to filter by
- `page`: 1-based page number
- `page_size`: Segments per page

**Returns**:
```python
[
    {
        'id': 1,
        'chunk_id': 'video_id_chunk_0',
        'segment_index': 0,
        'start_time': 0.0,
        'end_time': 5.2,
        'transcript': 'Xin chào',
        'translation': 'Hello',
        'review_state': 'Pending',
        'audio_path': 'segments/video_id/chunk_0/seg_0.wav'
    },
    ...
]
```

#### `update_segment(segment_id: int, **kwargs) -> bool`

Updates segment fields.

**Parameters**:
- `segment_id`: Segment ID
- `**kwargs`: Fields to update (transcript, translation, start_time, end_time, review_state)

**Returns**: `True` if successful, `False` otherwise.

**Example**:
```python
update_segment(
    segment_id=1,
    transcript="Updated transcript",
    review_state="Approved"
)
```

#### `get_database_stats() -> Dict`

Returns aggregate statistics.

**Returns**:
```python
{
    'total_videos': 10,
    'total_chunks': 50,
    'total_segments': 500,
    'reviewed_segments': 300,
    'approved_segments': 250,
    'rejected_segments': 50,
    'long_segments': 5  # >30s
}
```

### GUI State Management

#### `AppState` Dataclass

```python
@dataclass
class AppState:
    current_video: Optional[str]
    current_chunk: Optional[str]
    current_page: int
    bulk_edit_mode: bool
    bulk_selected: Dict[int, bool]
```

**Methods**:

```python
# Reset state
state.current_video = None
state.current_chunk = None
state.current_page = 1

# Toggle bulk edit
state.bulk_edit_mode = not state.bulk_edit_mode

# Select/deselect segment
state.bulk_selected[segment_id] = True
```

---

## Development Workflow

### Setup Environment

```powershell
# Clone repository
git clone https://github.com/your-repo/final_nlp.git
cd final_nlp

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from src.db import ensure_database_exists; ensure_database_exists()"
```

### Run Development Server

```powershell
# Activate venv
.venv\Scripts\Activate.ps1

# Run GUI (auto-reload with --reload flag)
python src/gui_app.py

# Access at http://localhost:8501
```

### Code Style

**PEP8 Compliance**:
```powershell
# Install linters
pip install flake8 black

# Check style
flake8 src/

# Auto-format
black src/
```

**Type Hints**:
```python
from typing import List, Dict, Optional

def get_videos() -> List[Dict[str, Any]]:
    """Type hints required for all functions."""
    pass
```

### Git Workflow

```powershell
# Feature branch
git checkout -b feature/new-feature

# Commit with clear messages
git commit -m "feat: Add bulk export to ZIP"

# Push and create PR
git push origin feature/new-feature
```

**Commit Convention**:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `refactor:` Code refactor
- `test:` Tests

---

## Testing

### Unit Tests

```python
# tests/test_db.py
import unittest
from src.db import get_videos, update_segment

class TestDatabase(unittest.TestCase):
    def test_get_videos(self):
        videos = get_videos()
        self.assertIsInstance(videos, list)
    
    def test_update_segment(self):
        result = update_segment(1, transcript="Test")
        self.assertTrue(result)
```

Run tests:
```powershell
python -m unittest discover tests/
```

### Integration Tests

```python
# tests/test_preprocessing.py
from src.preprocessing.chunk_audio import chunk_audio_file
from pathlib import Path

def test_chunking():
    chunk_audio_file(
        input_path='tests/fixtures/sample.wav',
        output_dir='tests/output',
        chunk_duration=10
    )
    chunks = list(Path('tests/output').glob('*.wav'))
    assert len(chunks) > 0
```

### GUI Testing

Manual testing checklist:

- [ ] Dashboard loads stats
- [ ] Video selection works
- [ ] Chunk selection works
- [ ] Segment editing saves
- [ ] Audio player plays
- [ ] Bulk edit mode toggles
- [ ] Export downloads ZIP
- [ ] Pagination navigates

---

## Deployment

### Production Setup

```powershell
# Clone on server
git clone https://github.com/your-repo/final_nlp.git
cd final_nlp

# Setup environment
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure
# Edit src/gui_app.py: ui.run(host='0.0.0.0', port=8501)

# Run with nohup (Linux) or screen (Windows)
nohup python src/gui_app.py &
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8501
CMD ["python", "src/gui_app.py"]
```

Build and run:
```powershell
docker build -t nlp-review .
docker run -p 8501:8501 -v $(pwd)/data:/app/data nlp-review
```

### Environment Variables

```bash
# .env file
GEMINI_API_KEY=your_api_key_here
DATABASE_PATH=data/lab_data.db
AUDIO_ROOT=data/
```

Load in Python:
```python
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
```

---

## Troubleshooting

### NiceGUI Routing Error

**Error**: `RuntimeError: ui.page cannot be used in NiceGUI scripts where you define UI in the global scope`

**Cause**: Mixing `@ui.page` decorators with module-level UI or helper functions.

**Solution**: Use script mode (no decorators) with tab-based navigation.

```python
# ❌ WRONG (App Mode with helpers)
@ui.page('/')
def main_page():
    create_navigation()  # Helper creates UI → triggers error

# ✅ CORRECT (Script Mode)
def main_page():
    with ui.tabs() as tabs:
        ui.tab('dashboard')
    with ui.tab_panels(tabs):
        with ui.tab_panel('dashboard'):
            dashboard_content()

def main():
    main_page()  # Direct call
    ui.run()
```

### Database Locked

**Cause**: Multiple connections open simultaneously.

**Solution**: Use context managers:

```python
# ❌ WRONG
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
# ... forgot to close

# ✅ CORRECT
with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    # ... automatically closes
```

### Audio Path Issues

**Symptom**: Audio player shows "File not found".

**Check**:
1. File exists: `ls data/segments/{video_id}/{chunk_id}/`
2. Static route configured: `app.add_static_files('/data', str(DATA_ROOT))`
3. Path format: `/data/segments/video_id/chunk_id/seg_0.wav`

---

## Performance Optimization

### Database Indexing

```sql
-- Add indexes for common queries
CREATE INDEX idx_segments_review_pending 
ON segments(review_state) 
WHERE review_state = 'Pending';

CREATE INDEX idx_segments_video_chunk 
ON segments(video_id, chunk_id);
```

### Caching

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_database_stats():
    """Cached for 60 seconds."""
    # ... query database
    pass

# Clear cache manually
get_database_stats.cache_clear()
```

### Lazy Loading

```python
# Don't load all segments at once
def review_content_sync():
    # Only load current page
    segments = get_segments(chunk_id, page=state.current_page, page_size=20)
    # Render only visible segments
```

---

## Security Considerations

### API Key Management

```python
# ❌ WRONG - Hardcoded
api_key = "AIzaSy..."

# ✅ CORRECT - Environment variable
import os
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    raise ValueError("GEMINI_API_KEY not set")
```

### Input Validation

```python
def update_segment(segment_id: int, transcript: str, translation: str):
    # Validate inputs
    if not isinstance(segment_id, int) or segment_id <= 0:
        raise ValueError("Invalid segment ID")
    
    if len(transcript) > 5000:
        raise ValueError("Transcript too long")
    
    # Sanitize for SQL injection (use parameterized queries)
    cursor.execute(
        "UPDATE segments SET transcript=?, translation=? WHERE id=?",
        (transcript, translation, segment_id)
    )
```

---

## Contributing

### Pull Request Process

1. **Fork** repository
2. **Create feature branch**: `git checkout -b feature/my-feature`
3. **Make changes** with clear commits
4. **Add tests** for new features
5. **Update documentation** (this file)
6. **Submit PR** with description

### Code Review Checklist

- [ ] PEP8 compliant (run `flake8`)
- [ ] Type hints added
- [ ] Docstrings for all functions
- [ ] Tests pass (`python -m unittest`)
- [ ] Documentation updated
- [ ] No hardcoded paths or keys

---

## Architecture Decisions

### Why NiceGUI?

**Pros**:
- Fast development (Python-only, no HTML/CSS/JS)
- Built-in components (audio player, file upload)
- Auto-reload during development
- Easy deployment (single Python file)

**Cons**:
- Limited routing (tab-based navigation only)
- Less flexible than React/Vue
- Smaller ecosystem

**Alternative Considered**: Streamlit
- **Rejected**: Streamlit's reruns make state management harder

### Why SQLite?

**Pros**:
- Zero-configuration
- File-based (easy backup)
- Sufficient for <100k segments
- Built into Python

**Cons**:
- No concurrent writes (not an issue for single-user GUI)
- No advanced features (triggers, stored procedures)

**Migration Path**: If scaling needed, migrate to PostgreSQL via `sqlite3_to_postgres.py` script.

---

## Changelog

### v2.0 (2025-01-15)

**Features**:
- ✅ Data-grid layout for segments
- ✅ Bulk edit mode with checkboxes
- ✅ Time-picker widgets for timestamps
- ✅ Enhanced audio player styling
- ✅ Chunk-level JSON upload
- ✅ Tab-based navigation (script mode)

**Fixed**:
- ❌ Removed URL routing (NiceGUI limitation)
- ✅ Converted to tab-based SPA

**Documentation**:
- ✅ Created USER_GUIDE.md
- ✅ Created DEVELOPER_GUIDE.md
- ✅ Updated WORKFLOW.md

### v1.0 (2024-12-01)

**Initial Release**:
- Basic review interface
- Video/chunk selection
- Segment editing
- Export to JSON

---

## Support & Contact

**Issues**: GitHub Issues  
**Documentation**: `docs/` folder  
**Developer**: MLOps Team

---

**Version**: 2.0  
**Last Updated**: 2025-01-15  
**License**: MIT

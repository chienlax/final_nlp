# 05. Script Details

This document provides detailed documentation for all scripts in the `src/` directory.

---

## Table of Contents

1. [Orchestrator Scripts](#1-orchestrator-scripts)
   - [5.1 ingest_youtube.py](#51-ingest_youtubepy)
   - [5.2 ingest_substack.py](#52-ingest_substackpy)
   - [5.3 label_studio_sync.py](#53-label_studio_syncpy)
   - [5.4 sync_daemon.py](#54-sync_daemonpy)
   - [5.5 export_reviewed.py](#55-export_reviewedpy)
   - [5.6 webhook_server.py](#56-webhook_serverpy)
2. [Utility Modules](#2-utility-modules)
   - [5.7 video_downloading_utils.py](#57-video_downloading_utilspy)
   - [5.8 transcript_downloading_utils.py](#58-transcript_downloading_utilspy)
   - [5.9 substack_utils.py](#59-substack_utilspy)
   - [5.10 text_utils.py](#510-text_utilspy)
   - [5.11 data_utils.py](#511-data_utilspy)

---

## 1. Orchestrator Scripts

### 5.1 ingest_youtube.py

**Location:** `src/ingest_youtube.py`

**Purpose:** Main orchestrator for the YouTube audio-first ingestion pipeline. Combines video download, transcript download, CS ratio calculation, and database insertion into a single workflow.

#### Usage

```bash
# Download and ingest a single video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Download from a channel
python src/ingest_youtube.py "https://www.youtube.com/@ChannelName"

# Dry run (simulate without database writes)
python src/ingest_youtube.py --dry-run "https://youtube.com/watch?v=VIDEO_ID"

# Skip download, use existing metadata.jsonl
python src/ingest_youtube.py --skip-download

# Combine flags
python src/ingest_youtube.py --skip-download --dry-run
```

#### Command Line Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `urls` | positional | YouTube video or channel URLs to download |
| `--skip-download` | flag | Skip download step, use existing `metadata.jsonl` |
| `--dry-run` | flag | Simulate ingestion without database writes |

#### Pipeline Steps

```
[STEP 1/4] Download audio files (yt-dlp + ffmpeg)
    ↓
[STEP 2/4] Download transcripts with timestamps
    ↓
[STEP 3/4] Calculate linguistic metrics (CS ratio)
    ↓
[STEP 4/4] Ingest to database
```

#### Key Functions

```python
def run_pipeline(urls: List[str], skip_download: bool, dry_run: bool) -> None:
    """
    Run the full YouTube ingestion pipeline.
    
    Steps:
    1. Download audio as 16kHz mono WAV
    2. Download transcripts with timestamps
    3. Calculate CS ratio for each transcript
    4. Insert records into database
    """

def ingest_to_database(metadata_entries: List[Dict], dry_run: bool) -> Dict[str, int]:
    """
    Ingest metadata entries into the samples table.
    
    Returns:
        {'inserted': N, 'skipped': M, 'failed': K}
    """
```

#### Output Files

| File | Location | Description |
|------|----------|-------------|
| Audio | `data/raw/audio/{video_id}.wav` | 16kHz mono WAV |
| Transcript | `data/raw/text/{video_id}_transcript.json` | JSON with timestamps |
| Metadata | `data/raw/metadata.jsonl` | Batch metadata file |

---

### 5.2 ingest_substack.py

**Location:** `src/ingest_substack.py`

**Purpose:** Main orchestrator for the Substack text-first ingestion pipeline. Downloads blog articles and ingests them for the TTS generation workflow.

#### Usage

```bash
# From URLs file
python src/ingest_substack.py --urls-file data/substack_urls.txt

# Process existing downloads only
python src/ingest_substack.py --skip-download

# Dry run mode
python src/ingest_substack.py --dry-run

# Limit number of articles
python src/ingest_substack.py --limit 10
```

#### Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--urls-file` | path | `data/substack_urls.txt` | File containing Substack URLs |
| `--download-dir` | path | `data/substack_downloads` | Output directory |
| `--teencode-file` | path | `data/teencode.txt` | Teencode dictionary |
| `--skip-download` | flag | - | Skip download, process existing |
| `--dry-run` | flag | - | Preview without database writes |
| `--limit` | int | - | Max articles to process |

#### Key Functions

```python
def ingest_substack(
    urls: List[str],
    skip_download: bool,
    dry_run: bool
) -> dict:
    """
    Main entry point for Substack ingestion.
    
    Returns:
        {'total': N, 'processed': M, 'ingested': K, 'skipped': S, 'errors': E}
    """

def process_article(
    article_path: Path,
    source_url: str,
    teencode_dict: dict,
    conn,
    dry_run: bool
) -> Optional[int]:
    """
    Process a single article and ingest into database.
    
    Returns:
        sample_id if successful, None otherwise
    """
```

#### Output Files

| File | Location | Description |
|------|----------|-------------|
| Articles | `data/raw/text/substack/{blog_slug}/{article}.txt` | Cleaned text |

---

### 5.3 label_studio_sync.py

**Location:** `src/label_studio_sync.py`

**Purpose:** Synchronizes data between the PostgreSQL database and Label Studio for human annotation tasks.

#### Usage

```bash
# Push samples to Label Studio for annotation
python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed annotations back to database
python src/label_studio_sync.py pull --task-type transcript_correction

# Check connection status
python src/label_studio_sync.py status
```

#### Environment Variables

```bash
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_api_key
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_TRANSLATION=2
LS_PROJECT_SEGMENTATION=3
```

#### Task Types

| Task Type | Description | Project |
|-----------|-------------|---------|
| `transcript_verification` | Verify/correct ASR transcripts | `LS_PROJECT_TRANSCRIPT` |
| `timestamp_alignment` | Verify word-level timestamps | `LS_PROJECT_TRANSCRIPT` |
| `translation_review` | Review LLM translations | `LS_PROJECT_TRANSLATION` |
| `quality_assessment` | Final quality check | `LS_PROJECT_TRANSLATION` |

---

### 5.4 sync_daemon.py

**Location:** `src/sync_daemon.py`

**Purpose:** Automatic DVC synchronization daemon that runs every 5 minutes to keep data in sync between local storage and Google Drive remote.

#### Usage

```bash
# Run continuous sync (default: every 5 minutes)
python src/sync_daemon.py

# Single sync operation
python src/sync_daemon.py --once

# Custom interval (10 minutes)
python src/sync_daemon.py --interval 10

# Push-only mode (upload local changes)
python src/sync_daemon.py --once --push
```

#### Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--once` | flag | - | Run single sync and exit |
| `--interval` | int | 5 | Sync interval in minutes |
| `--push` | flag | - | Push-only mode (upload changes) |

#### Key Functions

```python
def run_dvc_pull() -> Dict[str, Any]:
    """
    Execute DVC pull to fetch new data from remote.
    
    Returns:
        {
            'success': bool,
            'files_updated': int,
            'commit_hash': str,
            'message': str
        }
    """

def run_dvc_push() -> Dict[str, Any]:
    """
    Execute DVC push to upload local changes.
    
    Returns:
        {
            'success': bool,
            'files_pushed': int,
            'commit_hash': str,
            'message': str
        }
    """

def run_sync_loop(interval_minutes: int = 5) -> None:
    """
    Run continuous sync loop.
    
    - Executes pull → push every interval
    - Logs results to console
    - Records commit hashes in database
    - Handles interrupts gracefully
    """

def run_once(push_only: bool = False) -> Dict[str, Any]:
    """
    Run single sync operation.
    
    Args:
        push_only: If True, only push (no pull)
    
    Returns:
        Sync result dictionary
    """
```

#### Environment Variables

```bash
DVC_REMOTE=gdrive               # Remote name (configured in .dvc/config)
SYNC_INTERVAL_MINUTES=5         # Default interval
DATABASE_URL=postgresql://...   # For logging sync results
```

#### Docker Integration

Runs as `sync_service` container:
```yaml
sync_service:
  build:
    context: .
    dockerfile: Dockerfile.ingest
  command: python src/sync_daemon.py --interval 5
  volumes:
    - ./data:/app/data
```

---

### 5.5 export_reviewed.py

**Location:** `src/export_reviewed.py`

**Purpose:** Export reviewed and verified samples from the database to a structured output directory for downstream processing.

#### Usage

```bash
# Export all reviewed samples
python src/export_reviewed.py --output-dir data/reviewed

# Export specific task type
python src/export_reviewed.py --task-type transcript_correction

# Dry run (preview only)
python src/export_reviewed.py --dry-run

# Limit number of exports
python src/export_reviewed.py --limit 100
```

#### Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--output-dir` | path | `data/reviewed` | Output directory |
| `--task-type` | str | - | Filter by task type |
| `--dry-run` | flag | - | Preview without writing |
| `--limit` | int | - | Maximum samples to export |

#### Output Structure

```
data/reviewed/
└── {task_type}/
    └── {sample_id}/
        ├── audio.wav           # Original audio file
        ├── transcript.json     # Final corrected transcript
        ├── translation.json    # Verified translation (if available)
        └── metadata.json       # Sample metadata + revision history
```

#### Key Functions

```python
def export_sample(
    sample_id: str,
    output_dir: Path,
    include_audio: bool = True
) -> Dict[str, Any]:
    """
    Export a single reviewed sample.
    
    Returns:
        {
            'sample_id': str,
            'files_exported': List[str],
            'total_size_bytes': int,
            'success': bool
        }
    """

def export_all_reviewed(
    output_dir: Path,
    task_type: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Export all reviewed samples to output directory.
    
    Returns:
        {
            'total_samples': int,
            'exported': int,
            'skipped': int,
            'errors': int,
            'total_size_mb': float
        }
    """

def generate_manifest(output_dir: Path) -> Dict[str, Any]:
    """
    Generate manifest.json with metadata for all exported samples.
    
    Returns:
        Manifest dictionary with sample list and statistics
    """
```

#### DVC Pipeline Integration

```yaml
# dvc.yaml
stages:
  export_reviewed:
    cmd: python src/export_reviewed.py --output-dir data/reviewed
    deps:
      - src/export_reviewed.py
    outs:
      - data/reviewed
```

---

### 5.6 webhook_server.py

**Location:** `src/webhook_server.py`

**Purpose:** FastAPI server that receives webhook callbacks from Label Studio when annotations are created or updated. Handles conflict detection and database recording.

#### Usage

```bash
# Start webhook server (development)
uvicorn src.webhook_server:app --host 0.0.0.0 --port 8000 --reload

# Start webhook server (production)
uvicorn src.webhook_server:app --host 0.0.0.0 --port 8000 --workers 4

# Via Docker Compose
docker-compose up webhook_server
```

#### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook` | Receive Label Studio annotation callbacks |
| GET | `/api/conflicts` | List all detected conflicts |
| POST | `/api/resolve-conflict/{id}` | Resolve a conflict |
| GET | `/api/stats` | Get annotation statistics |
| GET | `/health` | Health check endpoint |

#### Webhook Payload Format

```json
{
  "action": "ANNOTATION_CREATED",
  "annotation": {
    "id": 123,
    "completed_by": 1,
    "result": [...],
    "created_at": "2024-01-01T12:00:00Z"
  },
  "task": {
    "id": 456,
    "data": {
      "sample_id": "uuid-here",
      "sync_version": 5
    }
  },
  "project": {
    "id": 1,
    "title": "Transcript Correction"
  }
}
```

#### Key Functions

```python
@app.post("/webhook")
async def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle Label Studio webhook callbacks.
    
    Processes:
    - ANNOTATION_CREATED: Check conflict, record result
    - ANNOTATION_UPDATED: Update existing annotation
    - TASK_COMPLETED: Mark sample as reviewed
    
    Returns:
        {'status': 'success' | 'conflict_detected', 'message': str}
    """

def check_conflict(sample_id: str, annotation_sync_version: int) -> bool:
    """
    Check if sample was modified during annotation.
    
    Compares sync_version at annotation start vs current database value.
    
    Returns:
        True if conflict detected
    """

def record_annotation_to_db(
    sample_id: str,
    annotation_result: Dict,
    annotator_id: int,
    task_type: str
) -> str:
    """
    Record completed annotation to database.
    
    - Creates new transcript/translation revision
    - Updates sample processing state
    - Unlocks sample
    
    Returns:
        UUID of created revision
    """

def create_conflict_sample(
    original_sample_id: str,
    annotation_result: Dict
) -> str:
    """
    Create new sample from conflict annotation.
    
    - Clones original sample with '_conflict_{timestamp}' suffix
    - Stores annotation result
    - Flags both for re-review
    
    Returns:
        UUID of conflict sample
    """
```

#### Environment Variables

```bash
WEBHOOK_SECRET=your_secret_key    # For payload validation (optional)
DATABASE_URL=postgresql://...     # Database connection
LABEL_STUDIO_URL=http://...       # For API callbacks
```

#### Conflict Resolution API

```bash
# List conflicts
curl http://localhost:8000/api/conflicts

# Resolve conflict (keep annotated version)
curl -X POST http://localhost:8000/api/resolve-conflict/123 \
  -H "Content-Type: application/json" \
  -d '{"resolution": "keep_annotated"}'

# Resolve conflict (keep updated version)
curl -X POST http://localhost:8000/api/resolve-conflict/123 \
  -d '{"resolution": "keep_updated"}'
```

---

## 2. Utility Modules

### 5.7 video_downloading_utils.py

**Location:** `src/utils/video_downloading_utils.py`

**Purpose:** Downloads YouTube videos as 16kHz mono WAV files using yt-dlp and ffmpeg.

#### Constants

```python
SAMPLE_RATE = 16000      # 16kHz as per project spec
CHANNELS = 1             # Mono
MIN_DURATION = 120       # 2 minutes minimum
MAX_DURATION = 3600      # 60 minutes maximum
OUTPUT_DIR = Path("data/raw/audio")
METADATA_FILE = Path("data/raw/metadata.jsonl")
```

#### Key Functions

```python
def download_channels(url_list: List[str]) -> None:
    """
    Download audio from YouTube channels/videos as 16kHz mono WAV.
    
    Features:
    - Duration filter (2-60 minutes)
    - Best audio quality extraction
    - Automatic resampling to 16kHz mono
    - Progress hooks for metadata capture
    """

def _duration_filter(info_dict: Dict, incomplete: bool) -> Optional[str]:
    """
    Filter function for yt-dlp to skip videos outside duration range.
    
    Returns:
        None if video passes, error message string if rejected
    """

def save_jsonl(append: bool = True) -> None:
    """
    Save downloaded video metadata to JSONL file.
    
    Supports append mode with deduplication by video ID.
    """
```

#### yt-dlp Configuration

```python
ydl_opts = {
    'format': 'bestaudio/best',
    'match_filter': _duration_filter,
    'postprocessors': [
        {'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'},
        {'key': 'FFmpegMetadata'},
    ],
    'postprocessor_args': {
        'ffmpeg': ['-ar', '16000', '-ac', '1'],  # 16kHz mono
    },
    'outtmpl': 'data/raw/audio/%(id)s.%(ext)s',
}
```

---

### 5.8 transcript_downloading_utils.py

**Location:** `src/utils/transcript_downloading_utils.py`

**Purpose:** Downloads YouTube transcripts with timestamps for audio segmentation.

#### Key Functions

```python
def get_transcript_info(video_id: str) -> Dict[str, Any]:
    """
    Fetch transcript with subtitle type detection.
    
    Priority order:
    1. Manual English transcript
    2. Auto-generated English transcript
    3. Manual Vietnamese transcript
    4. Auto-generated Vietnamese transcript
    
    Returns:
        {
            'segments': [{text, start, duration, end}, ...],
            'text': 'Full transcript text',
            'subtitle_type': 'Manual' | 'Auto-generated' | 'Not Available',
            'language': 'en' | 'vi',
            'error': None | 'error message'
        }
    """

def download_transcripts_from_metadata() -> List[Dict[str, Any]]:
    """
    Download transcripts for all videos in metadata.jsonl.
    
    - Saves as JSON files with timestamps
    - Updates metadata.jsonl with transcript info
    - Skips existing transcripts
    """
```

#### Output JSON Format

```json
{
  "video_id": "OXPQQIREOzk",
  "language": "en",
  "subtitle_type": "Manual",
  "segments": [
    {
      "text": "Hello everyone",
      "start": 0.47,
      "duration": 0.95,
      "end": 1.42
    }
  ],
  "full_text": "Hello everyone..."
}
```

---

### 5.9 substack_utils.py

**Location:** `src/utils/substack_utils.py`

**Purpose:** Downloads Substack blog articles using Python requests and BeautifulSoup.

#### Constants

```python
OUTPUT_DIR = Path("data/raw/text/substack")
URLS_FILE = Path("data/substack_urls.txt")
```

#### Key Functions

```python
def run_downloader(
    urls: Optional[List[str]] = None,
    urls_file: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Download Substack blog posts.
    
    Returns:
        List of metadata dictionaries for downloaded articles
    """

def _download_single_article(url: str, output_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Download a single Substack article.
    
    - Fetches HTML via requests
    - Parses with BeautifulSoup
    - Extracts title and body content
    - Saves as plain text
    
    Returns:
        Metadata dict or None if failed
    """

def extract_blog_slug(url: str) -> str:
    """
    Extract blog slug from URL.
    
    Handles:
    - https://myblog.substack.com → 'myblog'
    - https://www.customdomain.com → 'customdomain'
    """

def list_downloaded_articles(output_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    List all downloaded articles in the output directory.
    
    Returns:
        List of metadata dicts with file paths
    """
```

---

### 5.10 text_utils.py

**Location:** `src/utils/text_utils.py`

**Purpose:** Text processing utilities including normalization, teencode replacement, and code-switching detection.

#### Constants

```python
# Vietnamese particles for CS detection
VN_PARTICLES = {'và', 'là', 'của', 'những', 'các', 'này', 'đó', ...}

# English stop words for CS detection
EN_STOP_WORDS = {'the', 'a', 'an', 'and', 'or', 'but', 'so', 'is', ...}
```

#### Key Functions

```python
def load_teencode_dict(file_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Load teencode dictionary from file.
    
    Format: teencode<TAB>replacement (one per line)
    
    Example:
        ko\tkhông
        dc\tđược
        cx\tcũng
    """

def normalize_text(
    text: str,
    teencode_dict: Optional[Dict[str, str]] = None,
    lowercase: bool = True,
    remove_urls: bool = True,
    remove_emojis: bool = True
) -> str:
    """
    Normalize Vietnamese text.
    
    Operations:
    1. Lowercase conversion
    2. URL removal
    3. Emoji removal
    4. Teencode replacement
    5. Whitespace normalization
    """

def contains_code_switching(text: str) -> bool:
    """
    Check if text contains code-switching.
    
    Uses "Intersection Rule":
    - Must have ≥1 Vietnamese particle AND
    - Must have ≥1 English stop word
    """

def extract_cs_chunks(
    text: str,
    context_sentences: int = 1,
    min_cs_ratio: float = 0.1
) -> List[Dict[str, Any]]:
    """
    Extract code-switching chunks with context.
    
    Returns:
        [{
            'cs_sentence': 'The CS sentence',
            'context_before': ['Previous sentence'],
            'context_after': ['Next sentence'],
            'full_chunk': 'Complete chunk text',
            'cs_ratio': 0.35,
            'sentence_index': 5
        }, ...]
    """
```

---

### 5.11 data_utils.py

**Location:** `src/utils/data_utils.py`

**Purpose:** Database connectivity and operations for PostgreSQL. Handles all CRUD operations for the multi-table schema.

#### Database Connection

```python
def get_pg_connection() -> psycopg2.extensions.connection:
    """
    Establish PostgreSQL connection.
    
    Uses DATABASE_URL environment variable or defaults to:
    postgresql://admin:secret_password@localhost:5432/data_factory
    """
```

#### Source Operations

```python
def get_or_create_source(
    source_type: str,
    external_id: str,
    name: Optional[str] = None,
    url: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Get existing source or create new one.
    
    source_type options:
    - 'youtube_with_transcript'
    - 'youtube_without_transcript'
    - 'substack'
    - 'manual_upload'
    
    Returns:
        UUID of the source
    """
```

#### Sample Operations

```python
def insert_sample(
    content_type: str,           # 'audio_primary' or 'text_primary'
    pipeline_type: str,          # Pipeline this sample follows
    audio_file_path: str = None,
    text_file_path: str = None,
    external_id: str = None,     # Video ID, article slug
    source_id: str = None,
    duration_seconds: float = None,
    cs_ratio: float = None,
    source_metadata: Dict = None,
    acoustic_metadata: Dict = None,
    linguistic_metadata: Dict = None,
    priority: int = 0
) -> str:
    """
    Insert a new sample into the samples table.
    
    Returns:
        UUID of the inserted sample
    """

def sample_exists(
    audio_file_path: str = None,
    external_id: str = None
) -> bool:
    """
    Check if a sample already exists in the database.
    """

def get_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a sample by ID.
    """

def transition_state(
    sample_id: str,
    new_state: str,
    executor: str = 'system'
) -> bool:
    """
    Transition sample to a new processing state.
    
    Valid states:
    RAW → ALIGNED → SEGMENTED → ENHANCED → TRANSLATED → REVIEWED
    """
```

#### Revision Operations

```python
def insert_transcript_revision(
    sample_id: str,
    transcript_text: str,
    revision_type: str,           # 'raw', 'asr_generated', 'human_corrected', 'mfa_aligned'
    revision_source: str = None,  # 'youtube_api', 'whisper', 'annotator_123'
    timestamps: List = None,      # [{start_ms, end_ms, text}, ...]
    metadata: Dict = None
) -> str:
    """
    Insert a new transcript revision.
    
    Returns:
        UUID of the revision
    """

def get_latest_transcript(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest transcript revision for a sample.
    """

def insert_translation_revision(
    sample_id: str,
    translation_text: str,
    target_language: str,
    revision_type: str,           # 'llm_generated', 'human_corrected', 'final'
    revision_source: str = None,
    source_transcript_revision_id: str = None,
    confidence_score: float = None
) -> str:
    """
    Insert a new translation revision.
    """

def get_latest_translation(sample_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest translation revision for a sample.
    """
```

#### Query Operations

```python
def get_review_queue(
    task_type: str = None,
    limit: int = 100,
    min_priority: int = 0
) -> List[Dict[str, Any]]:
    """
    Get samples ready for review in Label Studio.
    """

def get_pipeline_stats() -> List[Dict[str, Any]]:
    """
    Get processing statistics by pipeline and state.
    """
```

#### Utility Functions

```python
def calculate_cs_ratio(text: str) -> float:
    """
    Calculate code-switching ratio of a text.
    
    Uses word-level detection of Vietnamese and English tokens.
    
    Returns:
        Float between 0.0 and 1.0
    """

def log_processing(
    sample_id: str,
    step_name: str,
    status: str,
    input_state: str = None,
    output_state: str = None,
    metadata: Dict = None
) -> None:
    """
    Log a processing step to the audit trail.
    """
```

---

## 3. Directory Structure

```
src/
├── ingest_youtube.py           # YouTube ingestion orchestrator
├── ingest_substack.py          # Substack ingestion orchestrator
├── label_studio_sync.py        # Label Studio integration
├── sync_daemon.py              # DVC auto-sync service
├── export_reviewed.py          # Export reviewed data
├── webhook_server.py           # FastAPI webhook handler
└── utils/
    ├── __init__.py
    ├── data_utils.py           # Database operations
    ├── video_downloading_utils.py   # YouTube audio download
    ├── transcript_downloading_utils.py  # YouTube transcript download
    ├── substack_utils.py       # Substack article download
    └── text_utils.py           # Text processing utilities
```

---

## 4. Dependencies

| Package | Purpose |
|---------|---------|
| `yt-dlp` | YouTube video/audio download |
| `youtube-transcript-api` | YouTube transcript API |
| `requests` | HTTP requests |
| `beautifulsoup4` | HTML parsing |
| `lxml` | XML/HTML parser |
| `psycopg2-binary` | PostgreSQL driver |
| `dvc[gdrive]` | Data version control with Google Drive |
| `fastapi` | Webhook server framework |
| `uvicorn[standard]` | ASGI server for FastAPI |
| `pydantic` | Data validation |
| `python-multipart` | Form data handling |

---

## 5. Error Handling

All scripts follow consistent error handling patterns:

1. **Validation Errors**: Raised for invalid inputs (missing files, bad URLs)
2. **Network Errors**: Caught and logged, processing continues
3. **Database Errors**: Connection errors are caught, data saved to JSONL for retry
4. **Processing Errors**: Individual item failures don't stop batch processing

Example pattern:
```python
try:
    result = process_item(item)
    stats['success'] += 1
except SpecificError as e:
    print(f"[ERROR] {item}: {e}")
    stats['failed'] += 1
    continue  # Process next item
```

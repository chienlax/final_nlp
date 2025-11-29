# 05. Script Details

This document provides detailed documentation for all scripts in the `src/` directory.

---

## Table of Contents

1. [Ingestion Scripts](#1-ingestion-scripts)
2. [Preprocessing Scripts](#2-preprocessing-scripts)
3. [Utility Modules](#3-utility-modules)
4. [Other Scripts](#4-other-scripts)

---

## 1. Ingestion Scripts

### ingest_youtube.py

**Location:** `src/ingest_youtube.py`

**Purpose:** YouTube ingestion orchestrator. Downloads videos with transcripts and ingests them into the database.

#### Usage

```bash
# Download from YouTube channel
python src/ingest_youtube.py https://www.youtube.com/@ChannelName

# Download specific video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Skip download, use existing metadata.jsonl
python src/ingest_youtube.py --skip-download

# Dry run (no database writes)
python src/ingest_youtube.py --skip-download --dry-run
```

#### Command Line Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `urls` | positional | YouTube video or channel URLs |
| `--skip-download` | flag | Use existing `metadata.jsonl` |
| `--dry-run` | flag | Preview without database writes |

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

#### Key Behavior

- **Rejects videos without transcripts** - Only processes videos with subtitles
- **Detects subtitle type** - Manual vs auto-generated
- **Initial state** - Samples start in `RAW` state

#### Output Files

| File | Location |
|------|----------|
| Audio | `data/raw/audio/{video_id}.wav` |
| Transcript | `data/raw/text/{video_id}_transcript.json` |
| Metadata | `data/raw/metadata.jsonl` |

---

## 2. Preprocessing Scripts

### whisperx_align.py

**Location:** `src/preprocessing/whisperx_align.py`

**Purpose:** WhisperX forced alignment to extract word-level timestamps from verified transcripts.

#### Usage

```bash
# Align specific sample
python src/preprocessing/whisperx_align.py --sample-id <uuid>

# Batch processing
python src/preprocessing/whisperx_align.py --batch --limit 10

# Specify device
python src/preprocessing/whisperx_align.py --batch --device cuda
```

#### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--sample-id` | UUID | - | Process specific sample |
| `--batch` | flag | - | Process multiple samples |
| `--limit` | int | 10 | Max samples in batch mode |
| `--device` | str | `cuda` | Device (`cuda` or `cpu`) |

#### Process

1. Load WhisperX with Vietnamese alignment model
2. Load verified transcript from database
3. Force-align transcript with audio
4. Extract word and sentence timestamps
5. Store in `transcript_revisions` table
6. Transition state: `TRANSCRIPT_VERIFIED` → `ALIGNED`

#### Vietnamese Model

- **Model:** `nguyenvulebinh/wav2vec2-base-vi-vlsp2020`
- **Framework:** HuggingFace through WhisperX

#### Output Format

```json
{
  "word_timestamps": [
    {"word": "Xin", "start": 0.5, "end": 0.7, "score": 0.95}
  ],
  "sentence_timestamps": [
    {"text": "Xin chào", "start": 0.5, "end": 1.0, "words": [...]}
  ]
}
```

---

### segment_audio.py

**Location:** `src/preprocessing/segment_audio.py`

**Purpose:** Segment audio into 10-30 second chunks at sentence boundaries.

#### Usage

```bash
# Segment specific sample
python src/preprocessing/segment_audio.py --sample-id <uuid>

# Batch processing
python src/preprocessing/segment_audio.py --batch --limit 10

# Custom duration range
python src/preprocessing/segment_audio.py --batch --min-duration 10 --max-duration 30
```

#### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--sample-id` | UUID | - | Process specific sample |
| `--batch` | flag | - | Process multiple samples |
| `--limit` | int | 10 | Max samples in batch mode |
| `--min-duration` | float | 10.0 | Minimum segment duration (seconds) |
| `--max-duration` | float | 30.0 | Maximum segment duration (seconds) |

#### Process

1. Load aligned transcript with word timestamps
2. Group words into sentences
3. Merge sentences into 10-30s segments
4. Slice audio files
5. Create segment records in `segments` table
6. Transition state: `ALIGNED` → `SEGMENTED`

#### Output

- Audio files: `data/segments/{sample_id}/0000.wav`, `0001.wav`, ...
- Database records with word timestamps per segment

---

### translate.py

**Location:** `src/preprocessing/translate.py`

**Purpose:** Translate code-switched transcripts using Gemini API with key rotation.

#### Usage

```bash
# Translate specific sample
python src/preprocessing/translate.py --sample-id <uuid>

# Batch processing
python src/preprocessing/translate.py --batch --limit 10

# Check API key status
python src/preprocessing/translate.py --check-keys
```

#### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--sample-id` | UUID | - | Process specific sample |
| `--batch` | flag | - | Process multiple samples |
| `--limit` | int | 10 | Max samples in batch mode |
| `--check-keys` | flag | - | Show API key status |

#### API Key Configuration

```bash
# Environment variables
export GEMINI_API_KEY_1="your-first-key"
export GEMINI_API_KEY_2="your-second-key"
export GEMINI_API_KEY_3="your-third-key"
```

#### Key Rotation Strategy

1. Try first available (non-exhausted) key
2. On rate limit → mark key as exhausted, switch to next
3. If all keys exhausted → stop and wait for next day
4. Keys reset daily (tracked in `api_keys` table)

#### Process

1. Get next available API key
2. Translate FULL transcript (for global context)
3. Split translation to match segments
4. Store full translation in `translation_revisions`
5. Store per-segment translations in `segment_translations`
6. Transition state: `SEGMENT_VERIFIED` → `TRANSLATED`

---

### denoise_audio.py

**Location:** `src/preprocessing/denoise_audio.py`

**Purpose:** Remove background noise from segment audio using DeepFilterNet.

#### Usage

```bash
# Denoise specific sample
python src/preprocessing/denoise_audio.py --sample-id <uuid>

# Batch processing
python src/preprocessing/denoise_audio.py --batch --limit 10
```

#### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--sample-id` | UUID | - | Process specific sample |
| `--batch` | flag | - | Process multiple samples |
| `--limit` | int | 10 | Max samples in batch mode |

#### Process

1. Load DeepFilterNet3 model
2. Process each verified segment
3. Remove background noise (NO enhancement/upscaling)
4. **Replace** original audio with denoised version
5. Transition state: `TRANSLATION_REVIEW` → `DENOISED`

#### Note

DeepFilterNet only removes noise. It does NOT:
- Enhance audio quality
- Upscale sample rate
- Modify speech characteristics

---

## 3. Utility Modules

### data_utils.py

**Location:** `src/utils/data_utils.py`

**Purpose:** Database connectivity and operations for PostgreSQL.

#### Database Connection

```python
def get_pg_connection() -> psycopg2.extensions.connection:
    """Establish PostgreSQL connection."""
```

Uses `DATABASE_URL` environment variable or defaults to Docker Compose credentials.

#### Source Operations

```python
def get_or_create_source(
    source_type: str,
    external_id: str,
    name: Optional[str] = None,
    url: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """Get existing source or create new one."""
```

#### Sample Operations

```python
def insert_sample(...) -> str:
    """Insert a new sample into the samples table."""

def sample_exists(audio_file_path: str = None, external_id: str = None) -> bool:
    """Check if a sample already exists."""

def update_sample_state(sample_id: str, new_state: str) -> bool:
    """Update sample processing state."""
```

#### Segment Operations

```python
def insert_segment(
    sample_id: str,
    segment_index: int,
    audio_path: str,
    transcript_text: str,
    start_time: float,
    end_time: float,
    word_timestamps: List[Dict],
    alignment_score: float
) -> str:
    """Insert a segment record."""

def get_segments_for_sample(sample_id: str) -> List[Dict]:
    """Get all segments for a sample."""
```

#### Translation Operations

```python
def insert_segment_translation(
    segment_id: str,
    translation_text: str,
    translation_version: int
) -> str:
    """Insert segment translation."""

def get_api_key() -> Optional[Dict]:
    """Get next available Gemini API key."""

def mark_api_key_exhausted(key_id: str) -> None:
    """Mark API key as rate-limited for today."""
```

#### Logging

```python
def log_processing(
    sample_id: str,
    step_name: str,
    status: str,
    metadata: Dict = None
) -> None:
    """Log a processing step to audit trail."""
```

---

### video_downloading_utils.py

**Location:** `src/utils/video_downloading_utils.py`

**Purpose:** Download YouTube videos as 16kHz mono WAV using yt-dlp.

#### Constants

```python
SAMPLE_RATE = 16000      # 16kHz
CHANNELS = 1             # Mono
MIN_DURATION = 120       # 2 minutes
MAX_DURATION = 3600      # 60 minutes
```

#### Key Functions

```python
def download_channels(url_list: List[str]) -> None:
    """Download audio from YouTube channels/videos."""

def save_jsonl(append: bool = True) -> None:
    """Save metadata to JSONL file."""
```

---

### transcript_downloading_utils.py

**Location:** `src/utils/transcript_downloading_utils.py`

**Purpose:** Download YouTube transcripts with timestamps.

#### Key Functions

```python
def get_transcript_info(video_id: str) -> Dict[str, Any]:
    """
    Fetch transcript with subtitle type detection.
    
    Returns:
        {
            'segments': [{text, start, end}, ...],
            'subtitle_type': 'Manual' | 'Auto-generated' | 'Not Available',
            'language': 'en' | 'vi'
        }
    """

def download_transcripts_from_metadata() -> List[Dict]:
    """Download transcripts for all videos in metadata.jsonl."""
```

---

### text_utils.py

**Location:** `src/utils/text_utils.py`

**Purpose:** Text processing utilities including normalization and CS detection.

#### Key Functions

```python
def load_teencode_dict(file_path: Path = None) -> Dict[str, str]:
    """Load teencode dictionary from file."""

def normalize_text(text: str, teencode_dict: Dict = None) -> str:
    """Normalize Vietnamese text."""

def contains_code_switching(text: str) -> bool:
    """Check if text contains code-switching."""

def calculate_cs_ratio(text: str) -> float:
    """Calculate code-switching ratio of text."""
```

---

## 4. Other Scripts

### label_studio_sync.py

**Location:** `src/label_studio_sync.py`

**Purpose:** Synchronize data between PostgreSQL and Label Studio.

```bash
# Push samples for annotation
python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed annotations
python src/label_studio_sync.py pull --task-type transcript_correction

# Check status
python src/label_studio_sync.py status
```

### sync_daemon.py

**Location:** `src/sync_daemon.py`

**Purpose:** Automatic DVC sync service.

```bash
# Continuous sync (5-minute interval)
python src/sync_daemon.py

# Single sync
python src/sync_daemon.py --once
```

### export_reviewed.py

**Location:** `src/export_reviewed.py`

**Purpose:** Export reviewed samples for training.

```bash
# Export all reviewed samples
python src/export_reviewed.py --output-dir data/reviewed
```

---

## 5. Directory Structure

```
src/
├── ingest_youtube.py           # YouTube ingestion
├── label_studio_sync.py        # Label Studio integration
├── sync_daemon.py              # DVC sync service
├── export_reviewed.py          # Export for training
├── preprocessing/
│   ├── __init__.py
│   ├── whisperx_align.py       # WhisperX alignment
│   ├── segment_audio.py        # Audio segmentation
│   ├── translate.py            # Gemini translation
│   └── denoise_audio.py        # DeepFilterNet denoising
└── utils/
    ├── data_utils.py           # Database operations
    ├── video_downloading_utils.py
    ├── transcript_downloading_utils.py
    └── text_utils.py
```

---

## Related Documentation

- [04_workflow.md](04_workflow.md) - Pipeline workflow
- [06_database_design.md](06_database_design.md) - Database schema

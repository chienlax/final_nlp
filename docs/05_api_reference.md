# API Reference

Developer documentation for scripts and utility modules.

---

## Table of Contents

1. [Ingestion Scripts](#1-ingestion-scripts)
2. [Preprocessing Scripts](#2-preprocessing-scripts)
3. [Utility Modules](#3-utility-modules)

---

## 1. Ingestion Scripts

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
[STEP 4/4] Ingest to database (RAW state)
```

#### Key Behavior

- **Rejects videos without transcripts**
- **Detects subtitle type**: Manual vs auto-generated
- **Initial state**: `RAW`

#### Output Files

| File | Location |
|------|----------|
| Audio | `data/raw/audio/{video_id}.wav` |
| Transcript | `data/raw/text/{video_id}_transcript.json` |
| Metadata | `data/raw/metadata.jsonl` |

---

## 2. Preprocessing Scripts

### gemini_process.py

**Location:** `src/preprocessing/gemini_process.py`

**Purpose:** Unified transcription + translation using Gemini's multimodal capabilities.

#### Features

- **Hybrid single-pass**: Full audio context + structured JSON output
- **Few-shot prompting**: Vietnamese-English code-switching examples
- **Adaptive chunking**: Auto-splits audio >27 minutes with overlap
- **Deduplication**: Removes duplicate sentences from chunk overlaps
- **Issue flagging**: Marks problematic translations for repair

#### Constants

```python
MAX_AUDIO_DURATION_SECONDS = 27 * 60  # Chunking threshold
CHUNK_OVERLAP_SECONDS = 18            # Overlap between chunks
TEXT_SIMILARITY_THRESHOLD = 0.8       # Deduplication threshold
OVERLAP_TIME_TOLERANCE_SECONDS = 2.0  # Timestamp tolerance
```

#### Output Schema

```json
{
  "sentences": [
    {
      "text": "Original transcription (code-switched)",
      "start": 5.2,
      "end": 8.7,
      "duration": 3.5,
      "translation": "Pure Vietnamese translation"
    }
  ]
}
```

#### State Transition

`RAW` → `TRANSLATED` (with `needs_translation_review` flag if issues)

---

### gemini_repair_translation.py

**Location:** `src/preprocessing/gemini_repair_translation.py`

**Purpose:** Re-translate sentences flagged with translation issues.

#### Key Functions

```python
def get_samples_with_translation_issues() -> List[Dict]:
    """Query samples where has_translation_issues = TRUE."""

def repair_sentence_translations(
    sentences: List[Dict],
    issue_indices: List[int],
    api_key: str
) -> List[Dict]:
    """Re-translate specific sentences by index."""
```

---

### whisperx_align.py

**Location:** `src/preprocessing/whisperx_align.py`

**Purpose:** WhisperX forced alignment for word-level timestamps.

#### Vietnamese Model

- **Model:** `nguyenvulebinh/wav2vec2-base-vi-vlsp2020`
- **Framework:** WhisperX with HuggingFace backend

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

#### State Transition

`TRANSCRIPT_VERIFIED` → `ALIGNED`

---

### segment_audio.py

**Location:** `src/preprocessing/segment_audio.py`

**Purpose:** Segment audio into 10-30 second chunks at sentence boundaries.

#### Key Behavior

1. Group words into sentences
2. Merge sentences into 10-30s segments
3. Slice audio files
4. Create segment records

#### Output

- Audio: `data/segments/{sample_id}/0000.wav`, `0001.wav`, ...
- Database: `segments` table with word timestamps

#### State Transition

`ALIGNED` → `SEGMENTED`

---

### denoise_audio.py

**Location:** `src/preprocessing/denoise_audio.py`

**Purpose:** Remove background noise using DeepFilterNet.

#### Key Behavior

- **Replaces** original audio with denoised version
- Does NOT enhance/upscale audio
- Only removes noise

#### State Transition

`TRANSLATION_REVIEW` → `DENOISED`

---

## 3. Utility Modules

### data_utils.py

**Location:** `src/utils/data_utils.py`

**Purpose:** Database connectivity and operations.

#### Connection

```python
def get_pg_connection() -> psycopg2.extensions.connection:
    """
    Establish PostgreSQL connection.
    Uses DATABASE_URL environment variable.
    """
```

#### Sample Operations

```python
def insert_sample(
    source_id: str,
    external_id: str,
    audio_file_path: str,
    subtitle_type: str,
    duration_seconds: float,
    cs_ratio: float,
    source_metadata: Dict
) -> str:
    """Insert new sample, returns sample_id."""

def sample_exists(
    audio_file_path: str = None,
    external_id: str = None
) -> bool:
    """Check if sample already exists."""

def update_sample_state(
    sample_id: str,
    new_state: str
) -> bool:
    """Update processing state."""

def get_samples_by_state(
    state: str,
    limit: int = None
) -> List[Dict]:
    """Get samples in specific state."""
```

#### Revision Operations

```python
def add_transcript_revision(
    sample_id: str,
    transcript_text: str,
    revision_type: str,
    sentence_timestamps: List[Dict] = None,
    word_timestamps: List[Dict] = None,
    has_translation_issues: bool = False,
    translation_issue_indices: List[int] = None
) -> str:
    """Add new transcript revision, returns revision_id."""

def add_translation_revision(
    sample_id: str,
    translation_text: str,
    revision_type: str,
    sentence_translations: List[Dict] = None
) -> str:
    """Add new translation revision, returns revision_id."""
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
    """Insert segment record."""

def get_segments_for_sample(sample_id: str) -> List[Dict]:
    """Get all segments for a sample."""
```

#### Logging

```python
def log_processing(
    sample_id: str,
    step_name: str,
    status: str,
    metadata: Dict = None,
    error_message: str = None
) -> None:
    """Log processing step to audit trail."""
```

---

### text_utils.py

**Location:** `src/utils/text_utils.py`

**Purpose:** Text processing and code-switching detection.

#### Functions

```python
def load_teencode_dict(file_path: Path = None) -> Dict[str, str]:
    """Load Vietnamese teencode dictionary."""

def normalize_text(
    text: str,
    teencode_dict: Dict = None
) -> str:
    """
    Normalize Vietnamese text:
    - Expand teencode
    - Fix diacritics
    - Clean whitespace
    """

def contains_code_switching(text: str) -> bool:
    """
    Check for code-switching using Intersection Rule:
    - ≥1 Vietnamese particle (và, là, của, etc.)
    - AND ≥1 English stop word (the, and, is, etc.)
    """

def calculate_cs_ratio(text: str) -> float:
    """Calculate code-switching ratio (0.0 to 1.0)."""
```

---

### video_downloading_utils.py

**Location:** `src/utils/video_downloading_utils.py`

**Purpose:** Download YouTube videos as WAV using yt-dlp.

#### Constants

```python
SAMPLE_RATE = 16000      # 16kHz
CHANNELS = 1             # Mono
MIN_DURATION = 120       # 2 minutes
MAX_DURATION = 3600      # 60 minutes
```

#### Functions

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

#### Functions

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

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🛠️ [Command Reference](03_command_reference.md) - All commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues

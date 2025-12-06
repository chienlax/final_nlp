# Architecture & Workflow

Technical documentation for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                   │
│                                                                           │
│   YouTube   ──►   Gemini    ──►  Streamlit  ──►  Export  │
│   Ingest         Process       Review         Dataset   │
│                                                                           │
│   pending ────► transcribed ───► reviewed ────► exported │
│       │                                                                   │
│       └───► Denoise (Optional)                                         │
│           (DeepFilterNet)                                                │
│           modifies audio_path,                                           │
│           keeps state='pending'                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Processing States

| State | Description | Next Action |
|-------|-------------|-------------|
| `pending` | Audio downloaded, ready for processing | Run Gemini OR denoise first |
| `transcribed` | Transcription + translation complete | Review in Streamlit |
| `reviewed` | Human review complete | Export dataset |
| `exported` | Dataset generated | Training ready |
| `rejected` | Video marked as unusable | Archive |

**Note on Denoising:** The `denoise_audio.py` script modifies `audio_path` to point to the denoised version but keeps the state as `pending`. This ensures `gemini_process.py` can find and process the denoised audio.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Local Machine                             │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Python Environment                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │   │
│  │  │ ingest_     │  │ denoise_    │  │ gemini_         │   │   │
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
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Streamlit App                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │   │
│  │  │ Waveform    │  │ Segment     │  │ Upload          │   │   │
│  │  │ Player      │  │ Editor      │  │ Interface       │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                     Tailscale (Optional)                        │
│                              │                                   │
└──────────────────────────────┼───────────────────────────────────┘
                               │
                     Remote Reviewers (Browser)
```

---

## Database Schema

The project uses SQLite with WAL mode for concurrent access.

### Videos Table

Stores metadata for each ingested YouTube video or uploaded audio.

```sql
CREATE TABLE videos (
    video_id        TEXT PRIMARY KEY,
    url             TEXT,
    title           TEXT,
    channel_name    TEXT,
    reviewer        TEXT,                    -- NEW: Assigned reviewer
    duration_seconds INTEGER,
    audio_path      TEXT NOT NULL,
    denoised_audio_path TEXT,               -- NEW: Path to denoised version
    processing_state TEXT DEFAULT 'pending',
    source_type     TEXT DEFAULT 'youtube',  -- NEW: 'youtube' or 'upload'
    upload_metadata TEXT,                    -- NEW: JSON metadata for uploads
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Segments Table

Stores individual segments with transcription and translation.

```sql
CREATE TABLE segments (
    segment_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id            TEXT NOT NULL,
    chunk_id            TEXT,                    -- NEW: Reference to chunk
    segment_index       INTEGER,
    start_ms            INTEGER NOT NULL,
    end_ms              INTEGER NOT NULL,
    transcript          TEXT,
    translation         TEXT,
    reviewed_transcript TEXT,                    -- Edited transcript
    reviewed_translation TEXT,                   -- Edited translation
    reviewed_start_ms   INTEGER,                 -- NEW: Adjusted timing
    reviewed_end_ms     INTEGER,                 -- NEW: Adjusted timing
    is_reviewed         INTEGER DEFAULT 0,       -- NEW: Review status
    is_rejected         INTEGER DEFAULT 0,
    reviewer_notes      TEXT,                    -- NEW: Review comments
    reviewed_at         DATETIME,                -- NEW: Review timestamp
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
);
```

### Chunks Table (NEW)

For long videos (>10 minutes), audio is split into chunks for independent processing.

```sql
CREATE TABLE chunks (
    chunk_id        TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    audio_path      TEXT NOT NULL,
    processing_state TEXT DEFAULT 'pending',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);
```

### Indexes

```sql
CREATE INDEX idx_segments_video_id ON segments(video_id);
CREATE INDEX idx_videos_state ON videos(processing_state);
```

---

## Audio Processing Specifications

### Input Requirements

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16 kHz |
| Channels | Mono |
| Format | WAV (PCM 16-bit) |
| Duration | 2-60 minutes per video |

### Chunking Strategy

Gemini processing uses intelligent chunking:

| Parameter | Value |
|-----------|-------|
| Chunk Size | 10 minutes |
| Overlap | 10 seconds |
| Tail Threshold | ≤11 minutes (don't split if tail is ≤11 min) |

### Output Segments

| Parameter | Value |
|-----------|-------|
| Min Duration | 2 seconds |
| Max Duration | 25 seconds |
| Format | WAV (16kHz mono) |

---

## Gemini Processing

### Prompt Structure

Each audio chunk is processed with a structured prompt:

```
System: You are a transcription and translation assistant for 
Vietnamese-English code-switching speech.

Task: Transcribe and translate the audio into segments.

Output Format (JSON):
{
  "segments": [
    {
      "text": "Original transcription",
      "start": 0.0,
      "end": 5.5,
      "translation": "English translation"
    }
  ]
}

Rules:
- Keep segments 2-25 seconds
- Preserve code-switching as-is
- Translate to natural English
```

### Deduplication

When merging overlapping chunks, segments are deduplicated using:
1. Time-based matching (within 500ms)
2. Text similarity (>80% match)
3. Preference for later chunk's version

---

## Streamlit Review App

### Features

| Feature | Description |
|---------|-------------|
| Dashboard | Statistics and state overview |
| Channel Filtering | Filter videos by channel name |
| Chunk Selection | Review specific chunks of long videos |
| Audio Player | Play segments with auto-pause at boundaries |
| Segment Editor | Editable transcript and translation |
| Duration Badges | Warnings for segments >25s |
| Reviewer Assignment | Assign reviewers per video (dropdown) |
| Transcript Upload/Remove | Manage transcript files per video |
| Keyboard Shortcuts | Alt+A (approve), Alt+S (save), Alt+R (reject) |
| Split Button | Split long segments at cursor |
| Reject Toggle | Mark segments as rejected |
| Playlist Metadata | Fetch video info from YouTube playlists |

### State Management

Review state is stored in SQLite:
- `reviewed_transcript`: Edited transcript (or NULL if unchanged)
- `reviewed_translation`: Edited translation (or NULL if unchanged)
- `reviewed_start_ms`/`reviewed_end_ms`: Adjusted timing (NEW)
- `is_reviewed`: 1 if segment approved (NEW)
- `is_rejected`: 1 if segment should be excluded
- `reviewer_notes`: Comments from reviewer (NEW)

---

## Export Format

### Output Structure

```
data/export/
├── audio/
│   ├── VIDEO_ID_000001.wav
│   ├── VIDEO_ID_000002.wav
│   └── ...
└── manifest.tsv
```

### Manifest Format

TSV file compatible with HuggingFace datasets:

```tsv
audio_path	transcript	translation	duration_ms
audio/VIDEO_ID_000001.wav	Original text	English text	4500
audio/VIDEO_ID_000002.wav	Xin chào	Hello	2300
```

---

## Data Flow

```
1. INGEST
   YouTube URL → yt-dlp → data/raw/audio/{channel_id}/{video_id}.wav
                       → SQLite: videos table (state=pending)
                       → Queue chunking jobs to data/raw/chunk_jobs.jsonl

2. CHUNK (Optional, for videos >10 min)
   data/raw/audio/*.wav → chunk_audio.py → data/raw/chunks/{video_id}/chunk_*.wav
                                         → SQLite: chunks table

3. DENOISE (Optional)
   data/raw/audio/*.wav → DeepFilterNet → data/denoised/*_denoised.wav
                                        → SQLite: update denoised_audio_path
                                        → Keep state='pending'

4. PROCESS
   Audio (original or denoised) → Gemini 2.5 Pro → JSON segments
                                                  → SQLite: segments table, state=transcribed
   Can process full video OR individual chunks with --chunk-id flag

5. REVIEW
   Streamlit app ← SQLite: segments
   User edits   → SQLite: reviewed_transcript, reviewed_translation
   User assigns → SQLite: reviewer column
   User uploads → Transcript files managed per video
   User rejects → SQLite: is_rejected=1, state=reviewed

6. EXPORT
   SQLite: approved segments → pydub: cut audio
                            → data/export/audio/*.wav
                            → data/export/manifest.tsv
                            → SQLite: state=exported
```

---

## File Organization

```
final_nlp/
├── data/
│   ├── lab_data.db          # SQLite database
│   ├── raw/
│   │   ├── audio/           # Original YouTube audio (organized by channel)
│   │   ├── chunks/          # NEW: Chunked audio for long videos
│   │   ├── chunk_jobs.jsonl # NEW: Chunking queue
│   │   └── metadata.jsonl   # Download metadata
│   ├── denoised/            # DeepFilterNet output
│   ├── segments/            # Intermediate segments
│   ├── review/              # NEW: Uploaded transcripts
│   │   └── transcripts/
│   └── export/              # Final dataset
│       ├── audio/           # Training audio files
│       └── manifest.tsv     # Dataset manifest
├── src/
│   ├── db.py                # SQLite utilities
│   ├── ingest_youtube.py    # YouTube download
│   ├── review_app.py        # Streamlit app
│   ├── export_final.py      # Dataset export
│   ├── setup_gdrive_auth.py # Google Drive OAuth
│   ├── preprocessing/
│   │   ├── chunk_audio.py       # NEW: Audio chunking
│   │   ├── denoise_audio.py     # DeepFilterNet
│   │   └── gemini_process.py    # Transcription
│   └── utils/
│       ├── video_downloading_utils.py
│       └── text_utils.py
├── init_scripts/
│   └── sqlite_schema.sql    # Database schema
└── docs/
    ├── 01_getting_started.md
    ├── 02_architecture.md   # This file
    ├── 03_command_reference.md
    ├── 04_troubleshooting.md
    ├── 05_api_reference.md
    ├── 06_known_caveats.md
    └── 07_todo-list.md
```

---

## Next Steps

- 🛠️ [Command Reference](03_command_reference.md) - All available commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer documentation

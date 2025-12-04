# Architecture & Workflow

Technical documentation for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                   │
│                                                                           │
│   YouTube   ──►   Denoise   ──►   Gemini    ──►  Streamlit  ──►  Export  │
│   Ingest        (DeepFilterNet)   Process       Review         Dataset   │
│                                                                           │
│   ingested ────► denoised ──────► processed ───► reviewed ────► exported │
└──────────────────────────────────────────────────────────────────────────┘
```

### Processing States

| State | Description | Next Action |
|-------|-------------|-------------|
| `ingested` | Audio downloaded from YouTube | Run denoising |
| `denoised` | Background noise removed | Run Gemini processing |
| `processed` | Transcription + translation complete | Review in Streamlit |
| `reviewed` | Human review complete | Export dataset |
| `exported` | Dataset generated | Training ready |

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

Stores metadata for each ingested YouTube video.

```sql
CREATE TABLE videos (
    video_id        TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT,
    channel_name    TEXT,
    duration_seconds INTEGER,
    audio_path      TEXT NOT NULL,
    processing_state TEXT DEFAULT 'ingested',
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
    start_ms            INTEGER NOT NULL,
    end_ms              INTEGER NOT NULL,
    transcript          TEXT,
    translation         TEXT,
    transcript_reviewed TEXT,
    translation_reviewed TEXT,
    is_rejected         INTEGER DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
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
| Waveform Player | Interactive audio visualization |
| Segment Grid | Editable transcript and translation |
| Duration Badges | Warnings for segments >25s |
| Split Button | Split long segments at cursor |
| Reject Toggle | Mark segments as rejected |
| JSON Upload | Upload Gemini output for new videos |
| Audio Upload | Upload raw audio files |

### State Management

Review state is stored in SQLite:
- `transcript_reviewed`: Edited transcript (or NULL if unchanged)
- `translation_reviewed`: Edited translation (or NULL if unchanged)
- `is_rejected`: 1 if segment should be excluded

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
   YouTube URL → yt-dlp → data/raw/audio/VIDEO_ID.wav
                       → SQLite: videos table (state=ingested)

2. DENOISE
   data/raw/audio/*.wav → DeepFilterNet → data/denoised/*_denoised.wav
                                        → SQLite: update audio_path, state=denoised

3. PROCESS
   Denoised audio → Gemini 2.5 Pro → JSON segments
                                   → SQLite: segments table, state=processed

4. REVIEW
   Streamlit app ← SQLite: segments
   User edits   → SQLite: transcript_reviewed, translation_reviewed
   User rejects → SQLite: is_rejected=1

5. EXPORT
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
│   │   ├── audio/           # Original YouTube audio
│   │   └── metadata.jsonl   # Download metadata
│   ├── denoised/            # DeepFilterNet output
│   ├── segments/            # Intermediate segments
│   └── export/              # Final dataset
│       ├── audio/           # Training audio files
│       └── manifest.tsv     # Dataset manifest
├── src/
│   ├── db.py                # SQLite utilities
│   ├── ingest_youtube.py    # YouTube download
│   ├── review_app.py        # Streamlit app
│   ├── export_final.py      # Dataset export
│   ├── preprocessing/
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
    └── 06_known_caveats.md
```

---

## Next Steps

- 🛠️ [Command Reference](03_command_reference.md) - All available commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer documentation

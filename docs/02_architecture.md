# Architecture & Workflow

Technical overview of the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Processing States](#2-processing-states)
3. [Data Specifications](#3-data-specifications)
4. [Database Schema](#4-database-schema)
5. [Directory Structure](#5-directory-structure)

---

## 1. Pipeline Overview

### High-Level Flow

```
┌─────────────┐    ┌──────────────┐    ┌──────────────────┐    ┌─────────────┐
│   YouTube   │───►│   Gemini     │───►│  Unified Review  │───►│  Training   │
│  Ingestion  │    │  Processing  │    │  (Label Studio)  │    │   Export    │
└─────────────┘    └──────────────┘    └──────────────────┘    └─────────────┘
     RAW            TRANSLATED          REVIEW_PREPARED         FINAL
                                           ↓
                                    15 sentences/task
                                    sentence-level audio
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| YouTube-only source | Focus on videos with existing transcripts |
| Transcript required | Only process videos with manual/auto subtitles |
| Unified Gemini processing | Single-pass transcription + translation |
| Unified review (15 sentences/task) | Efficient chunked review with sentence-level audio |
| Sentence-level output | Individual sentence WAVs for training flexibility |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Docker Environment                             │
│                                                                          │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────┐  │
│  │  PostgreSQL  │◄───│  Python Scripts  │───►│    Label Studio      │  │
│  │ (data_factory│    │ (ingestion,      │    │  (localhost:8085)    │  │
│  │  + label_    │    │  preprocessing)  │    │                      │  │
│  │  studio DBs) │    │                  │    └──────────┬───────────┘  │
│  └──────────────┘    └────────┬─────────┘               │              │
│                               │                         │              │
│                               ▼                         ▼              │
│                      ┌──────────────────┐      ┌──────────────┐        │
│                      │   Audio Server   │◄─────│   Browser    │        │
│                      │ (localhost:8081) │      │   (User)     │        │
│                      └──────────────────┘      └──────────────┘        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Processing States

### State Enum

```sql
CREATE TYPE processing_state AS ENUM (
    'RAW',                  -- Just ingested from YouTube
    'TRANSLATED',           -- Gemini transcription + translation complete
    'REVIEW_PREPARED',      -- Sentence audio cut, review chunks created
    'FINAL',                -- Review applied, ready for training
    'REJECTED'              -- Failed QC
);
```

### State Transition Diagram

```
RAW
 │
 │  (gemini_process.py)
 ▼
TRANSLATED
 │
 │  (prepare_review_audio.py)
 ▼
REVIEW_PREPARED ──► Label Studio (Unified Review)
 │                    - 15 sentences per task
 │                    - Sentence-level audio playback
 │                    - Transcript + Translation + Timing corrections
 │
 │  (apply_review.py)
 ▼
FINAL ──► Training Export
 │
 └──► REJECTED (at any stage)
```

### Stage Details

| Stage | Script | Human Review? | Description |
|-------|--------|---------------|-------------|
| RAW | `ingest_youtube.py` | No | Downloaded from YouTube with transcript |
| TRANSLATED | `gemini_process.py` | No | Gemini transcription + translation |
| REVIEW_PREPARED | `prepare_review_audio.py` | No | Sentence audio cut, chunks created |
| (In Label Studio) | `label_studio_sync.py push` | **Yes** | Unified review of transcript, translation, timing |
| (Review complete) | `label_studio_sync.py pull` | No | Corrections saved to database |
| FINAL | `apply_review.py` | No | Final audio cut with corrections |

---

## 3. Data Specifications

### Audio Format

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Container | `.wav` | Lossless, universal support |
| Sample Rate | `16000 Hz` | Speech recognition standard |
| Channels | `1` (Mono) | Single speaker focus |
| Bit Depth | 16-bit PCM | Standard quality |

### Duration Limits

| Type | Min | Max | Rationale |
|------|-----|-----|-----------|
| Full Video | 2 min | 60 min | Processing efficiency |
| Segment | 10 sec | 30 sec | Training optimization |

### Transcript Format

```json
{
  "video_id": "OXPQQIREOzk",
  "language": "en",
  "subtitle_type": "Manual",
  "segments": [
    {"text": "Xin chào everyone", "start": 0.47, "end": 1.42}
  ],
  "full_text": "Xin chào everyone..."
}
```

### Code-Switching Detection

**Intersection Rule**: Content must contain:
- ≥1 Vietnamese particle (`và`, `là`, `của`, etc.)
- **AND** ≥1 English stop word (`the`, `and`, `is`, etc.)

### Gemini Output Format

The `gemini_process.py` script produces structured JSON:

```json
{
  "sentences": [
    {
      "text": "Xin chào các bạn, hello everyone.",
      "start": 5.2,
      "end": 8.7,
      "duration": 3.5,
      "translation": "Xin chào các bạn, xin chào mọi người."
    }
  ]
}
```

---

## 4. Database Schema

### Entity Relationship

```
┌─────────────┐
│   sources   │  (YouTube channels)
└──────┬──────┘
       │ 1:N
       ▼
┌─────────────────────────────────────────────────────────────┐
│                          samples                             │
│  (Full videos with processing_state tracking)               │
└──────────────────────────┬──────────────────────────────────┘
                           │ 1:N
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ review_      │    │ transcript_  │    │ translation_ │
│ chunks       │    │ revisions    │    │ revisions    │
│ (15 sent/    │    │              │    │              │
│  chunk)      │    └──────────────┘    └──────────────┘
└──────┬───────┘
       │ 1:N
       ▼
┌──────────────────┐
│ sentence_        │
│ reviews          │
│ (corrections)    │
└──────────────────┘
```

### Key Tables

#### samples

```sql
CREATE TABLE samples (
    sample_id UUID PRIMARY KEY,
    external_id VARCHAR(255) UNIQUE,      -- YouTube video ID
    audio_file_path TEXT NOT NULL,
    subtitle_type subtitle_type,           -- 'manual' | 'auto_generated'
    processing_state processing_state DEFAULT 'RAW',
    duration_seconds NUMERIC(10, 2),
    cs_ratio NUMERIC(5, 4),               -- Code-switching ratio
    needs_translation_review BOOLEAN,      -- Flag for Gemini issues
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### review_chunks (NEW)

```sql
CREATE TABLE review_chunks (
    chunk_id UUID PRIMARY KEY,
    sample_id UUID REFERENCES samples(sample_id),
    chunk_index INTEGER NOT NULL,         -- 0-based chunk number
    start_sentence_idx INTEGER NOT NULL,  -- First sentence index (inclusive)
    end_sentence_idx INTEGER NOT NULL,    -- Last sentence index (exclusive)
    ls_task_id INTEGER,                   -- Label Studio task ID
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE (sample_id, chunk_index)
);
```

#### sentence_reviews (NEW)

```sql
CREATE TABLE sentence_reviews (
    review_id UUID PRIMARY KEY,
    chunk_id UUID REFERENCES review_chunks(chunk_id),
    sentence_idx INTEGER NOT NULL,         -- Index within sample
    original_text TEXT NOT NULL,
    reviewed_text TEXT,                    -- Corrected transcript
    original_translation TEXT NOT NULL,
    reviewed_translation TEXT,             -- Corrected translation
    original_start_ms INTEGER NOT NULL,
    original_end_ms INTEGER NOT NULL,
    reviewed_start_ms INTEGER,             -- Adjusted timing
    reviewed_end_ms INTEGER,               -- Adjusted timing
    is_deleted BOOLEAN DEFAULT FALSE,      -- Sentence marked for removal
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (chunk_id, sentence_idx)
);
```

#### transcript_revisions

```sql
CREATE TABLE transcript_revisions (
    revision_id UUID PRIMARY KEY,
    sample_id UUID REFERENCES samples(sample_id),
    version INTEGER NOT NULL,
    transcript_text TEXT NOT NULL,
    revision_type VARCHAR(50),            -- 'youtube_raw', 'gemini', 'human_corrected'
    sentence_timestamps JSONB,            -- [{text, start, end, duration}, ...]
    has_translation_issues BOOLEAN,       -- Flag for repair script
    translation_issue_indices INTEGER[],  -- Which sentences had issues
    UNIQUE (sample_id, version)
);
```

#### translation_revisions

```sql
CREATE TABLE translation_revisions (
    revision_id UUID PRIMARY KEY,
    sample_id UUID REFERENCES samples(sample_id),
    version INTEGER NOT NULL,
    translation_text TEXT NOT NULL,
    sentence_translations JSONB,          -- [{text, translation, start, end}, ...]
    UNIQUE (sample_id, version)
);
```

### Useful Views

```sql
-- Pipeline statistics by state
SELECT * FROM v_pipeline_stats;

-- Sample overview with transcript info
SELECT * FROM v_sample_overview;

-- Segments ready for export
SELECT * FROM v_export_ready_segments;
```

---

## 5. Directory Structure

```
final_nlp/
├── data/
│   ├── raw/                    # DVC-tracked: Ingested audio
│   │   ├── audio/              # {video_id}.wav (16kHz mono)
│   │   ├── text/               # {video_id}_transcript.json
│   │   └── metadata.jsonl
│   ├── review/                 # Sentence audio for Label Studio
│   │   └── {sample_id}/
│   │       └── sentences/
│   │           ├── 0000.wav    # Individual sentence audio (with padding)
│   │           ├── 0001.wav
│   │           └── ...
│   ├── final/                  # Final output after review
│   │   └── {sample_id}/
│   │       └── sentences/
│   │           ├── 0000.wav    # Sentence audio (reviewed timing)
│   │           ├── manifest.tsv
│   │           └── ...
│   ├── dataset/                # DVC-tracked: Training export
│   │   └── {sample_id}/
│   │       ├── sentences/
│   │       ├── manifest.tsv
│   │       └── metadata.json
│   └── db_sync/                # Database backups (DVC-tracked)
├── src/
│   ├── ingest_youtube.py
│   ├── label_studio_sync.py          # Unified review push/pull
│   ├── export_reviewed.py            # Export FINAL to dataset
│   ├── preprocessing/
│   │   ├── gemini_process.py         # Transcription + translation
│   │   ├── gemini_repair_translation.py
│   │   ├── prepare_review_audio.py   # NEW: Cut sentence audio, create chunks
│   │   ├── apply_review.py           # NEW: Apply corrections, create final
│   │   ├── whisperx_align.py         # (Optional)
│   │   ├── segment_audio.py          # (Legacy)
│   │   └── denoise_audio.py          # (Optional)
│   └── utils/
│       ├── data_utils.py
│       └── text_utils.py
├── init_scripts/
│   ├── 01_schema.sql
│   └── 02_review_system_migration.sql  # NEW: Review tables
├── label_studio_templates/
│   ├── unified_review.xml            # NEW: Single review template
│   └── archive/                      # Legacy templates
│       ├── transcript_correction.xml
│       ├── segment_review.xml
│       └── translation_review.xml
├── docker-compose.yml
└── requirements.txt
```

### Data Flow

```
data/raw/audio/{video_id}.wav
         │
         │ prepare_review_audio.py
         ▼
data/review/{sample_id}/sentences/{idx}.wav   (0.2s padding each side)
         │
         │ Label Studio (unified_review.xml)
         │ label_studio_sync.py push/pull
         │
         │ apply_review.py
         ▼
data/final/{sample_id}/sentences/{idx}.wav    (reviewed timing, no padding)
         │                manifest.tsv
         │
         │ export_reviewed.py
         ▼
data/dataset/{sample_id}/sentences/{idx}.wav  (DVC-tracked)
                        manifest.tsv
                        metadata.json
```

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🛠️ [Command Reference](03_command_reference.md) - All commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer docs

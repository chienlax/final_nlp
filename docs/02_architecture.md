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
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐
│   YouTube   │───►│   Gemini     │───►│ Label Studio │───►│  Training   │
│  Ingestion  │    │  Processing  │    │   Review     │    │   Export    │
└─────────────┘    └──────────────┘    └──────────────┘    └─────────────┘
     RAW            TRANSLATED          VERIFIED             FINAL
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| YouTube-only source | Focus on videos with existing transcripts |
| Transcript required | Only process videos with manual/auto subtitles |
| Unified Gemini processing | Single-pass transcription + translation |
| 3-stage human review | Transcript → Segment → Translation verification |
| Segment-level output | 10-30s chunks optimized for training |

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
    'TRANSCRIPT_REVIEW',    -- In Label Studio (Round 1)
    'TRANSCRIPT_VERIFIED',  -- Human approved transcript
    'ALIGNED',              -- WhisperX alignment complete
    'SEGMENTED',            -- Audio chunked (10-30s)
    'SEGMENT_REVIEW',       -- In Label Studio (Round 2)
    'SEGMENT_VERIFIED',     -- Human approved segments
    'TRANSLATED',           -- Gemini translation complete
    'TRANSLATION_REVIEW',   -- In Label Studio (Round 3)
    'DENOISED',             -- DeepFilterNet complete
    'FINAL',                -- Ready for training
    'REJECTED'              -- Failed QC
);
```

### State Transition Diagram

```
RAW
 │
 ├──► TRANSCRIPT_REVIEW ──► TRANSCRIPT_VERIFIED
 │                                   │
 │         (Optional: WhisperX)      ▼
 │                               ALIGNED
 │                                   │
 │                                   ▼
 │                               SEGMENTED
 │                                   │
 │                                   ▼
 │                          SEGMENT_REVIEW ──► SEGMENT_VERIFIED
 │                                                    │
 │              (gemini_process.py)                   │
 │                      │                             │
 │                      ▼                             ▼
 │               TRANSLATED ◄─────────────────────────┘
 │                      │
 │                      ▼
 │             TRANSLATION_REVIEW
 │                      │
 │                      ▼
 │                  DENOISED
 │                      │
 │                      ▼
 │                   FINAL
 │
 └──► REJECTED (at any stage)
```

### Stage Details

| Stage | Script | Human Review? | Description |
|-------|--------|---------------|-------------|
| RAW | `ingest_youtube.py` | No | Downloaded from YouTube with transcript |
| TRANSCRIPT_REVIEW | `label_studio_sync.py` | **Yes** | Correct transcript errors |
| TRANSCRIPT_VERIFIED | - | No | Transcript approved |
| ALIGNED | `whisperx_align.py` | No | Word-level timestamps added |
| SEGMENTED | `segment_audio.py` | No | Split into 10-30s chunks |
| SEGMENT_REVIEW | `label_studio_sync.py` | **Yes** | Verify segment boundaries |
| SEGMENT_VERIFIED | - | No | Segments approved |
| TRANSLATED | `gemini_process.py` | No | Transcription + translation via Gemini |
| TRANSLATION_REVIEW | `label_studio_sync.py` | **Yes** | Review translation accuracy |
| DENOISED | `denoise_audio.py` | No | Background noise removed |
| FINAL | `export_reviewed.py` | No | Ready for training |

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
│   segments   │    │ transcript_  │    │ translation_ │
│ (10-30s      │    │ revisions    │    │ revisions    │
│  chunks)     │    │              │    │              │
└──────┬───────┘    └──────────────┘    └──────────────┘
       │ 1:N
       ▼
┌──────────────────┐
│ segment_         │
│ translations     │
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

#### segments

```sql
CREATE TABLE segments (
    segment_id UUID PRIMARY KEY,
    sample_id UUID REFERENCES samples(sample_id),
    segment_index INTEGER NOT NULL,
    audio_file_path TEXT NOT NULL,
    start_time NUMERIC(10, 3),
    end_time NUMERIC(10, 3),
    transcript_text TEXT NOT NULL,
    word_timestamps JSONB,
    is_verified BOOLEAN DEFAULT FALSE,
    UNIQUE (sample_id, segment_index)
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
│   ├── raw/                    # DVC-tracked
│   │   ├── audio/              # {video_id}.wav (16kHz mono)
│   │   ├── text/               # {video_id}_transcript.json
│   │   └── metadata.jsonl
│   ├── segments/               # Segmented chunks
│   │   └── {sample_id}/
│   │       ├── 0000.wav
│   │       └── ...
│   └── db_sync/                # Database backups (DVC-tracked)
├── src/
│   ├── ingest_youtube.py
│   ├── label_studio_sync.py
│   ├── preprocessing/
│   │   ├── gemini_process.py        # Unified transcription + translation
│   │   ├── gemini_repair_translation.py
│   │   ├── whisperx_align.py
│   │   ├── segment_audio.py
│   │   └── denoise_audio.py
│   └── utils/
│       ├── data_utils.py
│       └── text_utils.py
├── init_scripts/
│   └── 01_schema.sql
├── label_studio_templates/
│   ├── transcript_correction.xml
│   ├── segment_review.xml
│   └── translation_review.xml
├── docker-compose.yml
└── requirements.txt
```

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🛠️ [Command Reference](03_command_reference.md) - All commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer docs

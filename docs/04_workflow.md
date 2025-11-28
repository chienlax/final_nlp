# 04. Workflow Documentation

## Overview

This document describes the complete data ingestion and processing workflow for the Vietnamese-English Code-Switching Speech Translation project. The system supports two primary data pipelines based on the input modality.

**Related Documentation:**
- [07. Label Studio Integration](07_label_studio.md) - Detailed annotation workflow
- [06. Database Design](06_database_design.md) - Schema and versioning

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES                                       │
├─────────────────────────────────┬───────────────────────────────────────────┤
│       YOUTUBE (Audio-First)     │         SUBSTACK (Text-First)             │
│  - Video/Channel URLs           │  - Blog article URLs                      │
│  - 16kHz mono WAV extraction    │  - Markdown/text extraction               │
│  - Transcript w/ timestamps     │  - Teencode normalization                 │
└─────────────────┬───────────────┴──────────────────────┬────────────────────┘
                  │                                      │
                  ▼                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RAW DATA STORAGE                                     │
│                        (DVC-versioned)                                       │
│  data/raw/audio/     - WAV files (16kHz mono)                               │
│  data/raw/text/      - Transcript JSON files (with timestamps)               │
│  data/raw/metadata.jsonl - Batch metadata                                   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
            ┌─────────────────────┴─────────────────────┐
            │                                           │
            ▼                                           ▼
┌───────────────────────────────┐     ┌───────────────────────────────────────┐
│      POSTGRESQL DATABASE       │     │          DVC SYNC DAEMON              │
│  - sources: Origin tracking    │     │  - Auto-sync every 5 minutes          │
│  - samples: Central registry   │     │  - Pulls new data from Google Drive   │
│  - transcript_revisions        │     │  - Pushes local changes upstream      │
│  - translation_revisions       │     │  - Records commit hashes              │
│  - annotations: Label Studio   │     │                                       │
│  - processing_logs: Audit      │     │  Script: src/sync_daemon.py           │
└───────────────────┬───────────┘     └───────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROCESSING PIPELINES                                    │
│  (Future: MFA alignment, VAD segmentation, DeepFilterNet, TTS)              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LABEL STUDIO ANNOTATION                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐        │
│  │ Transcript      │  │ Translation     │  │ Audio Segmentation   │        │
│  │ Correction      │  │ Review          │  │ (Future)             │        │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘        │
│           │                    │                      │                     │
│           └────────────────────┴──────────────────────┘                     │
│                                │                                            │
│                       ┌────────▼────────┐                                   │
│                       │ Webhook Server   │                                  │
│                       │ (Conflict Check) │                                  │
│                       └────────┬────────┘                                   │
│                                │                                            │
│                       ┌────────▼────────┐                                   │
│                       │ Export Pipeline  │                                  │
│                       └─────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Audio-First Pipeline (YouTube)

This pipeline is designed for YouTube videos that contain Vietnamese-English code-switching speech.

### 2.1 Pipeline States

```
RAW → ALIGNED → SEGMENTED → ENHANCED → TRANSLATED → REVIEWED
          ↓
     (alternative if no transcript)
          ↓
     VAD_SEGMENTED → ALIGNED → ...
```

### 2.2 Workflow Steps

| Step | Task | Processing State | Script | Section |
|------|------|------------------|--------|---------|
| 1 | Download audio (16kHz WAV) | - | `ingest_youtube.py` | [§5.1](05_scripts_details.md#51-ingest_youtubepy) |
| 2 | Download transcript w/ timestamps | RAW | `ingest_youtube.py` | [§5.1](05_scripts_details.md#51-ingest_youtubepy) |
| 3 | Calculate CS ratio | RAW | `ingest_youtube.py` | [§5.1](05_scripts_details.md#51-ingest_youtubepy) |
| 4 | Insert to database | RAW | `ingest_youtube.py` | [§5.1](05_scripts_details.md#51-ingest_youtubepy) |
| 5 | MFA Forced Alignment | ALIGNED | *Future* | - |
| 6 | Audio Segmentation | SEGMENTED | *Future* | - |
| 7 | Audio Enhancement (DeepFilterNet) | ENHANCED | *Future* | - |
| 8 | LLM Translation | TRANSLATED | *Future* | - |
| 9 | Human Review (Label Studio) | REVIEWED | `label_studio_sync.py` | [§5.3](05_scripts_details.md#53-label_studio_syncpy) |

### 2.3 Detailed Sub-Tasks

#### Step 1: Audio Download
```
Input:  YouTube URL (video or channel)
Output: data/raw/audio/{video_id}.wav

Sub-tasks:
├── Validate URL format
├── Extract video metadata (yt-dlp)
├── Filter by duration (2-60 min)
├── Download best audio stream
├── Convert to 16kHz mono WAV (ffmpeg)
└── Log to downloaded_videos_log

Related Script: src/utils/video_downloading_utils.py
  └── download_channels()
  └── _duration_filter()
  └── progress_hook()
```

#### Step 2: Transcript Download
```
Input:  Video ID from metadata.jsonl
Output: data/raw/text/{video_id}_transcript.json

Sub-tasks:
├── List available transcripts (manual vs auto-generated)
├── Prioritize: Manual EN > Auto EN > Manual VI > Auto VI
├── Fetch transcript segments with timestamps
├── Convert to JSON format with start/end times
└── Update metadata.jsonl with transcript info

Related Script: src/utils/transcript_downloading_utils.py
  └── get_transcript_info()
  └── download_transcripts_from_metadata()

Output Format:
{
  "video_id": "xxx",
  "language": "en",
  "subtitle_type": "Manual",
  "segments": [
    {"text": "...", "start": 0.47, "duration": 0.95, "end": 1.42},
    ...
  ],
  "full_text": "..."
}
```

#### Step 3: CS Ratio Calculation
```
Input:  Transcript text
Output: Float (0.0 - 1.0)

Sub-tasks:
├── Tokenize text into words
├── Detect Vietnamese particles
├── Detect English stop words
├── Calculate intersection ratio

Related Script: src/utils/data_utils.py
  └── calculate_cs_ratio()
```

#### Step 4: Database Ingestion
```
Input:  Metadata entries with file paths
Output: PostgreSQL records (sources, samples, transcript_revisions)

Sub-tasks:
├── Get or create source record
├── Insert sample record (RAW state)
├── Insert transcript revision (version 1)
├── Log processing step

Related Script: src/utils/data_utils.py
  └── get_or_create_source()
  └── insert_sample()
  └── insert_transcript_revision()
```

---

## 3. Text-First Pipeline (Substack)

This pipeline processes Substack blog articles that contain code-switching text.

### 3.1 Pipeline States

```
RAW → NORMALIZED → CS_CHUNKED → TTS_GENERATED → TRANSLATED → REVIEWED
```

### 3.2 Workflow Steps

| Step | Task | Processing State | Script | Section |
|------|------|------------------|--------|---------|
| 1 | Download article (HTML→Text) | - | `ingest_substack.py` | [§5.2](05_scripts_details.md#52-ingest_substackpy) |
| 2 | Normalize text (teencode) | RAW | `ingest_substack.py` | [§5.2](05_scripts_details.md#52-ingest_substackpy) |
| 3 | Extract CS chunks | NORMALIZED | `ingest_substack.py` | [§5.2](05_scripts_details.md#52-ingest_substackpy) |
| 4 | Insert to database | RAW | `ingest_substack.py` | [§5.2](05_scripts_details.md#52-ingest_substackpy) |
| 5 | TTS Generation (XTTS v2) | TTS_GENERATED | *Future* | - |
| 6 | LLM Translation | TRANSLATED | *Future* | - |
| 7 | Human Review (Label Studio) | REVIEWED | `label_studio_sync.py` | [§5.3](05_scripts_details.md#53-label_studio_syncpy) |

### 3.3 Detailed Sub-Tasks

#### Step 1: Article Download
```
Input:  Substack article URL
Output: data/raw/text/substack/{blog_slug}/{article_slug}.txt

Sub-tasks:
├── Extract blog slug from URL
├── Fetch HTML content (requests)
├── Parse article body (BeautifulSoup)
├── Extract title and content
├── Convert to clean text format
└── Save to organized directory

Related Script: src/utils/substack_utils.py
  └── run_downloader()
  └── _download_single_article()
  └── extract_blog_slug()
```

#### Step 2: Text Normalization
```
Input:  Raw article text
Output: Normalized text

Sub-tasks:
├── Load teencode dictionary
├── Apply teencode replacements
├── Remove URLs and emojis
├── Normalize whitespace
└── (Optional) Lowercase conversion

Related Script: src/utils/text_utils.py
  └── load_teencode_dict()
  └── normalize_text()
```

#### Step 3: CS Chunk Extraction
```
Input:  Normalized text
Output: List of CS chunks with context

Sub-tasks:
├── Split into sentences
├── Detect CS sentences (VN + EN intersection)
├── Calculate per-sentence CS ratio
├── Extract context (before/after sentences)
└── Build chunk dictionaries

Related Script: src/utils/text_utils.py
  └── contains_code_switching()
  └── extract_cs_chunks()
  └── _estimate_cs_ratio()
```

---

## 4. Data Versioning Workflow (DVC)

### 4.1 DVC Sync Daemon (Automated)

The sync daemon automatically synchronizes data every 5 minutes with Google Drive.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SYNC DAEMON WORKFLOW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│    ┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────┐    │
│    │  WAIT   │────▶│  DVC PULL   │────▶│  DVC PUSH   │────▶│  LOG    │    │
│    │ 5 min   │     │ (Fetch new) │     │ (Upload)    │     │ Result  │    │
│    └────▲────┘     └─────────────┘     └─────────────┘     └────┬────┘    │
│         │                                                       │          │
│         └───────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

Automatic sync via Docker:
- Runs as sync_service container
- Pulls new data from Google Drive remote
- Pushes local changes upstream
- Records DVC commit hashes in database

Script: src/sync_daemon.py
```

### 4.2 Manual DVC Operations

```bash
# After downloading new files
dvc add data/raw

# Commit the tracking file
git add data/raw.dvc .gitignore
git commit -m "Add new batch of data"

# Push to remote storage
dvc push
```

### 4.3 Pulling Existing Data
```bash
# After cloning the repository
dvc pull
```

### 4.4 Checking Status
```bash
# See what's changed
dvc status

# See file details
dvc diff
```

---

## 5. Label Studio Annotation Workflow

### 5.1 Complete Annotation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      LABEL STUDIO WORKFLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. PUSH SAMPLES        2. ANNOTATE           3. WEBHOOK CALLBACK           │
│  ┌─────────────┐        ┌─────────────┐       ┌─────────────────┐          │
│  │ Select RAW  │        │ Label Studio│       │ FastAPI Server  │          │
│  │ samples     │───────▶│ UI          │──────▶│ (port 8000)     │          │
│  │             │        │             │       │                 │          │
│  │ Lock sample │        │ Audio +     │       │ Check conflict  │          │
│  │ in database │        │ Transcript  │       │ Record result   │          │
│  └─────────────┘        └─────────────┘       └────────┬────────┘          │
│                                                        │                    │
│  6. EXPORT              5. UPDATE DB           4. CONFLICT?                │
│  ┌─────────────┐        ┌─────────────┐       ┌────────▼────────┐          │
│  │ Export      │        │ Create new  │       │ Compare version │          │
│  │ reviewed    │◀───────│ revision    │◀──YES─│ sync_version    │          │
│  │ data        │        │             │       │                 │          │
│  │             │        │ Unlock      │  NO   │ Flag for        │          │
│  │ DVC push    │        │ sample      │◀──────│ re-review       │          │
│  └─────────────┘        └─────────────┘       └─────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Task Types

| Task Type | Template | Input | Output |
|-----------|----------|-------|--------|
| `transcript_correction` | Audio waveform + editable text | RAW samples | Corrected transcripts |
| `translation_review` | Side-by-side view | TRANSLATED samples | Verified translations |
| `audio_segmentation` | Waveform regions | Audio files | Segment boundaries |

### 5.3 Conflict Resolution

When a sample is updated during annotation:

1. **Detection**: Webhook compares `sync_version` at annotation start vs current
2. **Conflict Creation**: New sample created with `_conflict_{timestamp}` suffix
3. **Flagging**: Original marked for re-review
4. **Resolution Options**:
   - Keep annotated version
   - Keep updated version
   - Merge changes manually

### 5.4 Gold Standard Samples

Quality control using pre-verified samples:

```bash
# Set a sample as gold standard
# (via database function)
SELECT set_gold_standard('sample_uuid', expected_score);

# View annotator accuracy
SELECT * FROM v_annotator_accuracy;
```

---

## 6. Export Pipeline

### 6.1 Export Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXPORT REVIEWED DATA                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Input: REVIEWED samples from database                                      │
│                                                                             │
│  Output Structure:                                                          │
│  data/reviewed/                                                             │
│  └── {task_type}/                                                           │
│      └── {sample_id}/                                                       │
│          ├── audio.wav          # Original audio file                       │
│          ├── transcript.json    # Final corrected transcript                │
│          ├── translation.json   # Verified translation                      │
│          └── metadata.json      # Sample metadata + revision history        │
│                                                                             │
│  Script: src/export_reviewed.py                                             │
│  DVC Pipeline: dvc repro export_reviewed                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 DVC Pipeline Stages

```yaml
# dvc.yaml stages
stages:
  export_reviewed:
    cmd: python src/export_reviewed.py --output-dir data/reviewed
    deps:
      - src/export_reviewed.py
    outs:
      - data/reviewed

  generate_manifest:
    cmd: python -c "..."  # Generate manifest.json
    deps:
      - data/reviewed
    outs:
      - data/reviewed/manifest.json
```

---

## 7. Quick Reference: Script → Task Mapping

| Script | Primary Task | Key Functions |
|--------|--------------|---------------|
| `ingest_youtube.py` | YouTube ingestion orchestrator | `run_pipeline()`, `ingest_to_database()` |
| `ingest_substack.py` | Substack ingestion orchestrator | `ingest_substack()`, `process_article()` |
| `label_studio_sync.py` | Label Studio integration | `push()`, `pull()`, `status()` |
| `sync_daemon.py` | DVC auto-sync service | `run_dvc_pull()`, `run_dvc_push()`, `run_sync_loop()` |
| `export_reviewed.py` | Export reviewed data | `export_sample()`, `export_all_reviewed()` |
| `webhook_server.py` | Annotation webhooks | `handle_annotation_created()`, `check_conflict()` |
| `video_downloading_utils.py` | Audio download | `download_channels()`, `save_jsonl()` |
| `transcript_downloading_utils.py` | Transcript download | `get_transcript_info()`, `download_transcripts_from_metadata()` |
| `substack_utils.py` | Article download | `run_downloader()`, `list_downloaded_articles()` |
| `text_utils.py` | Text processing | `normalize_text()`, `extract_cs_chunks()` |
| `data_utils.py` | Database operations | `insert_sample()`, `insert_transcript_revision()`, `calculate_cs_ratio()` |

---

## 8. Environment Variables

```bash
# Database connection
DATABASE_URL=postgresql://admin:secret_password@localhost:5432/data_factory

# Label Studio integration
LABEL_STUDIO_URL=http://localhost:8080
LABEL_STUDIO_API_KEY=your_api_key
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_TRANSLATION=2
LS_PROJECT_SEGMENTATION=3

# Audio serving
AUDIO_SERVER_URL=http://localhost:8081

# DVC sync configuration
DVC_REMOTE=gdrive
SYNC_INTERVAL_MINUTES=5
```

---

## 9. Command Reference

### YouTube Ingestion
```bash
# Full pipeline with database
python src/ingest_youtube.py "https://youtube.com/watch?v=VIDEO_ID"

# Dry run (no database writes)
python src/ingest_youtube.py --dry-run "https://youtube.com/watch?v=VIDEO_ID"

# Skip download, use existing metadata
python src/ingest_youtube.py --skip-download --dry-run
```

### Substack Ingestion
```bash
# From URL file
python src/ingest_substack.py --urls-file data/substack_urls.txt

# Dry run with existing downloads
python src/ingest_substack.py --skip-download --dry-run

# Limit number of articles
python src/ingest_substack.py --limit 10
```

### Label Studio Sync
```bash
# Push samples for annotation
python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed annotations
python src/label_studio_sync.py pull --task-type transcript_correction

# Check connection
python src/label_studio_sync.py status
```

### DVC Sync Daemon
```bash
# Run continuous sync (every 5 minutes by default)
python src/sync_daemon.py

# Single sync operation
python src/sync_daemon.py --once

# Custom interval
python src/sync_daemon.py --interval 10

# Push-only mode
python src/sync_daemon.py --once --push
```

### Export Reviewed Data
```bash
# Export all reviewed samples
python src/export_reviewed.py --output-dir data/reviewed

# Export specific task type
python src/export_reviewed.py --task-type transcript_correction

# Dry run
python src/export_reviewed.py --dry-run
```

### Webhook Server
```bash
# Start webhook server
uvicorn src.webhook_server:app --host 0.0.0.0 --port 8000

# Or via docker-compose
docker-compose up webhook_server
```

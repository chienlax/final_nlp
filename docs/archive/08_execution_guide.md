# Execution Guide

A comprehensive reference for all commands available in the Vietnamese-English Code-Switching Speech Translation pipeline.

> **Note**: All commands use Docker for portability. Scripts also work natively with Python 3.10+ if dependencies are installed locally.

---

## Table of Contents

1. [Quick Reference](#1-quick-reference)
2. [Docker Service Management](#2-docker-service-management)
3. [YouTube Ingestion](#3-youtube-ingestion)
4. [Label Studio Sync](#4-label-studio-sync)
5. [Database Operations](#5-database-operations)
6. [Preprocessing Pipeline](#6-preprocessing-pipeline)
7. [DVC Data Versioning](#7-dvc-data-versioning)
8. [Export & Training Data](#8-export--training-data)
9. [Common Workflows](#9-common-workflows)
10. [Environment Variables & Credentials](#10-environment-variables--credentials)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Quick Reference

### Most Used Commands

```powershell
# Start all services
docker compose up -d

# Ingest YouTube video
docker compose run --rm -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Push to Label Studio for review
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory -e AUDIO_PUBLIC_URL=http://localhost:8081 -e LS_PROJECT_TRANSCRIPT=1 ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed annotations
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/label_studio_sync.py pull --task-type transcript_correction

# Check pipeline status
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT processing_state, COUNT(*) FROM samples GROUP BY processing_state;"

# Backup and sync to DVC
docker compose run --rm -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/db_backup.py
docker compose run --rm ingestion dvc push
```

---

## 2. Docker Service Management

### Start Services

```powershell
# Start all services
docker compose up -d

# Start specific services only
docker compose up -d postgres audio_server labelstudio

# Start with build (after code changes)
docker compose up -d --build

# Start in foreground (see logs)
docker compose up
```

### Stop Services

```powershell
# Stop all services (preserves data)
docker compose down

# Stop and remove volumes (⚠️ DELETES ALL DATA)
docker compose down -v

# Stop specific service
docker compose stop labelstudio
```

### Check Status

```powershell
# List running containers
docker compose ps

# View logs (all services)
docker compose logs

# View logs (specific service, follow mode)
docker compose logs -f labelstudio
docker compose logs -f postgres
docker compose logs -f audio_server

# Check container health
docker inspect factory_ledger --format='{{.State.Health.Status}}'
```

### Execute Commands in Containers

```powershell
# Interactive shell
docker exec -it factory_ingestion bash

# Run one-off command
docker compose run --rm ingestion python src/script.py

# Database shell
docker exec -it factory_ledger psql -U admin -d data_factory
```

### Service Reference

| Service | Container | Internal Host | External Port | Purpose |
|---------|-----------|---------------|---------------|---------|
| postgres | `factory_ledger` | `postgres` | 5432 | Metadata database |
| labelstudio | `labelstudio` | `labelstudio` | 8085 | Annotation UI |
| audio_server | `audio_server` | `audio_server` | 8081 | Serve audio files |
| ingestion | `factory_ingestion` | - | - | Run pipeline scripts |

---

## 3. YouTube Ingestion

### Script: `src/ingest_youtube.py`

Downloads YouTube videos, extracts audio, and imports metadata to database.

### Basic Usage

```powershell
# Single video
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://youtu.be/VIDEO_1" "https://youtu.be/VIDEO_2"

# Entire channel
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://www.youtube.com/@ChannelName"
```

### Options

```powershell
# Skip download, use existing metadata.jsonl
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py --skip-download

# Dry run (preview without database writes)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py --skip-download --dry-run

# Allow videos without transcripts (not recommended for this project)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "URL" --no-require-transcript
```

### Arguments Reference

| Argument | Description |
|----------|-------------|
| `urls` (positional) | YouTube video/channel URLs |
| `--skip-download` | Use existing `metadata.jsonl` instead of downloading |
| `--no-require-transcript` | Allow videos without subtitles |
| `--dry-run` | Simulate without database writes |

---

## 4. Label Studio Sync

### Script: `src/label_studio_sync.py`

Manages bidirectional sync between database and Label Studio.

### Push Samples for Review

```powershell
# Push for transcript correction
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSCRIPT=1 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Push for translation review
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSLATION=2 `
  ingestion python src/label_studio_sync.py push --task-type translation_review

# Push for audio segmentation
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_SEGMENTATION=3 `
  ingestion python src/label_studio_sync.py push --task-type audio_segmentation

# Push with limit
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSCRIPT=1 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction --limit 10
```

### Pull Completed Annotations

```powershell
# Pull transcript corrections
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type transcript_correction

# Pull translation reviews
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type translation_review

# Dry run (preview without changes)
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type transcript_correction --dry-run
```

### Check Status

```powershell
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py status
```

### Create Projects

```powershell
# Create transcript correction project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type transcript_correction

# Create translation review project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type translation_review

# Create audio segmentation project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type audio_segmentation
```

### Arguments Reference

| Argument | Description |
|----------|-------------|
| `push` | Push samples to Label Studio |
| `pull` | Pull completed annotations |
| `status` | Check connection and pending tasks |
| `--task-type` | `transcript_correction`, `translation_review`, `audio_segmentation` |
| `--limit N` | Maximum items to process |
| `--dry-run` | Preview without making changes |

---

## 5. Database Operations

### Backup Database

```powershell
# Incremental backup (since last sync)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_backup.py

# Full backup (all data)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_backup.py --full

# Dry run
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_backup.py --dry-run

# Verbose output
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_backup.py -v
```

**Output**: Exports to `data/db_sync/` as JSONL files.

### Restore Database

```powershell
# Import with last-write-wins conflict resolution
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_restore.py

# Force overwrite (ignore timestamps)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_restore.py --force

# Preview changes
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_restore.py --dry-run
```

### Direct Database Queries

```powershell
# Interactive SQL shell
docker exec -it factory_ledger psql -U admin -d data_factory

# Run single query
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT * FROM samples;"

# Pipeline status by state
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT processing_state, COUNT(*) FROM samples GROUP BY processing_state ORDER BY COUNT(*) DESC;"

# List all samples
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state, created_at FROM samples ORDER BY created_at DESC;"

# Check annotations
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT s.external_id, a.task_type, a.status FROM samples s JOIN annotations a ON s.sample_id = a.sample_id;"

# Recent processing logs
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT * FROM processing_logs ORDER BY created_at DESC LIMIT 10;"

# List tables
docker exec factory_ledger psql -U admin -d data_factory -c "\dt"
```

### Backup Arguments Reference

| Argument | Description |
|----------|-------------|
| `--full` | Export all data (ignore last sync checkpoint) |
| `--dry-run` | Preview without writing files |
| `--no-compress` | Output uncompressed JSONL |
| `-v, --verbose` | Detailed output |

---

## 6. Preprocessing Pipeline

### WhisperX Alignment

Force-aligns transcript with audio at word level.

**Requirements**: GPU with 4-8GB VRAM

```powershell
# Align specific sample
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/whisperx_align.py --sample-id <UUID>

# Batch processing
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/whisperx_align.py --batch --limit 10

# Dry run
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/whisperx_align.py --batch --dry-run
```

### Gemini Unified Processing (Transcription + Translation)

Transcribes audio using Gemini's multimodal capabilities with structured output,
producing sentence-level timestamps and Vietnamese translations in a single pass.

**Features**:
- Hybrid single-pass: Full audio context understanding + structured JSON output
- Few-shot prompting with Vietnamese-English code-switching examples
- Automatic audio chunking for files >27 minutes with overlap deduplication
- Translation issue detection and flagging for repair script

**Requirements**: `GEMINI_API_KEY_1` in `.env` file

**Pipeline Stage**: RAW → TRANSLATED (with `needs_translation_review` flag if issues)

```powershell
# Process specific sample
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --sample-id <UUID>

# Batch processing (samples in RAW state)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --batch --limit 5

# Re-process samples that already have transcripts
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --batch --replace-existing --limit 5

# Use Pro model for better quality (slower, higher cost)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --batch --model gemini-2.5-pro

# Check API key status
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --check-keys

# Dry run - preview what would be processed
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --batch --dry-run
```

**Output**: Creates both `transcript_revision` (with `sentence_timestamps` JSONB) and `translation_revision` (with `sentence_translations` JSONB) in a single operation.

### Gemini Translation Repair

Repairs sentences that had translation issues during initial `gemini_process.py` run.
Queries samples with `has_translation_issues=TRUE` and re-translates problematic sentences.

**Requirements**: `GEMINI_API_KEY_1` in `.env` file

**Pipeline Stage**: Repairs TRANSLATED samples (clears `needs_translation_review` flag)

```powershell
# Repair batch of samples with translation issues
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_repair_translation.py --batch --limit 10

# Repair specific sample
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_repair_translation.py --sample-id <UUID>

# Dry run - see what would be repaired
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_repair_translation.py --dry-run

# Check API keys
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --check-keys
```

### Audio Segmentation

Splits audio into 10-30 second segments based on alignment.

```powershell
# Segment specific sample
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/segment_audio.py --sample-id <UUID>

# Batch processing
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/segment_audio.py --batch --limit 10

# Custom directories
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/segment_audio.py --batch --data-root /app/data --segments-root /app/data/segments
```

### Audio Denoising

Removes background noise using DeepFilterNet.

**Requirements**: GPU with 2-4GB VRAM

```powershell
# Denoise specific sample
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/denoise_audio.py --sample-id <UUID>

# Batch processing
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/denoise_audio.py --batch --limit 10
```

### Preprocessing Arguments Reference

| Argument | Description |
|----------|-------------|
| `--sample-id <UUID>` | Process specific sample |
| `--batch` | Process all eligible samples |
| `--limit N` | Maximum samples to process |
| `--dry-run` | Preview without changes |
| `--data-root PATH` | Custom data directory |
| `--model` | Gemini model (`gemini-2.5-flash`, `gemini-2.5-pro`) |
| `--replace-existing` | Re-process samples with existing data |
| `--check-keys` | Check API key availability |

---

## 7. DVC Data Versioning

### Basic Commands

```powershell
# Add data to DVC tracking
docker compose run --rm ingestion dvc add data/raw
docker compose run --rm ingestion dvc add data/db_sync

# Push to remote (Google Drive)
docker compose run --rm ingestion dvc push

# Push specific file
docker compose run --rm ingestion dvc push data/raw.dvc
docker compose run --rm ingestion dvc push data/db_sync.dvc

# Pull from remote
docker compose run --rm ingestion dvc pull

# Force pull (overwrite local)
docker compose run --rm ingestion dvc pull --force

# Check status
docker compose run --rm ingestion dvc status
```

### Setup Google Drive Auth

```powershell
# Run OAuth flow
docker compose run --rm ingestion python src/setup_gdrive_auth.py

# Check if authenticated
docker compose run --rm ingestion python src/setup_gdrive_auth.py --check

# Print setup instructions
docker compose run --rm ingestion python src/setup_gdrive_auth.py --instructions
```

### Sync Daemon

Automatic continuous sync between database and DVC.

```powershell
# Continuous sync (default 5 minutes)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/sync_daemon.py

# Single sync and exit
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/sync_daemon.py --once

# Custom interval (minutes)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/sync_daemon.py --interval 10

# Push only (no pull)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/sync_daemon.py --push

# Check DVC status only
docker compose run --rm ingestion python src/sync_daemon.py --status

# Force restore local DB from remote
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/sync_daemon.py --force-restore
```

---

## 8. Export & Training Data

### Export Reviewed Samples

```powershell
# Export all reviewed samples
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py

# Filter by task type
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py --task-type transcript_verification

# Limit export count
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py --limit 100

# Custom output directory
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py --output-dir data/training

# Include already exported samples
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py --include-exported
```

**Output Structure**:
```
data/reviewed/{task_type}/{sample_id}/
├── audio.wav
├── transcript.json
├── translation.json
└── metadata.json
```

---

## 9. Common Workflows

### Initial Setup (First Time)

```powershell
# 1. Start services
docker compose up -d

# 2. Wait for Label Studio to initialize
Start-Sleep -Seconds 45

# 3. Open http://localhost:8085 and create account

# 4. Get API token from Label Studio UI
#    Settings → Account & Settings → Access Token

# 5. Create Label Studio projects
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type transcript_correction

# 6. Setup Google Drive auth for DVC (optional)
docker compose run --rm ingestion python src/setup_gdrive_auth.py
```

### Daily Ingestion Workflow

```powershell
# 1. Ingest new videos
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 2. Push to Label Studio for review
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSCRIPT=1 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction

# 3. (Human reviews in Label Studio UI)

# 4. Pull completed annotations
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type transcript_correction
```

### Full Preprocessing Pipeline

```powershell
# 1. Ingest YouTube video (downloads audio + YouTube transcript)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 2. Run unified Gemini processing (transcription + translation in one pass)
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_process.py --batch

# 3. Check for and repair any translation issues
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/gemini_repair_translation.py --batch

# 4. Push to Label Studio for human review (translation review)
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSLATION=2 `
  ingestion python src/label_studio_sync.py push --task-type translation_review

# 5. (Human reviews in Label Studio UI)

# 6. Pull completed annotations
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type translation_review

# 7. (Optional) Run WhisperX alignment for word-level timestamps
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/whisperx_align.py --batch

# 8. (Optional) Segment audio into 10-30s chunks
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/segment_audio.py --batch

# 9. (Optional) Denoise audio
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/preprocessing/denoise_audio.py --batch

# 10. Export for training
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/export_reviewed.py
```

### Data Sync Workflow

```powershell
# Backup local → Push to remote
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_backup.py

docker compose run --rm ingestion dvc add data/raw data/db_sync
docker compose run --rm ingestion dvc push

# Pull from remote → Restore local
docker compose run --rm ingestion dvc pull
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/db_restore.py
```

### Complete Reset

```powershell
# ⚠️ WARNING: This deletes all data

# 1. Stop services and remove volumes
docker compose down -v

# 2. Remove local data (optional)
Remove-Item -Recurse -Force data/raw/audio/*
Remove-Item -Recurse -Force data/raw/text/*
Remove-Item -Recurse -Force data/db_sync/*

# 3. Start fresh
docker compose up -d
```

---

## 10. Environment Variables & Credentials

### How Environment Variables Work

There are **two ways** to provide environment variables:

#### Option A: Use the `.env` File (Recommended)

The project includes a `.env` file at the project root. Variables defined here are **automatically loaded** by Docker Compose for services that reference them with `${VARIABLE_NAME}`.

```powershell
# Edit the .env file
notepad .env

# Variables in .env are automatically used by:
# - sync_service (continuous sync)
# - ingestion (when using docker compose run)
```

#### Option B: Pass Variables Inline (Override)

You can override `.env` values by passing `-e` flags. This is useful for:
- One-off commands with different values
- Testing without modifying `.env`

```powershell
# This overrides whatever is in .env
docker compose run --rm -e LABEL_STUDIO_API_KEY=different_token ingestion python src/label_studio_sync.py status
```

> **Note**: If a variable is set in `.env`, you don't need to pass it with `-e` for `docker compose run` commands.

---

### Credentials Reference

#### 1. Database Credentials

| Variable | Where It's Set | Default Value | How to Get It |
|----------|---------------|---------------|---------------|
| `POSTGRES_USER` | `docker-compose.yml` | `admin` | Pre-configured |
| `POSTGRES_PASSWORD` | `docker-compose.yml` | `secret_password` | Pre-configured |
| `POSTGRES_DB` | `docker-compose.yml` | `data_factory` | Pre-configured |
| `DATABASE_URL` | `.env` | `postgresql://admin:secret_password@postgres:5432/data_factory` | Constructed from above |

**Connection String Format**:
```
postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{host}:{port}/{POSTGRES_DB}
```

**Host depends on context**:
- Inside Docker containers: `postgres` (service name)
- From host machine: `localhost`

```powershell
# Inside Docker (used by docker compose run)
DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory

# From host machine (for local Python scripts)
DATABASE_URL=postgresql://admin:secret_password@localhost:5432/data_factory
```

---

#### 2. Label Studio API Key

| Variable | Where It's Set | How to Get It |
|----------|---------------|---------------|
| `LABEL_STUDIO_API_KEY` | `.env` | From Label Studio UI |
| `LABEL_STUDIO_URL` | `.env` | `http://localhost:8085` (default) |

**How to Get Your API Token**:

1. Open Label Studio at http://localhost:8085
2. Click your **user icon** (top-right corner)
3. Go to **Account & Settings**
4. Find **Access Token** section
5. Copy the **40-character hex string**

```
✅ Correct format: 8a467af13f15511a8f8cc9d893dff4fe847477e0
❌ Wrong format:   eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... (this is JWT, not API key)
```

**Update `.env`**:
```dotenv
LABEL_STUDIO_API_KEY=8a467af13f55571a4f8cc9dd93dff4fe841477e0
```

> **Important**: Each user who creates a Label Studio account gets their own token. If you're sharing the project, each person needs to update `.env` with their own token.

---

#### 3. Label Studio Project IDs

| Variable | Where It's Set | How to Get It |
|----------|---------------|---------------|
| `LS_PROJECT_TRANSCRIPT` | `.env` | From Label Studio URL after creating project |
| `LS_PROJECT_SEGMENT` | `.env` | From Label Studio URL after creating project |
| `LS_PROJECT_TRANSLATION` | `.env` | From Label Studio URL after creating project |

**How to Find Project IDs**:

1. Create a project in Label Studio
2. Open the project
3. Look at the URL: `http://localhost:8085/projects/1/data`
4. The number after `/projects/` is the ID

**Update `.env`**:
```dotenv
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_SEGMENT=2
LS_PROJECT_TRANSLATION=3
```

---

#### 4. Google Drive / DVC Credentials

| File | Location | How to Get It |
|------|----------|---------------|
| OAuth Client Secret | `.secrets/client_secret_*.json` | Google Cloud Console |
| Cached Auth Token | `~/.cache/pydrive2fs/credentials.json` | Auto-generated after OAuth flow |

**First-Time Setup**:
```powershell
# Run OAuth flow (opens browser for Google login)
docker compose run --rm ingestion python src/setup_gdrive_auth.py
```

**For Team Members**:
1. Get `credentials.json` from project owner
2. Place it at `~/.cache/pydrive2fs/credentials.json`
3. Or run the OAuth flow yourself

---

#### 5. Gemini API Keys (for Translation)

| Variable | Where It's Set | How to Get It |
|----------|---------------|---------------|
| `GEMINI_API_KEY_1` | `.env` | Google AI Studio |
| `GEMINI_API_KEY_2` | `.env` | Google AI Studio (backup for rate limits) |

**How to Get Gemini API Key**:

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key**
3. Copy the key

**Update `.env`**:
```dotenv
GEMINI_API_KEY_1=AIzaSyB...your_key_here
GEMINI_API_KEY_2=AIzaSyC...backup_key
```

---

### Complete `.env` Template

```dotenv
# =============================================================================
# Database Configuration
# =============================================================================
POSTGRES_USER=admin
POSTGRES_PASSWORD=secret_password
POSTGRES_DB=data_factory
DATABASE_URL=postgresql://admin:secret_password@localhost:5432/data_factory

# =============================================================================
# Label Studio Configuration
# =============================================================================
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_40_char_hex_token_here

# Project IDs (update after creating projects)
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_SEGMENT=2
LS_PROJECT_TRANSLATION=3

# =============================================================================
# Audio Server Configuration
# =============================================================================
AUDIO_SERVER_URL=http://localhost:8081

# =============================================================================
# Gemini API Keys (for translation)
# =============================================================================
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=

# =============================================================================
# Sync Configuration
# =============================================================================
SYNC_INTERVAL_MINUTES=5
```

---

### Simplified Commands (When `.env` is Configured)

Once your `.env` file has all credentials, you can use shorter commands:

```powershell
# DATABASE_URL is in .env, so no need to pass it
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Label Studio vars are in .env
docker compose run --rm -e AUDIO_PUBLIC_URL=http://localhost:8081 ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Pull doesn't need AUDIO_PUBLIC_URL
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type transcript_correction
```

> **Note**: `AUDIO_PUBLIC_URL` should be `http://localhost:8081` when pushing to Label Studio because the browser needs to access audio files. The internal Docker URL (`http://audio_server:80`) won't work from your browser.

---

## 11. Troubleshooting

### Container Won't Start

**Symptom**: `docker compose up` fails or container exits immediately

```powershell
# Check logs
docker compose logs postgres
docker compose logs labelstudio

# Verify ports aren't in use
netstat -an | findstr "5432"
netstat -an | findstr "8085"

# Rebuild containers
docker compose down
docker compose up -d --build
```

### Database Connection Failed

**Symptom**: `connection refused` or `password authentication failed`

```powershell
# Check postgres is running
docker compose ps postgres

# Verify connection string
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT 1;"

# Check password in docker-compose.yml
# Default: secret_password
```

### Audio Not Loading in Label Studio

**Symptom**: Red error in Label Studio audio player

```powershell
# Test audio server
curl http://localhost:8081/audio/VIDEO_ID.wav

# Check file exists
docker exec audio_server ls -la /usr/share/nginx/html/audio/

# Ensure AUDIO_PUBLIC_URL is set when pushing
# Must be http://localhost:8081 (not internal Docker hostname)
```

### Label Studio API 401 Unauthorized

**Symptom**: `Invalid token` or `401` errors

```powershell
# Verify token format (must be 40-char hex, NOT JWT)
# Wrong: eyJhbGciOiJIUzI1NiIs...
# Right: 8a467af13f65511a4f8cc9dd93dff4fe847477e0

# Check token in Label Studio UI
# Settings → Account & Settings → Access Token
```

### "No samples ready" When Pushing

**Symptom**: `Found 0 samples ready for transcript_correction`

```powershell
# Check sample states
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state, label_studio_task_id FROM samples;"

# Samples need:
# - processing_state = 'RAW' (for transcript_correction)
# - label_studio_task_id = NULL (not already pushed)
```

### DVC Push/Pull Fails

**Symptom**: `ERROR: failed to push/pull` or authentication errors

```powershell
# Re-authenticate Google Drive
docker compose run --rm ingestion python src/setup_gdrive_auth.py

# Check DVC status
docker compose run --rm ingestion dvc status

# Verify remote configuration
docker compose run --rm ingestion dvc remote list
```

### GPU Not Detected (Preprocessing)

**Symptom**: WhisperX or DeepFilterNet runs on CPU (slow)

```powershell
# Check NVIDIA driver
nvidia-smi

# Verify Docker GPU support
docker run --rm --gpus all nvidia/cuda:11.8-base nvidia-smi

# Add to docker-compose.yml for GPU services:
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```

### Out of Memory Errors

**Symptom**: Container killed or `OOM` errors

```powershell
# Reduce batch size
python src/preprocessing/whisperx_align.py --batch --limit 5

# Check Docker memory limits
docker stats

# Increase Docker Desktop memory allocation
# Settings → Resources → Memory
```

---

## Related Documentation

- [01_setup_project.md](01_setup_project.md) - Initial environment setup
- [04_workflow.md](04_workflow.md) - Full pipeline workflow
- [05_scripts_details.md](05_scripts_details.md) - Script documentation
- [06_database_design.md](06_database_design.md) - Database schema
- [07_label_studio.md](07_label_studio.md) - Label Studio integration

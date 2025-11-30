# Command Reference

Complete command reference for the Vietnamese-English Code-Switching Speech Translation pipeline.

> **Note**: All commands use Docker. Ensure services are running with `docker compose up -d`.

---

## Table of Contents

1. [Quick Reference](#1-quick-reference)
2. [Docker Management](#2-docker-management)
3. [YouTube Ingestion](#3-youtube-ingestion)
4. [Gemini Processing](#4-gemini-processing)
5. [Label Studio Sync](#5-label-studio-sync)
6. [Preprocessing](#6-preprocessing)
7. [Database Operations](#7-database-operations)
8. [DVC Data Versioning](#8-dvc-data-versioning)
9. [Common Workflows](#9-common-workflows)

---

## 1. Quick Reference

### Most Used Commands

```powershell
# Start services
docker compose up -d

# Ingest YouTube video
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Gemini transcription + translation
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch --limit 5

# Push to Label Studio
docker compose run --rm -e AUDIO_PUBLIC_URL=http://localhost:8081 ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Pull annotations
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type transcript_correction

# Check pipeline status
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT processing_state, COUNT(*) FROM samples GROUP BY processing_state;"

# Backup & sync
docker compose run --rm ingestion python src/db_backup.py
docker compose run --rm ingestion dvc push
```

---

## 2. Docker Management

### Start/Stop Services

```powershell
# Start all services
docker compose up -d

# Start specific services
docker compose up -d postgres audio_server labelstudio

# Stop services (preserves data)
docker compose down

# Stop and DELETE all data
docker compose down -v

# Rebuild after code changes
docker compose up -d --build
```

### View Logs

```powershell
docker compose logs -f labelstudio
docker compose logs -f postgres
docker compose logs -f audio_server
```

### Service Reference

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| postgres | `factory_ledger` | 5432 | Database |
| labelstudio | `labelstudio` | 8085 | Annotation UI |
| audio_server | `audio_server` | 8081 | Serve audio files |
| ingestion | `factory_ingestion` | - | Run scripts |

---

## 3. YouTube Ingestion

### Script: `src/ingest_youtube.py`

Downloads YouTube videos with transcripts.

```powershell
# Single video
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
docker compose run --rm ingestion python src/ingest_youtube.py "URL1" "URL2"

# Entire channel
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/@ChannelName"

# Use existing metadata (skip download)
docker compose run --rm ingestion python src/ingest_youtube.py --skip-download

# Dry run
docker compose run --rm ingestion python src/ingest_youtube.py --skip-download --dry-run
```

| Argument | Description |
|----------|-------------|
| `urls` | YouTube URLs (positional) |
| `--skip-download` | Use existing `metadata.jsonl` |
| `--dry-run` | Preview without database writes |
| `--no-require-transcript` | Allow videos without subtitles |

---

## 4. Gemini Processing

### Unified Processing: `src/preprocessing/gemini_process.py`

Single-pass transcription + translation using Gemini's multimodal capabilities.

```powershell
# Batch processing (RAW state samples)
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch --limit 5

# Specific sample
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --sample-id <UUID>

# Re-process existing samples
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch --replace-existing

# Use Pro model (better quality, slower)
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch --model gemini-2.5-pro

# Check API key status
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --check-keys

# Dry run
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch --dry-run
```

| Argument | Description |
|----------|-------------|
| `--batch` | Process multiple samples |
| `--sample-id <UUID>` | Process specific sample |
| `--limit N` | Max samples to process |
| `--model` | `gemini-2.5-flash` (default) or `gemini-2.5-pro` |
| `--replace-existing` | Re-process samples with data |
| `--check-keys` | Show API key status |
| `--dry-run` | Preview without changes |

**Output**: Creates both `transcript_revision` and `translation_revision` with sentence-level timestamps.

### Translation Repair: `src/preprocessing/gemini_repair_translation.py`

Repairs sentences flagged with translation issues.

```powershell
# Repair batch
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --batch --limit 10

# Specific sample
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --sample-id <UUID>

# Dry run
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --dry-run
```

---

## 5. Label Studio Sync

### Script: `src/label_studio_sync.py`

Sync between database and Label Studio.

### Push Samples for Review

```powershell
# Transcript correction (Round 1)
docker compose run --rm `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSCRIPT=1 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Translation review (Round 3)
docker compose run --rm `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSLATION=2 `
  ingestion python src/label_studio_sync.py push --task-type translation_review

# With limit
docker compose run --rm `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction --limit 10
```

### Pull Completed Annotations

```powershell
# Pull transcript corrections
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type transcript_correction

# Pull translation reviews
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type translation_review

# Dry run
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type transcript_correction --dry-run
```

### Check Status

```powershell
docker compose run --rm ingestion python src/label_studio_sync.py status
```

### Create Projects

```powershell
docker compose run --rm ingestion python src/create_project.py --task-type transcript_correction
docker compose run --rm ingestion python src/create_project.py --task-type translation_review
```

| Argument | Description |
|----------|-------------|
| `push` | Push samples to Label Studio |
| `pull` | Pull completed annotations |
| `status` | Check connection and pending tasks |
| `--task-type` | `transcript_correction`, `translation_review`, `audio_segmentation` |
| `--limit N` | Max items to process |
| `--dry-run` | Preview without changes |

---

## 6. Preprocessing

### WhisperX Alignment

Force-align transcript with audio (word-level timestamps).

```powershell
# Batch processing
docker compose run --rm ingestion python src/preprocessing/whisperx_align.py --batch --limit 10

# Specific sample
docker compose run --rm ingestion python src/preprocessing/whisperx_align.py --sample-id <UUID>
```

**Requirements**: GPU with 4-8GB VRAM

### Audio Segmentation

Split audio into 10-30 second chunks.

```powershell
# Batch processing
docker compose run --rm ingestion python src/preprocessing/segment_audio.py --batch --limit 10

# Custom duration
docker compose run --rm ingestion python src/preprocessing/segment_audio.py --batch --min-duration 10 --max-duration 30
```

### Audio Denoising

Remove background noise using DeepFilterNet.

```powershell
# Batch processing
docker compose run --rm ingestion python src/preprocessing/denoise_audio.py --batch --limit 10
```

**Requirements**: GPU with 2-4GB VRAM

| Common Arguments | Description |
|------------------|-------------|
| `--sample-id <UUID>` | Process specific sample |
| `--batch` | Process multiple samples |
| `--limit N` | Max samples |
| `--dry-run` | Preview without changes |

---

## 7. Database Operations

### Backup

```powershell
# Incremental backup
docker compose run --rm ingestion python src/db_backup.py

# Full backup
docker compose run --rm ingestion python src/db_backup.py --full

# Dry run
docker compose run --rm ingestion python src/db_backup.py --dry-run
```

### Restore

```powershell
# Import with conflict resolution
docker compose run --rm ingestion python src/db_restore.py

# Force overwrite
docker compose run --rm ingestion python src/db_restore.py --force

# Dry run
docker compose run --rm ingestion python src/db_restore.py --dry-run
```

### Direct Queries

```powershell
# Interactive SQL shell
docker exec -it factory_ledger psql -U admin -d data_factory

# Pipeline status
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT processing_state, COUNT(*) FROM samples GROUP BY processing_state;"

# List samples
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state FROM samples ORDER BY created_at DESC;"

# Recent logs
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT * FROM processing_logs ORDER BY created_at DESC LIMIT 10;"
```

---

## 8. DVC Data Versioning

### Basic Commands

```powershell
# Add data to tracking
docker compose run --rm ingestion dvc add data/raw
docker compose run --rm ingestion dvc add data/db_sync

# Push to remote (Google Drive)
docker compose run --rm ingestion dvc push

# Pull from remote
docker compose run --rm ingestion dvc pull

# Force pull (overwrite)
docker compose run --rm ingestion dvc pull --force

# Check status
docker compose run --rm ingestion dvc status
```

### Setup Google Drive Auth

```powershell
# Run OAuth flow
docker compose run --rm ingestion python src/setup_gdrive_auth.py

# Check status
docker compose run --rm ingestion python src/setup_gdrive_auth.py --check
```

---

## 9. Common Workflows

### Initial Setup

```powershell
docker compose up -d
# Wait 30-60 seconds
# Open http://localhost:8085, create account
# Get API token from Label Studio UI

docker compose run --rm ingestion python src/create_project.py --task-type transcript_correction
```

### Daily Ingestion

```powershell
# 1. Ingest
docker compose run --rm ingestion python src/ingest_youtube.py "URL"

# 2. Process with Gemini
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch

# 3. Repair any issues
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --batch

# 4. Push for review
docker compose run --rm -e AUDIO_PUBLIC_URL=http://localhost:8081 ingestion python src/label_studio_sync.py push --task-type translation_review

# 5. (Human reviews in Label Studio)

# 6. Pull results
docker compose run --rm ingestion python src/label_studio_sync.py pull --task-type translation_review
```

### Data Sync

```powershell
# Backup → Push
docker compose run --rm ingestion python src/db_backup.py
docker compose run --rm ingestion dvc add data/raw data/db_sync
docker compose run --rm ingestion dvc push

# Pull → Restore
docker compose run --rm ingestion dvc pull
docker compose run --rm ingestion python src/db_restore.py
```

### Complete Reset

```powershell
# ⚠️ DELETES ALL DATA
docker compose down -v
Remove-Item -Recurse -Force data/raw/audio/*
Remove-Item -Recurse -Force data/raw/text/*
Remove-Item -Recurse -Force data/db_sync/*
docker compose up -d
```

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer docs

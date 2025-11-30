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

# Prepare for sample review (cut sentence audio)
docker compose run --rm ingestion python src/preprocessing/prepare_review_audio.py --batch

# Push to Label Studio (sample-level review)
$env:DATABASE_URL = "postgresql://admin:secret_password@localhost:5433/data_factory"
$env:LABEL_STUDIO_API_KEY = "YOUR_40_CHAR_TOKEN"
python src/label_studio_sync.py push --limit 10

# Pull completed reviews
python src/label_studio_sync.py pull

# Apply corrections and create final output
docker compose run --rm ingestion python src/preprocessing/apply_review.py --batch

# Export to training dataset
docker compose run --rm ingestion python src/export_reviewed.py --batch

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
| postgres | `factory_ledger` | 5433 | Database |
| labelstudio | `labelstudio` | 8085 | Annotation UI |
| audio_server | `audio_server` | 8081 | Serve audio files |
| ingestion | `factory_ingestion` | - | Run scripts |

> **Note**: PostgreSQL uses port 5433 (not 5432) to avoid conflicts with local installations.

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

## 5. Label Studio Sync (Sample-Level Review)

### Script: `src/label_studio_sync.py`

Sync between database and Label Studio for sample-level review workflow.

### Push Samples for Review

```powershell
# Set environment variables
$env:DATABASE_URL = "postgresql://admin:secret_password@localhost:5433/data_factory"
$env:LABEL_STUDIO_URL = "http://localhost:8085"
$env:LABEL_STUDIO_API_KEY = "YOUR_40_CHAR_TOKEN"

# Push all REVIEW_PREPARED samples
python src/label_studio_sync.py push --limit 10

# Dry run
python src/label_studio_sync.py push --limit 10 --dry-run
```

### Pull Completed Annotations

```powershell
# Pull all completed reviews
python src/label_studio_sync.py pull

# Dry run
python src/label_studio_sync.py pull --dry-run
```

### Reopen Tasks for Re-review

```powershell
# Reopen a sample
python src/label_studio_sync.py reopen --sample-id <UUID>
```

### Check Status

```powershell
python src/label_studio_sync.py status
```

| Argument | Description |
|----------|-------------|
| `push` | Push REVIEW_PREPARED samples to Label Studio |
| `pull` | Pull completed annotations |
| `reopen` | Reopen tasks for re-review |
| `status` | Check connection and pending tasks |
| `--sample-id <UUID>` | Process specific sample |
| `--limit N` | Max items to process |
| `--dry-run` | Preview without changes |

### Label Studio Template (v4 - Paragraphs)

The template uses Label Studio's native `<Paragraphs>` tag with audio synchronization:

- **Full sample audio** via `<Audio>` tag (plays entire sample)
- **Timestamp-synced sentences** via `<Paragraphs>` tag (click to seek & play)
- **Editing table** via `<HyperText>` (5-column layout)
- **No JavaScript required** - all audio handled natively

Task data format:
```json
{
  "audio_url": "http://localhost:8081/audio/{external_id}.wav",
  "paragraphs": [
    {"start": 0.0, "end": 5.2, "text": "...", "idx": "000"},
    ...
  ],
  "sentences_html": "<table>...</table>"
}
```

---

## 6. Preprocessing

### Prepare Review Audio (NEW)

Cut sentence-level audio files and create review chunks for Label Studio.

```powershell
# Batch processing (TRANSLATED → REVIEW_PREPARED)
docker compose run --rm ingestion python src/preprocessing/prepare_review_audio.py --batch --limit 10

# Specific sample
docker compose run --rm ingestion python src/preprocessing/prepare_review_audio.py --sample-id <UUID>

# Custom chunk size
docker compose run --rm ingestion python src/preprocessing/prepare_review_audio.py --batch --chunk-size 20

# Dry run
docker compose run --rm ingestion python src/preprocessing/prepare_review_audio.py --batch --dry-run
```

| Argument | Description |
|----------|-------------|
| `--sample-id <UUID>` | Process specific sample |
| `--batch` | Process all TRANSLATED samples |
| `--limit N` | Max samples to process |
| `--chunk-size N` | Sentences per chunk (default: 15) |
| `--dry-run` | Preview without changes |

**Output**: Creates `data/review/{sample_id}/sentences/{idx:04d}.wav` with 0.2s padding.

### Apply Review Corrections (NEW)

Apply corrections from unified review and create final output.

```powershell
# Batch processing (REVIEW_PREPARED → FINAL)
docker compose run --rm ingestion python src/preprocessing/apply_review.py --batch --limit 10

# Specific sample (requires all chunks completed)
docker compose run --rm ingestion python src/preprocessing/apply_review.py --sample-id <UUID>

# Dry run
docker compose run --rm ingestion python src/preprocessing/apply_review.py --batch --dry-run
```

| Argument | Description |
|----------|-------------|
| `--sample-id <UUID>` | Process specific sample |
| `--batch` | Process all samples with completed reviews |
| `--limit N` | Max samples to process |
| `--dry-run` | Preview without changes |

**Output**: Creates `data/final/{sample_id}/sentences/{idx:04d}.wav` + `manifest.tsv`.

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
# Create unified review project with label_studio_templates/unified_review.xml
```

### Complete Pipeline (Recommended)

```powershell
# Set environment variables (Windows PowerShell)
$env:DATABASE_URL = "postgresql://admin:secret_password@localhost:5433/data_factory"
$env:LABEL_STUDIO_URL = "http://localhost:8085"
$env:LABEL_STUDIO_API_KEY = "YOUR_40_CHAR_TOKEN"

# 1. Ingest from YouTube
python src/ingest_youtube.py "URL"

# 2. Process with Gemini (transcription + translation)
python src/preprocessing/gemini_process.py --batch

# 3. Repair any translation issues
python src/preprocessing/gemini_repair_translation.py --batch

# 4. Prepare for sample review (cut sentence audio)
python src/preprocessing/prepare_review_audio.py --batch

# 5. Push to Label Studio (sample-level review with Paragraphs audio sync)
python src/label_studio_sync.py push --limit 10

# 6. (Human reviews in Label Studio - click sentences to play audio)
#    - Review transcript and translation
#    - Adjust timestamps if needed
#    - Mark sample quality and approval

# 7. Pull completed reviews
python src/label_studio_sync.py pull

# 8. Apply corrections, create final audio
python src/preprocessing/apply_review.py --batch

# 9. Export to training dataset
python src/export_reviewed.py --batch
```

### Daily Review Workflow

```powershell
# Set environment variables
$env:DATABASE_URL = "postgresql://admin:secret_password@localhost:5433/data_factory"
$env:LABEL_STUDIO_URL = "http://localhost:8085"
$env:LABEL_STUDIO_API_KEY = "YOUR_40_CHAR_TOKEN"

# Pull completed reviews
python src/label_studio_sync.py pull

# Apply corrections
python src/preprocessing/apply_review.py --batch

# Export to dataset
python src/export_reviewed.py --batch

# Backup
python src/db_backup.py
dvc push
```

### Re-review a Sample

```powershell
# Reopen sample for re-review
python src/label_studio_sync.py reopen --sample-id <UUID>
```

### Data Sync

```powershell
# Backup → Push
docker compose run --rm ingestion python src/db_backup.py
docker compose run --rm ingestion dvc add data/raw data/db_sync data/dataset
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
Remove-Item -Recurse -Force data/review/*
Remove-Item -Recurse -Force data/final/*
Remove-Item -Recurse -Force data/db_sync/*
docker compose up -d
```

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer docs

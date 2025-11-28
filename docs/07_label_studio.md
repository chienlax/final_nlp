# 07. Label Studio Integration

This document details the Label Studio integration for human annotation in the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Setup & Configuration](#3-setup--configuration)
4. [Label Studio Projects](#4-label-studio-projects)
5. [Workflow](#5-workflow)
6. [DVC Integration](#6-dvc-integration)
7. [Conflict Resolution](#7-conflict-resolution)
8. [Quality Control](#8-quality-control)
9. [API Reference](#9-api-reference)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

Label Studio provides the human annotation interface for:
- **Transcript Correction**: Review and correct ASR-generated transcripts
- **Translation Review**: Validate and fix machine translations
- **Audio Segmentation**: Mark language boundaries in audio

### Key Features
- Concurrent crawling and labeling (no need to finish ingestion before review)
- Automatic 5-minute DVC sync for data consistency
- Conflict detection when samples are modified during annotation
- Gold standard samples for annotator quality control

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATA FLOW ARCHITECTURE                                │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
    │   Google     │◄───────►│  DVC Sync    │◄───────►│  Local Data  │
    │   Drive      │  push   │  Service     │  pull   │  (data/raw)  │
    │   (Source)   │         │  (5 min)     │         │              │
    └──────────────┘         └──────────────┘         └──────┬───────┘
                                                             │
                                                             ▼
    ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
    │  PostgreSQL  │◄───────►│  Label       │◄───────►│  nginx       │
    │  Database    │  sync   │  Studio      │  audio  │  Audio       │
    │              │         │  :8080       │         │  Server :8081│
    └──────────────┘         └──────────────┘         └──────────────┘
           ▲                        │
           │                        ▼
    ┌──────────────┐         ┌──────────────┐
    │  Webhook     │◄────────│  Annotation  │
    │  Server      │ callback│  Completion  │
    │  (FastAPI)   │         │              │
    └──────────────┘         └──────────────┘
```

### Docker Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| `label_studio` | label_studio | 8080 | Annotation interface |
| `audio_server` | audio_server | 8081 | Serve audio files with CORS |
| `sync_service` | sync_service | - | Periodic DVC pull (5 min) |
| `postgres` | factory_ledger | 5432 | Database |
| `ingestion` | factory_ingestion | - | Data ingestion scripts |

---

## 3. Setup & Configuration

### 3.1 Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Key variables:

```bash
# Label Studio
LABEL_STUDIO_URL=http://localhost:8080
LABEL_STUDIO_API_KEY=your_api_key_here
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_TRANSLATION=2
LS_PROJECT_SEGMENTATION=3

# Audio Server
AUDIO_SERVER_URL=http://localhost:8081

# Sync Service
SYNC_INTERVAL_MINUTES=5

# Quality Control
GOLD_SAMPLE_RATIO=0.05
SKIP_GOLD_VALIDATION=false
```

### 3.2 Starting Services

```bash
# Start all services
docker-compose up -d

# Verify services are running
docker-compose ps

# View logs
docker-compose logs -f label_studio
docker-compose logs -f sync_service
```

### 3.3 Initial Label Studio Setup

1. **Access Label Studio**: http://localhost:8080
2. **Create admin account** on first launch
3. **Get API key**: Settings → Account & Settings → Access Token
4. **Update `.env`** with your API key

### 3.4 Apply Database Schema Migration

```bash
# Apply Label Studio schema additions
docker exec -i factory_ledger psql -U admin -d data_factory < init_scripts/03_schema_label_studio_v1.sql
```

---

## 4. Label Studio Projects

### 4.1 Creating Projects

Create three projects in Label Studio using the provided templates:

| Project | Template File | Data Fields |
|---------|---------------|-------------|
| Transcript Correction | `label_studio_templates/transcript_correction.xml` | `audio`, `text`, `sample_id` |
| Translation Review | `label_studio_templates/translation_review.xml` | `source_text`, `translation`, `sample_id` |
| Audio Segmentation | `label_studio_templates/audio_segmentation.xml` | `audio`, `text`, `sample_id` |

### 4.2 Project Setup Steps

1. Click **Create Project**
2. Enter project name (e.g., "Transcript Correction")
3. Go to **Labeling Setup** → **Code**
4. Paste the XML from the corresponding template file
5. Go to **Settings** → **Webhooks**
6. Add webhook URL: `http://host.docker.internal:8000/webhook`
7. Select events: `ANNOTATION_CREATED`, `ANNOTATION_UPDATED`

### 4.3 Template Reference

#### Transcript Correction (`transcript_correction.xml`)
- Audio player with waveform
- Editable text area for corrections
- Quality flags (audio_quality_poor, heavy_code_switching, etc.)
- Confidence rating (1-5 stars)

#### Translation Review (`translation_review.xml`)
- Side-by-side source/target view
- Editable translation text area
- Translation quality issues checklist
- MT quality rating

#### Audio Segmentation (`audio_segmentation.xml`)
- Audio player with region selection
- Language labels (Vietnamese, English, Code-Switched, Silence, Noise)
- Segment quality tags
- Overall audio quality rating

---

## 5. Workflow

### 5.1 Push Samples to Label Studio

```bash
# Push transcript correction tasks
python src/label_studio_sync.py push --task-type transcript_correction --limit 50

# Push translation review tasks
python src/label_studio_sync.py push --task-type translation_review

# Dry run (preview without creating tasks)
python src/label_studio_sync.py push --task-type transcript_correction --dry-run
```

### 5.2 Pull Completed Annotations

```bash
# Pull completed annotations back to database
python src/label_studio_sync.py pull --task-type transcript_correction

# Check status
python src/label_studio_sync.py status
```

### 5.3 Export Reviewed Data

```bash
# Export all reviewed samples
python src/export_reviewed.py

# Export specific task type
python src/export_reviewed.py --task-type transcript_verification

# Dry run
python src/export_reviewed.py --dry-run

# Include previously exported samples
python src/export_reviewed.py --include-exported
```

### 5.4 DVC Pipeline

```bash
# Run export stage
dvc repro export_reviewed

# Generate manifest
dvc repro generate_manifest

# Push reviewed data to remote
dvc push
```

---

## 6. DVC Integration

### 6.1 Sync Daemon

The `sync_service` container runs automatic DVC pulls every 5 minutes:

```bash
# Manual single sync
python src/sync_daemon.py --once

# Check DVC status
python src/sync_daemon.py --status

# Push local changes to remote
python src/sync_daemon.py --push
```

### 6.2 Data Flow

```
Google Drive (DVC Remote)
         │
         ▼ dvc pull (every 5 min)
    data/raw/
    ├── audio/         → served via nginx:8081
    ├── text/          → stored in database
    └── metadata.jsonl
         │
         ▼ after human review
    data/reviewed/
    ├── transcript_verification/
    │   └── {sample_id}/
    │       ├── audio.wav
    │       ├── transcript.json
    │       └── metadata.json
    └── translation_review/
        └── {sample_id}/
            └── ...
         │
         ▼ dvc push
    Google Drive (DVC Remote)
```

### 6.3 Version Tracking

Each sample tracks its DVC version:

| Column | Purpose |
|--------|---------|
| `dvc_commit_hash` | Git commit hash when sample was added |
| `audio_file_md5` | MD5 hash of audio file for integrity |
| `sync_version` | Auto-incremented on file changes |

---

## 7. Conflict Resolution

### 7.1 Conflict Detection

A conflict occurs when:
1. Sample is pushed to Label Studio for annotation
2. Crawler updates the sample (new transcript, different audio)
3. Annotator completes the annotation

The system detects this via `sync_version` comparison.

### 7.2 Conflict Resolution Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `human_wins` | Human annotation takes precedence | Default for corrections |
| `crawler_wins` | New crawled data replaces annotation | Rare, for re-ingestion |
| `merged` | Combine both changes | Complex merge scenarios |
| `pending_reflow` | Create new sample for re-review | When unsure |

### 7.3 Handling Conflicts

```bash
# List conflicts
curl http://localhost:8000/api/conflicts

# Resolve a conflict
curl -X POST "http://localhost:8000/api/resolve-conflict/{annotation_id}?resolution=human_wins"
```

### 7.4 Database Functions

```sql
-- Lock sample before pushing to Label Studio
SELECT * FROM lock_sample_for_annotation('sample-uuid', 'label_studio');

-- Check for conflicts
SELECT * FROM check_annotation_conflict('sample-uuid', expected_version);

-- Create conflict sample for re-review
SELECT create_conflict_sample('original-sample-uuid', 'Reason for conflict');

-- Unlock sample after annotation
SELECT unlock_sample('sample-uuid', TRUE);  -- TRUE = increment version
```

---

## 8. Quality Control

### 8.1 Gold Standard Samples

Gold standard samples are pre-verified samples used to measure annotator accuracy.

```sql
-- Mark a sample as gold standard
SELECT set_gold_standard('sample-uuid', 0.95, 'admin');

-- View gold standard samples
SELECT * FROM v_gold_standard_samples;

-- View annotator accuracy
SELECT * FROM v_annotator_accuracy;
```

### 8.2 Environment Configuration

```bash
# Percentage of samples to use as gold (5%)
GOLD_SAMPLE_RATIO=0.05

# Skip validation for testing
SKIP_GOLD_VALIDATION=true
```

### 8.3 Annotator Metrics

The `v_annotator_accuracy` view provides:
- Total gold annotations per annotator
- Average expected score
- Completion rate percentage

---

## 9. API Reference

### 9.1 Webhook Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Label Studio webhook handler |
| `/api/conflicts` | GET | List annotation conflicts |
| `/api/resolve-conflict/{id}` | POST | Resolve a conflict |
| `/api/stats` | GET | Annotation statistics |

### 9.2 Label Studio Sync CLI

```bash
# Usage
python src/label_studio_sync.py <action> [options]

# Actions
push     Push samples to Label Studio
pull     Pull completed annotations
status   Check connection status

# Options
--task-type    transcript_correction | translation_review | audio_segmentation
--limit        Maximum samples to process
--dry-run      Preview without changes
```

### 9.3 Export CLI

```bash
# Usage
python src/export_reviewed.py [options]

# Options
--task-type         Filter by task type
--limit             Maximum samples to export
--output-dir        Output directory (default: data/reviewed)
--include-exported  Include previously exported
--dry-run           Preview without writing
--no-manifest       Skip manifest generation
```

### 9.4 Sync Daemon CLI

```bash
# Usage
python src/sync_daemon.py [options]

# Options
--once       Run single sync and exit
--interval   Sync interval in minutes (default: 5)
--push       Run dvc push instead of pull
--status     Check DVC status and exit
-v           Verbose output
```

---

## 10. Troubleshooting

### 10.1 Common Issues

#### Audio files not loading in Label Studio
```bash
# Check nginx is serving files
curl http://localhost:8081/audio/test.wav

# Verify CORS headers
curl -I http://localhost:8081/audio/test.wav | grep -i access-control
```

#### Webhook not receiving callbacks
```bash
# Check webhook server is running
curl http://localhost:8000/health

# Verify Label Studio webhook configuration
# Settings → Webhooks → Test Connection
```

#### DVC sync failing
```bash
# Check authentication
dvc remote list
dvc push --verbose

# Re-authenticate
# Delete ~/.cache/pydrive2fs and re-run dvc pull
```

### 10.2 Logs

```bash
# Label Studio logs
docker-compose logs -f label_studio

# Sync service logs
docker-compose logs -f sync_service

# Audio server logs
docker-compose logs -f audio_server

# Webhook server (if running locally)
tail -f logs/webhook.log
```

### 10.3 Database Queries

```sql
-- Check sync status
SELECT * FROM v_sync_status WHERE lock_status != 'unlocked';

-- Find samples with pending annotations
SELECT s.sample_id, a.status, a.task_type
FROM samples s
JOIN annotations a ON s.sample_id = a.sample_id
WHERE a.status IN ('pending', 'in_progress');

-- Check for conflicts
SELECT * FROM annotations WHERE conflict_detected = TRUE;
```

---

## Related Documentation

- [01. Project Setup](01_setup_project.md) - Initial environment setup
- [04. Workflow](04_workflow.md) - Overall pipeline workflow
- [05. Script Details](05_scripts_details.md) - Script documentation
- [06. Database Design](06_database_design.md) - Schema reference

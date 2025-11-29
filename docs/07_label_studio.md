# 07. Label Studio Integration

This document details the Label Studio integration for human annotation in the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Setup & Configuration](#3-setup--configuration)
4. [PostgreSQL Backend](#4-postgresql-backend)
5. [Label Studio Projects](#5-label-studio-projects)
6. [Workflow](#6-workflow)
7. [DVC Integration](#7-dvc-integration)
8. [Conflict Resolution](#8-conflict-resolution)
9. [Quality Control](#9-quality-control)
10. [API Reference](#10-api-reference)
11. [Backup & Recovery](#11-backup--recovery)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

Label Studio provides the human annotation interface for:
- **Transcript Correction**: Review and correct ASR-generated transcripts
- **Translation Review**: Validate and fix machine translations
- **Audio Segmentation**: Mark language boundaries in audio

### Key Features
- **PostgreSQL backend**: All Label Studio data stored in PostgreSQL (same instance as data_factory)
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
    ┌──────────────────────────────────────────────────────────────────────┐
    │                      PostgreSQL (factory_ledger)                      │
    │  ┌─────────────────────────┐    ┌─────────────────────────┐         │
    │  │    data_factory DB      │    │    label_studio DB      │         │
    │  │  - samples              │    │  - users, projects      │         │
    │  │  - transcripts          │    │  - tasks, annotations   │         │
    │  │  - translations         │    │  - Django internals     │         │
    │  └─────────────────────────┘    └─────────────────────────┘         │
    └──────────────────────────────────────────────────────────────────────┘
           ▲                                    ▲
           │                                    │
    ┌──────┴──────┐         ┌──────────────┐   │    ┌──────────────┐
    │  Webhook    │◄────────│  Label       │───┘    │  nginx       │
    │  Server     │ callback│  Studio      │◄──────►│  Audio       │
    │  (FastAPI)  │         │  :8085       │  audio │  Server :8081│
    └─────────────┘         └──────────────┘        └──────────────┘
```

### Docker Services

| Service | Container | Port | Database |
|---------|-----------|------|----------|
| `postgres` | factory_ledger | 5432 | data_factory + label_studio |
| `label_studio` | label_studio | 8085 | Uses label_studio DB |
| `audio_server` | audio_server | 8081 | - |
| `sync_service` | sync_service | - | Uses data_factory DB |
| `ingestion` | factory_ingestion | - | Uses data_factory DB |

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
LABEL_STUDIO_URL=http://localhost:8085
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

1. **Access Label Studio**: http://localhost:8085
2. **Create admin account** on first launch
3. **Get API key**: Settings → Account & Settings → Access Token
4. **Update `.env`** with your API key

> **Note:** Database schemas are applied automatically on first `docker-compose up`. No manual SQL execution needed!

---

## 4. PostgreSQL Backend

Label Studio is configured to use PostgreSQL instead of SQLite, which means:
- **Shared persistence**: All data lives in `./database_data/`
- **Better performance**: PostgreSQL handles concurrent access better
- **Unified backups**: One database backup covers everything

### 4.1 Database Layout

```
PostgreSQL Instance (factory_ledger:5432)
├── data_factory (database)
│   ├── samples
│   ├── transcript_revisions
│   ├── translation_revisions
│   ├── annotations
│   └── ...
└── label_studio (database)
    ├── auth_user (Label Studio users)
    ├── projects_project (Label Studio projects)
    ├── tasks_task (Tasks)
    ├── tasks_annotation (Annotations)
    └── ... (Django internals)
```

### 4.2 Benefits of PostgreSQL Backend

| Feature | SQLite (default) | PostgreSQL (our setup) |
|---------|-----------------|------------------------|
| Concurrent writes | ❌ Limited | ✅ Full support |
| Survives `docker-compose down -v` | ❌ No | ✅ Yes (bind mount) |
| Backup with data_factory | ❌ Separate | ✅ Together |
| Query from Python scripts | ❌ Complex | ✅ Direct SQL |
| Team collaboration | ❌ File locks | ✅ Connection pooling |

### 4.3 Accessing Label Studio Database

```powershell
# Connect to label_studio database
docker exec -it factory_ledger psql -U admin -d label_studio

# List tables
\dt

# Query users
SELECT id, email, is_staff FROM auth_user;

# Query projects
SELECT id, title, created_at FROM projects_project;
```

---

## 5. Label Studio Projects

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

## 6. Workflow

### 6.1 Push Samples to Label Studio

```bash
# Push transcript correction tasks
python src/label_studio_sync.py push --task-type transcript_correction --limit 50

# Push translation review tasks
python src/label_studio_sync.py push --task-type translation_review

# Dry run (preview without creating tasks)
python src/label_studio_sync.py push --task-type transcript_correction --dry-run
```

### 6.2 Pull Completed Annotations

```bash
# Pull completed annotations back to database
python src/label_studio_sync.py pull --task-type transcript_correction

# Check status
python src/label_studio_sync.py status
```

### 6.3 Export Reviewed Data

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

### 6.4 DVC Pipeline

```bash
# Run export stage
dvc repro export_reviewed

# Generate manifest
dvc repro generate_manifest

# Push reviewed data to remote
dvc push
```

---

## 7. DVC Integration

### 7.1 Sync Daemon

The `sync_service` container runs automatic DVC pulls every 5 minutes:

```bash
# Manual single sync
python src/sync_daemon.py --once

# Check DVC status
python src/sync_daemon.py --status

# Push local changes to remote
python src/sync_daemon.py --push
```

### 7.2 Data Flow

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

### 7.3 Version Tracking

Each sample tracks its DVC version:

| Column | Purpose |
|--------|---------|
| `dvc_commit_hash` | Git commit hash when sample was added |
| `audio_file_md5` | MD5 hash of audio file for integrity |
| `sync_version` | Auto-incremented on file changes |

---

## 8. Conflict Resolution

### 8.1 Conflict Detection

A conflict occurs when:
1. Sample is pushed to Label Studio for annotation
2. Crawler updates the sample (new transcript, different audio)
3. Annotator completes the annotation

The system detects this via `sync_version` comparison.

### 8.2 Conflict Resolution Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `human_wins` | Human annotation takes precedence | Default for corrections |
| `crawler_wins` | New crawled data replaces annotation | Rare, for re-ingestion |
| `merged` | Combine both changes | Complex merge scenarios |
| `pending_reflow` | Create new sample for re-review | When unsure |

### 8.3 Handling Conflicts

```bash
# List conflicts
curl http://localhost:8000/api/conflicts

# Resolve a conflict
curl -X POST "http://localhost:8000/api/resolve-conflict/{annotation_id}?resolution=human_wins"
```

### 8.4 Database Functions

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

## 9. Quality Control

### 9.1 Gold Standard Samples

Gold standard samples are pre-verified samples used to measure annotator accuracy.

```sql
-- Mark a sample as gold standard
SELECT set_gold_standard('sample-uuid', 0.95, 'admin');

-- View gold standard samples
SELECT * FROM v_gold_standard_samples;

-- View annotator accuracy
SELECT * FROM v_annotator_accuracy;
```

### 9.2 Environment Configuration

```bash
# Percentage of samples to use as gold (5%)
GOLD_SAMPLE_RATIO=0.05

# Skip validation for testing
SKIP_GOLD_VALIDATION=true
```

### 9.3 Annotator Metrics

The `v_annotator_accuracy` view provides:
- Total gold annotations per annotator
- Average expected score
- Completion rate percentage

---

## 10. API Reference

### 10.1 Webhook Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Label Studio webhook handler |
| `/api/conflicts` | GET | List annotation conflicts |
| `/api/resolve-conflict/{id}` | POST | Resolve a conflict |
| `/api/stats` | GET | Annotation statistics |

### 10.2 Label Studio Sync CLI

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

### 10.3 Export CLI

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

### 10.4 Sync Daemon CLI

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

## 11. Backup & Recovery

### 11.1 Understanding Data Persistence

All persistent data is stored in `./database_data/`:

```
database_data/
├── base/                  # PostgreSQL data files
├── global/                # System catalog
├── pg_wal/                # Write-ahead logs
└── ...
```

**Both databases** (`data_factory` and `label_studio`) are stored here.

### 11.2 Backup Strategies

#### Full Database Backup (Recommended)

```powershell
# Create timestamped backup
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
docker exec factory_ledger pg_dumpall -U admin > "backup_${timestamp}.sql"

# Compress backup
Compress-Archive -Path "backup_${timestamp}.sql" -DestinationPath "backup_${timestamp}.zip"
```

#### Per-Database Backup

```powershell
# Backup data_factory only
docker exec factory_ledger pg_dump -U admin -d data_factory > data_factory_backup.sql

# Backup label_studio only
docker exec factory_ledger pg_dump -U admin -d label_studio > label_studio_backup.sql
```

### 11.3 Restore from Backup

```powershell
# Stop all services
docker-compose down

# Clear existing data (DANGER: destroys all data!)
Remove-Item -Recurse -Force .\database_data\*

# Start only PostgreSQL
docker-compose up -d postgres

# Wait for it to be ready
Start-Sleep -Seconds 10

# Restore backup (PowerShell-compatible)
Get-Content backup_20251128_120000.sql | docker exec -i factory_ledger psql -U admin -d postgres

# Start remaining services
docker-compose up -d
```

### 11.4 Label Studio Export/Import (Alternative)

For portability, you can also use Label Studio's built-in export:

1. **Export Project**: Project Settings → Export → JSON
2. **Import Project**: Create new project → Import → Upload JSON

This exports:
- Project configuration
- Tasks
- Annotations

**Note:** This does NOT export user accounts.

### 11.5 Automated Backup Script

Create `scripts/backup.ps1`:

```powershell
# Automated backup script
$BACKUP_DIR = ".\backups"
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_FILE = "$BACKUP_DIR\backup_$TIMESTAMP.sql"

# Create backup directory
New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null

# Dump all databases
Write-Host "Creating backup: $BACKUP_FILE"
docker exec factory_ledger pg_dumpall -U admin | Out-File -Encoding UTF8 $BACKUP_FILE

# Compress
Compress-Archive -Path $BACKUP_FILE -DestinationPath "$BACKUP_FILE.zip"
Remove-Item $BACKUP_FILE

# Keep only last 7 backups
Get-ChildItem $BACKUP_DIR -Filter "*.zip" | 
    Sort-Object CreationTime -Descending | 
    Select-Object -Skip 7 | 
    Remove-Item

Write-Host "Backup complete: $BACKUP_FILE.zip"
```

### 11.6 Before Clean Reset Checklist

Before running `docker-compose down -v` or deleting `database_data/`:

- [ ] Export Label Studio projects (JSON format)
- [ ] Run database backup (pg_dumpall)
- [ ] Verify backup file is not empty
- [ ] Note your Label Studio API key

---

## 12. Troubleshooting

### 12.1 Common Issues

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

#### Label Studio not starting (PostgreSQL connection)
```powershell
# Check PostgreSQL is healthy
docker-compose ps
docker logs factory_ledger

# Verify label_studio database exists
docker exec factory_ledger psql -U admin -c "\l"
```

### 12.2 Logs

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

### 12.3 Database Queries

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

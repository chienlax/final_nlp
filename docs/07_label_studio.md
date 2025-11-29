# 07. Label Studio Integration

This document provides a **comprehensive guide** for setting up and using Label Studio in the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start Guide](#3-quick-start-guide)
4. [Detailed Setup](#4-detailed-setup)
5. [Creating Projects](#5-creating-projects)
6. [Running the Pipeline](#6-running-the-pipeline)
7. [Annotation Workflow](#7-annotation-workflow)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting](#9-troubleshooting)
10. [Database Integration](#10-database-integration)

---

## 1. Overview

Label Studio provides the human-in-the-loop interface for 3 annotation stages:

| Round | Task Type | Purpose | Template |
|-------|-----------|---------|----------|
| 1 | `transcript_correction` | Review/correct YouTube transcripts | `transcript_correction.xml` |
| 2 | `audio_segmentation` | Verify segment boundaries | `audio_segmentation.xml` / `segment_review.xml` |
| 3 | `translation_review` | Review machine translations | `translation_review.xml` |

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   PostgreSQL    │◄────│  Python Scripts  │────►│  Label Studio   │
│  (data_factory) │     │ (label_studio_   │     │  (localhost:    │
│                 │     │   sync.py)       │     │      8085)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │  Audio Server   │
                                                 │ (localhost:8081)│
                                                 └─────────────────┘
```

---

## 2. Prerequisites

Before starting, ensure you have:

- **Docker Desktop** installed and running
- **Git** for cloning the repository
- **PowerShell** (Windows) or **Bash** (Linux/Mac)
- At least **4GB RAM** available for containers

---

## 3. Quick Start Guide

**For experienced users** - run these commands in order:

```powershell
# 1. Start services
docker compose up -d postgres audio_server labelstudio

# 2. Wait for Label Studio to initialize (30-60 seconds)
Start-Sleep -Seconds 45

# 3. Open Label Studio and create account
# Go to: http://localhost:8085
# Sign up with email/password

# 4. Enable legacy API tokens (required - run in PowerShell)
docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE django_site SET domain='localhost:8085', name='localhost:8085' WHERE id=1; UPDATE authtoken_token SET key=LOWER(key) WHERE LENGTH(key) > 40;"

# 5. Get your API token from Label Studio
# Settings → Account & Settings → Access Token (copy the hex string)

# 6. Create project with template
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN_HERE ingestion python src/create_project.py --task-type transcript_correction

# 7. Ingest a YouTube video
docker compose run --rm -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 8. Push to Label Studio
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN_HERE -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory -e AUDIO_PUBLIC_URL=http://localhost:8081 -e LS_PROJECT_TRANSCRIPT=1 ingestion python src/label_studio_sync.py push --task-type transcript_correction

# 9. Annotate in Label Studio, then pull results
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN_HERE -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/label_studio_sync.py pull --task-type transcript_correction
```

---

## 4. Detailed Setup

### Step 4.1: Start Docker Services

```powershell
cd "path\to\final_nlp"

# Start required services
docker compose up -d postgres audio_server labelstudio

# Verify services are running
docker compose ps
```

Expected output:
```
NAME              STATUS                   PORTS
audio_server      Up (healthy)             0.0.0.0:8081->80/tcp
factory_ledger    Up (healthy)             0.0.0.0:5432->5432/tcp
labelstudio       Up                       0.0.0.0:8085->8085/tcp
```

### Step 4.2: Create Label Studio Account

1. **Wait 30-60 seconds** for Label Studio to fully initialize
2. Open **http://localhost:8085** in your browser
3. Click **Sign Up**
4. Enter your email and password
5. Complete registration

### Step 4.3: Enable Legacy API Tokens

**CRITICAL**: Label Studio uses JWT tokens by default, but our scripts need legacy tokens.

Run this command to enable legacy tokens:

```powershell
docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE django_site SET domain='localhost:8085', name='localhost:8085' WHERE id=1;"
```

### Step 4.4: Get Your API Token

1. In Label Studio, click your **user icon** (top-right corner)
2. Go to **Account & Settings**
3. Find **Access Token** section
4. **Copy the hex string** (40 characters like `8a467af13f65511a4f8cc9dd93dff4fe847477e0`)

> ⚠️ **WARNING**: Do NOT copy the JWT token (starts with `eyJ...`). Copy only the hex Access Token.

### Step 4.5: Verify Connection

Test that everything works:

```powershell
# Test API connection (replace YOUR_TOKEN with your actual token)
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=YOUR_TOKEN ingestion python -c "import requests; r = requests.get('http://labelstudio:8085/api/projects', headers={'Authorization': 'Token YOUR_TOKEN'}); print('Status:', r.status_code, '- Projects:', len(r.json().get('results', [])))"
```

Expected output: `Status: 200 - Projects: 0`

---

## 5. Creating Projects

### Option A: Using the Script (Recommended)

```powershell
# Create Transcript Correction project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type transcript_correction

# Create Translation Review project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type translation_review

# Create Audio Segmentation project
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type audio_segmentation
```

### Option B: Manual Creation via UI

1. Click **Create Project** in Label Studio
2. Enter project name (e.g., "Transcript Correction")
3. Go to **Labeling Setup** tab
4. Click **Code** view
5. Open the template file from `label_studio_templates/` folder
6. Copy and paste the entire XML content
7. Click **Save**

### Project ID Mapping

After creating projects, note their IDs:

| Project Name | Default ID | Environment Variable |
|--------------|------------|---------------------|
| Transcript Correction | 1 | `LS_PROJECT_TRANSCRIPT` |
| Translation Review | 2 | `LS_PROJECT_TRANSLATION` |
| Audio Segmentation | 3 | `LS_PROJECT_SEGMENTATION` |

---

## 6. Running the Pipeline

### Step 6.1: Ingest YouTube Video

```powershell
# Ingest a single video
docker compose run --rm `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Step 6.2: Push Samples for Review

```powershell
# Push for transcript correction
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  -e LS_PROJECT_TRANSCRIPT=1 `
  ingestion python src/label_studio_sync.py push --task-type transcript_correction
```

### Step 6.3: Annotate in Label Studio

1. Open http://localhost:8085
2. Go to your project
3. Click on a task
4. Listen to audio, review/correct transcript
5. Fill in quality flags and confidence
6. Click **Submit**

### Step 6.4: Pull Completed Annotations

```powershell
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory `
  ingestion python src/label_studio_sync.py pull --task-type transcript_correction
```

---

## 7. Annotation Workflow

### Round 1: Transcript Correction

**Input State**: `RAW`  
**Output State**: `TRANSCRIPT_VERIFIED`

**Interface Elements:**
- 🎧 Audio player with playback controls
- 📄 Original transcript (read-only reference)
- ✏️ Corrected transcript (editable)
- 🏷️ Quality flags (checkboxes)
- ⭐ Confidence rating (1-5 stars)
- 📝 Notes field (optional)

**Annotator Tasks:**
1. Listen to the full audio
2. Compare with displayed transcript
3. Edit the **Corrected Transcript** field:
   - Fix Vietnamese diacritics (đ, ă, ê, ơ, ư)
   - Correct English words and phrases
   - Fix code-switching boundaries
   - Remove artifacts like [Music], [Applause]
4. Select applicable quality flags
5. Rate your confidence in the correction
6. Submit

### Round 2: Segment Review

**Input State**: `SEGMENTED`  
**Output State**: `SEGMENT_VERIFIED`

**Annotator Tasks:**
1. Verify no words are cut at segment boundaries
2. Confirm transcript matches segment audio
3. Approve or reject each segment

### Round 3: Translation Review

**Input State**: `TRANSLATED`  
**Output State**: Ready for next stage

**Annotator Tasks:**
1. Review machine translation accuracy
2. Fix translation errors
3. Ensure natural Vietnamese phrasing
4. Approve or reject

---

## 8. Configuration Reference

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `LABEL_STUDIO_URL` | Label Studio base URL | `http://localhost:8085` | `http://labelstudio:8085` (Docker) |
| `LABEL_STUDIO_API_KEY` | API authentication token | - | `8a467af13f65...` |
| `DATABASE_URL` | PostgreSQL connection string | - | `postgresql://admin:secret_password@postgres:5432/data_factory` |
| `AUDIO_PUBLIC_URL` | Public URL for audio files | `http://localhost:8081` | Browser accesses audio here |
| `AUDIO_SERVER_URL` | Internal Docker audio URL | `http://audio_server:80` | For container-to-container |
| `LS_PROJECT_TRANSCRIPT` | Transcript review project ID | `1` | |
| `LS_PROJECT_TRANSLATION` | Translation review project ID | `2` | |
| `LS_PROJECT_SEGMENTATION` | Segmentation review project ID | `3` | |

### Docker Service Names

| Service | Container Name | Internal Hostname | External Port |
|---------|---------------|-------------------|---------------|
| PostgreSQL | `factory_ledger` | `postgres` | 5432 |
| Label Studio | `labelstudio` | `labelstudio` | 8085 |
| Audio Server | `audio_server` | `audio_server` | 8081 |

> **Note**: Service names cannot contain underscores (RFC 1035 hostname rules).

### Template Files

Located in `label_studio_templates/`:

| File | Purpose | Required Data Fields |
|------|---------|---------------------|
| `transcript_correction.xml` | Transcript review | `audio`, `external_id`, `duration_seconds`, `subtitle_type`, `transcript_text` |
| `translation_review.xml` | Translation review | `audio`, `source_text`, `translation` |
| `audio_segmentation.xml` | Segment boundaries | `audio`, `segments` |
| `segment_review.xml` | Segment verification | `segment_audio`, `transcript_text` |

---

## 9. Troubleshooting

### Audio Not Loading

**Symptom**: Red error "There was an issue loading URL from $audio value"

**Cause**: Audio URL uses internal Docker hostname (`audio_server:80`)

**Solution**: Ensure `AUDIO_PUBLIC_URL=http://localhost:8081` is set when pushing tasks:

```powershell
docker compose run --rm `
  -e AUDIO_PUBLIC_URL=http://localhost:8081 `
  # ... other env vars ...
  ingestion python src/label_studio_sync.py push --task-type transcript_correction
```

**Verify Audio Server**:
```powershell
# Test audio file access
curl http://localhost:8081/audio/YOUR_VIDEO_ID.wav
```

### API Token Issues

**Symptom**: `401 Unauthorized` or `Invalid token`

**Causes & Solutions**:

1. **Wrong token format**: Copy the **Access Token** (40-char hex), NOT the JWT token
2. **Legacy tokens disabled**: Run:
   ```powershell
   docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE authtoken_token SET key=LOWER(key) WHERE LENGTH(key) > 40;"
   ```

### Docker Hostname Resolution

**Symptom**: `Failed to resolve 'labelstudio'`

**Solution**: Restart all containers together:
```powershell
docker compose down
docker compose up -d postgres audio_server labelstudio
```

### "No samples ready" When Pushing

**Symptom**: `Found 0 samples ready for transcript_correction`

**Causes**:
1. No samples in database in correct state
2. Samples already have `label_studio_task_id` set

**Check database**:
```powershell
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state, label_studio_task_id FROM samples;"
```

### Template Validation Errors

**Symptom**: "Couldn't validate the config" when pasting template

**Solution**: Ensure all `<Text>` elements have a `name` attribute:
```xml
<!-- Wrong -->
<Text value="$some_field"/>

<!-- Correct -->
<Text name="field_display" value="$some_field"/>
```

### Database Reset After Docker Restart

**Symptom**: Data disappears after `docker compose down`

**Note**: Running `docker compose down` removes containers but preserves volumes. To fully reset:
```powershell
docker compose down -v  # WARNING: Deletes all data
```

---

## 10. Database Integration

### Sample States

```
RAW → TRANSCRIPT_REVIEW → TRANSCRIPT_VERIFIED → ALIGNED → SEGMENTED → 
SEGMENT_REVIEW → SEGMENT_VERIFIED → TRANSLATED → TRANSLATION_REVIEW → 
FINAL_REVIEWED → DENOISED → EXPORTED
```

### Check Pipeline Status

```sql
-- Samples by state
SELECT processing_state, COUNT(*) 
FROM samples 
GROUP BY processing_state;

-- Pending annotations
SELECT s.external_id, a.task_type, a.status
FROM samples s
JOIN annotations a ON s.sample_id = a.sample_id
WHERE a.status = 'pending';
```

### Annotation Tracking

When tasks are pushed:
- Entry created in `annotations` table
- `label_studio_task_id` recorded

When annotations complete:
- `samples.processing_state` transitions
- Results stored in `transcript_revisions` or `segment_translations`
- `processing_logs` records the operation

---

## Quick Reference Commands

```powershell
# === SERVICE MANAGEMENT ===
docker compose up -d postgres audio_server labelstudio  # Start services
docker compose ps                                        # Check status
docker compose logs -f labelstudio                       # View logs
docker compose down                                      # Stop services

# === PIPELINE OPERATIONS ===
# Ingest video
docker compose run --rm -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/ingest_youtube.py "URL"

# Push for review
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=TOKEN -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory -e AUDIO_PUBLIC_URL=http://localhost:8081 -e LS_PROJECT_TRANSCRIPT=1 ingestion python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=TOKEN -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/label_studio_sync.py pull --task-type transcript_correction

# Check status
docker compose run --rm -e LABEL_STUDIO_URL=http://labelstudio:8085 -e LABEL_STUDIO_API_KEY=TOKEN -e DATABASE_URL=postgresql://admin:secret_password@postgres:5432/data_factory ingestion python src/label_studio_sync.py status

# === DATABASE QUERIES ===
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state FROM samples;"
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT * FROM annotations;"
```

---

## Related Documentation

- [01_setup_project.md](01_setup_project.md) - Initial environment setup
- [04_workflow.md](04_workflow.md) - Full pipeline workflow
- [05_scripts_details.md](05_scripts_details.md) - Script documentation
- [06_database_design.md](06_database_design.md) - Database schema

# 07. Label Studio Integration

This document details the Label Studio setup for human annotation in the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## 1. Overview

Label Studio provides the human-in-the-loop interface for 3 review stages:

| Round | Stage | Task |
|-------|-------|------|
| 1 | TRANSCRIPT_REVIEW | Correct transcript errors |
| 2 | SEGMENT_REVIEW | Verify segment boundaries |
| 3 | TRANSLATION_REVIEW | Review translations |

---

## 2. Setup

### Start Services

```bash
docker-compose up -d postgres label_studio audio_server
```

### Initial Configuration

1. **Access Label Studio**: http://localhost:8085
2. **Create admin account** on first launch
3. **Get API key**: Settings → Account & Settings → Access Token
4. **Update `.env`**:
   ```bash
   LABEL_STUDIO_URL=http://localhost:8085
   LABEL_STUDIO_API_KEY=your_api_key
   ```

### Create Projects

Create 3 projects using templates from `label_studio_templates/`:

| Project | Template |
|---------|----------|
| Transcript Correction | `transcript_correction.xml` |
| Segment Review | `segment_review.xml` |
| Translation Review | `translation_review.xml` |

**Steps:**
1. Click **Create Project**
2. Enter project name
3. Go to **Labeling Setup** → **Code**
4. Paste XML from template file
5. Save

---

## 3. Projects

### Round 1: Transcript Correction

**Template:** `label_studio_templates/transcript_correction.xml`

**Purpose:** Review and correct raw transcripts (especially auto-generated ones).

**Interface:**
- Audio player with waveform
- Editable transcript text area
- Quality flags (audio issues, heavy CS)
- Confidence rating

**Human Tasks:**
- Fix Vietnamese diacritics
- Correct English words/phrases
- Fix ASR errors
- Flag quality issues

### Round 2: Segment Review

**Template:** `label_studio_templates/segment_review.xml`

**Purpose:** Verify segment boundaries and per-segment transcripts.

**Interface:**
- Segment audio player
- Display of segment transcript
- Boundary verification checkboxes
- Transcript accuracy rating

**Human Tasks:**
- Verify no words are cut at boundaries
- Confirm transcript matches audio
- Flag alignment issues
- Approve or reject segments

### Round 3: Translation Review

**Template:** `label_studio_templates/translation_review.xml`

**Purpose:** Review machine translations for accuracy.

**Interface:**
- Segment audio player
- Source transcript (code-switched)
- Editable translation text area
- Translation quality checklist

**Human Tasks:**
- Verify translation accuracy
- Fix translation errors
- Ensure natural Vietnamese phrasing
- Final approve/reject decision

---

## 4. Workflow

### Push Samples to Label Studio

```bash
# Push for transcript review
python src/label_studio_sync.py push --task-type transcript_correction --limit 50

# Push for segment review
python src/label_studio_sync.py push --task-type segment_review

# Push for translation review
python src/label_studio_sync.py push --task-type translation_review

# Dry run
python src/label_studio_sync.py push --task-type transcript_correction --dry-run
```

### Pull Completed Annotations

```bash
# Pull completed transcript corrections
python src/label_studio_sync.py pull --task-type transcript_correction

# Check status
python src/label_studio_sync.py status
```

### State Transitions

| Action | Before State | After State |
|--------|--------------|-------------|
| Push transcript task | RAW | TRANSCRIPT_REVIEW |
| Complete transcript review | TRANSCRIPT_REVIEW | TRANSCRIPT_VERIFIED |
| Push segment task | SEGMENTED | SEGMENT_REVIEW |
| Complete segment review | SEGMENT_REVIEW | SEGMENT_VERIFIED |
| Push translation task | TRANSLATED | TRANSLATION_REVIEW |
| Complete translation review | TRANSLATION_REVIEW | (ready for DENOISED) |

---

## 5. Audio Server

The audio server (nginx) serves audio files to Label Studio.

**URL:** http://localhost:8081

**Configuration:** `nginx.conf`

**Test:**
```bash
curl http://localhost:8081/audio/test.wav
```

---

## 6. Environment Variables

```bash
# Label Studio
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_api_key

# Project IDs (update after creating projects)
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_SEGMENT=2
LS_PROJECT_TRANSLATION=3

# Audio Server
AUDIO_SERVER_URL=http://localhost:8081
```

---

## 7. Database Integration

### Annotation Tracking

When tasks are pushed/pulled:
- `samples.processing_state` is updated
- `processing_logs` records the operation
- Completed annotations update `transcript_revisions` or `segment_translations`

### Query Pending Tasks

```sql
-- Samples awaiting transcript review
SELECT external_id, created_at
FROM samples
WHERE processing_state = 'TRANSCRIPT_REVIEW';

-- Segments awaiting review
SELECT s.external_id, COUNT(*) as pending_segments
FROM samples s
JOIN segments seg ON s.sample_id = seg.sample_id
WHERE s.processing_state = 'SEGMENT_REVIEW'
  AND seg.is_verified = FALSE
GROUP BY s.external_id;
```

---

## 8. Backup

### Export Projects

1. Go to Project Settings → Export
2. Choose JSON format
3. Download

This exports:
- Project configuration
- Tasks
- Annotations

**Note:** Does not export user accounts.

### Database Backup

```powershell
# Full backup (includes both data_factory and label_studio DBs)
docker exec postgres_nlp pg_dumpall -U admin > backup.sql
```

---

## 9. Troubleshooting

### Audio not loading

```bash
# Check audio server
curl -I http://localhost:8081/audio/test.wav

# Check CORS headers
curl -I http://localhost:8081/audio/test.wav | grep -i access-control
```

### Connection issues

```bash
# Check services are running
docker-compose ps

# Check Label Studio logs
docker-compose logs -f label_studio
```

### API errors

```bash
# Test API connection
curl -H "Authorization: Token YOUR_API_KEY" \
     http://localhost:8085/api/projects/
```

---

## Related Documentation

- [01_setup_project.md](01_setup_project.md) - Environment setup
- [04_workflow.md](04_workflow.md) - Pipeline workflow
- [06_database_design.md](06_database_design.md) - Database schema

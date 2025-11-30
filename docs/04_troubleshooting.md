# Troubleshooting

Common issues and solutions for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Docker & Services](#1-docker--services)
2. [Database](#2-database)
3. [Label Studio](#3-label-studio)
4. [Gemini API](#4-gemini-api)
5. [DVC & Data Sync](#5-dvc--data-sync)
6. [GPU & Preprocessing](#6-gpu--preprocessing)

---

## 1. Docker & Services

### Container Won't Start

**Symptom**: `docker compose up` fails or container exits immediately

```powershell
# Check logs
docker compose logs postgres
docker compose logs labelstudio

# Verify ports aren't in use
netstat -an | findstr "5433"
netstat -an | findstr "8085"

# Rebuild containers
docker compose down
docker compose up -d --build
```

> **Note**: PostgreSQL uses port 5433 to avoid conflicts with local PostgreSQL installations.

### Service Health Check

```powershell
docker compose ps
docker inspect factory_ledger --format='{{.State.Health.Status}}'
```

### Internal vs External Hostnames

| Context | PostgreSQL | Label Studio | Audio Server |
|---------|------------|--------------|--------------|
| Inside Docker | `postgres` | `labelstudio` | `audio_server` |
| From Host | `localhost` | `localhost` | `localhost` |

**Example**: `DATABASE_URL` uses `postgres` inside containers, `localhost` from host.

---

## 2. Database

### Connection Failed

**Symptom**: `connection refused` or `password authentication failed`

```powershell
# Check postgres is running
docker compose ps postgres

# Test connection
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT 1;"

# Default credentials (in docker-compose.yml):
# User: admin
# Password: secret_password
```

### Schema Issues

```powershell
# Apply schema manually
Get-Content init_scripts\01_schema.sql | docker exec -i factory_ledger psql -U admin -d data_factory

# Apply migration
Get-Content init_scripts\02_gemini_process_migration.sql | docker exec -i factory_ledger psql -U admin -d data_factory
```

### Data Lost After Restart

- `docker compose down` preserves volumes ✅
- `docker compose down -v` **DELETES** all data ❌

---

## 3. Label Studio

### Audio Not Playing

**Symptom**: Audio player shows but doesn't play, or audio doesn't seek when clicking sentences

**Template v4 uses native Label Studio tags**:
- `<Audio>` tag for the main audio player
- `<Paragraphs>` tag with `audioUrl` and `sync="audio"` for timestamp-synced playback

**Common causes**:

1. **Audio server not running**:
   ```powershell
   docker compose ps audio_server
   # Should show "Up (healthy)"
   ```

2. **Wrong audio URL**:
   ```powershell
   # Test audio file access
   curl http://localhost:8081/audio/VIDEO_ID.wav
   ```

3. **CORS issues** (audio server needs proper headers):
   The nginx audio server is configured with CORS headers. If using a different server, ensure these headers are set:
   ```
   Access-Control-Allow-Origin: *
   Access-Control-Allow-Methods: GET, OPTIONS
   ```

4. **Audio file doesn't exist**:
   ```powershell
   # Check if file exists
   Test-Path "data/raw/audio/VIDEO_ID.wav"
   ```

**Verify audio URL in task data**:
```powershell
# Check task data in Label Studio
python -c "
import requests
API_KEY = 'YOUR_TOKEN'
resp = requests.get('http://localhost:8085/api/tasks/TASK_ID/', 
                    headers={'Authorization': f'Token {API_KEY}'})
print(resp.json()['data']['audio_url'])
"
```

### API Token Issues

**Symptom**: `401 Unauthorized` or `Invalid token`

**Causes**:

1. **Wrong token format**: Copy **Access Token** (40-char hex), NOT JWT
   - ✅ `8a467af13f65511a4f8cc9dd93dff4fe847477e0`
   - ❌ `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`

2. **Legacy tokens disabled**: Run this SQL:
   ```powershell
   docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE django_site SET domain='localhost:8085', name='localhost:8085' WHERE id=1;"
   ```

### "No samples ready" When Pushing

**Symptom**: `Found 0 samples ready for transcript_correction`

**Check sample states**:
```powershell
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state, label_studio_task_id FROM samples;"
```

**Requirements**:
- `processing_state = 'RAW'` for transcript_correction
- `label_studio_task_id = NULL` (not already pushed)

### Docker Hostname Resolution

**Symptom**: `Failed to resolve 'labelstudio'`

```powershell
docker compose down
docker compose up -d postgres audio_server labelstudio
```

---

## 4. Gemini API

### No API Keys Available

**Symptom**: `No API keys available for processing`

**Solution**: Add keys to `.env`:
```dotenv
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
```

Get keys from: https://aistudio.google.com/app/apikey

### Rate Limited

**Symptom**: `429 Too Many Requests` or key marked as exhausted

- Script automatically rotates to next key
- If all keys exhausted, wait until daily reset
- Check status: `python src/preprocessing/gemini_process.py --check-keys`

### JSON Parse Errors

**Symptom**: `JSON parse error on attempt X`

- Script retries up to 3 times automatically
- Usually succeeds on retry
- If persistent, audio may be too complex for model

### Long Audio Processing

**Symptom**: Audio over 20 minutes processes slowly or inconsistently

- Audio >20 minutes is automatically chunked with 20-second overlap
- Overlapping sentences are deduplicated after processing
- Each chunk is processed sequentially with 2-second delay
- For very long audio (>1 hour), consider splitting manually first

### Translation Issues Flagged

**Symptom**: `has_translation_issues = TRUE`

```powershell
# Run repair script
docker compose run --rm ingestion python src/preprocessing/gemini_repair_translation.py --batch
```

---

## 5. DVC & Data Sync

### DVC Push/Pull Fails

**Symptom**: `ERROR: failed to push/pull` or authentication errors

```powershell
# Re-authenticate Google Drive
docker compose run --rm ingestion python src/setup_gdrive_auth.py

# Check status
docker compose run --rm ingestion dvc status

# Verify remote
docker compose run --rm ingestion dvc remote list
```

### Credentials Missing

```powershell
# Check if credentials exist
Test-Path "$HOME\.cache\pydrive2fs\credentials.json"

# Copy from team member
mkdir -Force "$HOME\.cache\pydrive2fs"
Copy-Item "path\to\credentials.json" "$HOME\.cache\pydrive2fs\credentials.json"
```

### Sync Conflict

```powershell
# Force pull (overwrite local)
docker compose run --rm ingestion dvc pull --force

# Force restore database
docker compose run --rm ingestion python src/db_restore.py --force
```

---

## 6. GPU & Preprocessing

### GPU Not Detected

**Symptom**: WhisperX or DeepFilterNet runs on CPU (slow)

```powershell
# Check NVIDIA driver
nvidia-smi

# Verify Docker GPU support
docker run --rm --gpus all nvidia/cuda:11.8-base nvidia-smi
```

**Docker Compose GPU config** (add to service):
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

### Out of Memory

**Symptom**: Container killed or `OOM` errors

```powershell
# Reduce batch size
docker compose run --rm ingestion python src/preprocessing/whisperx_align.py --batch --limit 5

# Check Docker memory
docker stats

# Increase Docker Desktop memory:
# Settings → Resources → Memory
```

### GPU Memory Requirements

| Script | Min VRAM | Recommended |
|--------|----------|-------------|
| whisperx_align.py | 4GB | 8GB |
| denoise_audio.py | 2GB | 4GB |

---

## Quick Diagnostic Commands

```powershell
# Service status
docker compose ps

# Database connectivity (port 5433)
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT 1;"

# Audio server
curl http://localhost:8081/audio/

# Label Studio API
curl http://localhost:8085/api/projects -H "Authorization: Token YOUR_TOKEN"

# Sample states
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT processing_state, COUNT(*) FROM samples GROUP BY processing_state;"

# Check Label Studio tasks
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, label_studio_task_id FROM samples WHERE label_studio_task_id IS NOT NULL;"

# Recent errors
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT * FROM processing_logs WHERE status='error' ORDER BY created_at DESC LIMIT 5;"
```

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🛠️ [Command Reference](03_command_reference.md) - All commands

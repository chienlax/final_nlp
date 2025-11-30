# Getting Started

Quick setup guide for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Docker Desktop | Latest | Container runtime |
| Git | 2.x+ | Version control |
| NVIDIA GPU | 4GB+ VRAM | Preprocessing (optional) |

---

## Quick Start (5 Minutes)

### 1. Clone & Configure

```powershell
git clone <repo_url>
cd final_nlp

# Copy environment template
Copy-Item .env.example .env
```

### 2. Start Services

```powershell
docker compose up -d
```

Wait 30-60 seconds for initialization, then verify:

```powershell
docker compose ps
```

Expected output:
```
NAME              STATUS         PORTS
audio_server      Up (healthy)   0.0.0.0:8081->80/tcp
factory_ledger    Up (healthy)   0.0.0.0:5432->5432/tcp
labelstudio       Up             0.0.0.0:8085->8085/tcp
```

### 3. Setup Label Studio

1. Open http://localhost:8085
2. **Sign up** with email/password
3. Enable legacy API tokens (required):
   ```powershell
   docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE django_site SET domain='localhost:8085', name='localhost:8085' WHERE id=1;"
   ```
4. Get your API token:
   - Click user icon → **Account & Settings** → **Access Token**
   - Copy the **40-character hex string** (NOT the JWT)
5. Update `.env`:
   ```dotenv
   LABEL_STUDIO_API_KEY=your_40_char_hex_token
   ```

### 4. Create Label Studio Project

```powershell
docker compose run --rm `
  -e LABEL_STUDIO_URL=http://labelstudio:8085 `
  -e LABEL_STUDIO_API_KEY=YOUR_TOKEN `
  ingestion python src/create_project.py --task-type transcript_correction
```

### 5. Test the Pipeline

```powershell
# Ingest a YouTube video
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Check database
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state FROM samples;"
```

---

## Credentials Reference

### Database (Pre-configured)

| Variable | Default Value |
|----------|---------------|
| `POSTGRES_USER` | `admin` |
| `POSTGRES_PASSWORD` | `secret_password` |
| `DATABASE_URL` | `postgresql://admin:secret_password@postgres:5432/data_factory` |

### Label Studio API Key

1. Open http://localhost:8085
2. User icon → **Account & Settings** → **Access Token**
3. Copy hex string (e.g., `8a467af13f65511a4f8cc9dd93dff4fe847477e0`)

> ⚠️ **Do NOT** copy the JWT token (starts with `eyJ...`)

### Gemini API Keys

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key**
3. Add to `.env`:
   ```dotenv
   GEMINI_API_KEY_1=AIzaSy...
   GEMINI_API_KEY_2=AIzaSy...  # Optional backup
   ```

### DVC / Google Drive

```powershell
# Run OAuth flow (opens browser)
docker compose run --rm ingestion python src/setup_gdrive_auth.py

# For team members: get credentials.json from project owner
mkdir -Force "$HOME\.cache\pydrive2fs"
Copy-Item "path\to\credentials.json" "$HOME\.cache\pydrive2fs\credentials.json"
```

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| PostgreSQL | 5432 | `localhost:5432` |
| Label Studio | 8085 | http://localhost:8085 |
| Audio Server | 8081 | http://localhost:8081 |

---

## Complete `.env` Template

```dotenv
# Database
DATABASE_URL=postgresql://admin:secret_password@localhost:5432/data_factory

# Label Studio
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_40_char_hex_token
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_TRANSLATION=2

# Gemini API
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=

# Audio
AUDIO_SERVER_URL=http://localhost:8081
```

---

## Next Steps

- 📖 [Architecture & Workflow](02_architecture.md) - Understand the pipeline
- 🛠️ [Command Reference](03_command_reference.md) - All available commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues

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

## Architecture: Server-Client Model

This project uses a **centralized server architecture** for team collaboration:

```
┌─────────────────────────────────────────────────────────────────┐
│                     SERVER (Your Main Desktop)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ PostgreSQL  │  │ Label Studio│  │ Audio Server│              │
│  │  (5433)     │  │   (8085)    │  │   (8081)    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                           │                                      │
│                    DVC ↔ Google Drive                           │
└─────────────────────────────────────────────────────────────────┘
                            │
           ┌────────────────┼────────────────┐
           │                │                │
     ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
     │ Annotator │    │ Annotator │    │ Annotator │
     │ (Browser) │    │ (Browser) │    │ (Browser) │
     └───────────┘    └───────────┘    └───────────┘
           Team members access via http://<server-ip>:8085
```

**Benefits**:
- ✅ Single source of truth (PostgreSQL on server)
- ✅ Team annotates via browser - no local setup needed
- ✅ Data auto-syncs to Google Drive via DVC
- ✅ Server admin manages all processing

---

## Quick Start - Server Setup (5 Minutes)

### Option A: Automated Setup (Recommended)

Run the setup script as Administrator:

```powershell
# Right-click PowerShell → "Run as Administrator"
cd path\to\final_nlp
.\setup.ps1
```

The script will:
1. ✅ Check Docker Desktop is running
2. ✅ Configure Windows Firewall for team access
3. ✅ Create `.env` with your Gemini API key
4. ✅ Start all Docker services
5. ✅ Create Label Studio admin account
6. ✅ Generate `TEAM_ACCESS.txt` with connection info

After setup, share `TEAM_ACCESS.txt` with your team!

### Option B: Manual Setup

#### 1. Clone & Configure

```powershell
git clone <repo_url>
cd final_nlp

# Copy environment template
Copy-Item .env.example .env
```

#### 2. Start Services

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
factory_ledger    Up (healthy)   0.0.0.0:5433->5432/tcp
labelstudio       Up             0.0.0.0:8085->8085/tcp
```

#### 3. Setup Label Studio

1. Open http://localhost:8085
2. **Sign up** with email/password
3. Enable legacy API tokens:
   ```powershell
   docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE core_organization SET legacy_enabled = true WHERE id = 1;"
   ```
4. Get your API token:
   - Click user icon → **Account & Settings** → **Access Token**
   - Copy the **40-character hex string** (NOT the JWT)
5. Update `.env`:
   ```dotenv
   LABEL_STUDIO_API_KEY=your_40_char_hex_token
   ```

---

## Team Member Setup (For Annotators)

Team members don't need to install anything! Just:

1. **Get connection info** from server admin (`TEAM_ACCESS.txt`)
2. **Open browser** to `http://<server-ip>:8085`
3. **Log in** with provided credentials or sign up
4. **Start annotating!**

### Troubleshooting Team Access

| Issue | Solution |
|-------|----------|
| Can't connect | Check you're on same network as server |
| Audio not playing | Allow autoplay in browser, or refresh |
| Page loads slowly | Server may be processing - wait a moment |

---

## Windows Firewall Configuration

For team members to access your server, ensure these firewall rules exist:

```powershell
# Run as Administrator
New-NetFirewallRule -DisplayName "Label Studio (Team Access)" -Direction Inbound -Protocol TCP -LocalPort 8085 -Action Allow -Profile Private,Domain
New-NetFirewallRule -DisplayName "Audio Server (Team Access)" -Direction Inbound -Protocol TCP -LocalPort 8081 -Action Allow -Profile Private,Domain
```

The `setup.ps1` script does this automatically.

---

## Credentials Reference

### Database (Pre-configured)

| Variable | Default Value |
|----------|---------------|
| `POSTGRES_USER` | `admin` |
| `POSTGRES_PASSWORD` | `secret_password` |
| `DATABASE_URL` | `postgresql://admin:secret_password@localhost:5433/data_factory` |

> **Note**: Use port 5433 for external access (from host), port 5432 for internal Docker access.

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

| Service | Port | URL | Access |
|---------|------|-----|--------|
| PostgreSQL | 5433 | `localhost:5433` | Server only |
| Label Studio | 8085 | http://localhost:8085 | Server + Team |
| Audio Server | 8081 | http://localhost:8081 | Server + Team |

> **Note**: PostgreSQL uses port 5433 (not 5432) to avoid conflicts with local installations.

---

## Complete `.env` Template

```dotenv
# =============================================================================
# Database Configuration
# =============================================================================
DATABASE_URL=postgresql://admin:secret_password@localhost:5433/data_factory

# =============================================================================
# Label Studio Configuration
# =============================================================================
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_40_char_hex_token

# Project ID for unified review (transcription + translation)
LS_PROJECT_UNIFIED_REVIEW=1

# =============================================================================
# Gemini API Keys (for audio transcription/translation)
# =============================================================================
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=

# =============================================================================
# Audio Server
# =============================================================================
AUDIO_SERVER_URL=http://localhost:8081
```

---

## Test the Pipeline

```powershell
# Ingest a YouTube video
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Check database
docker exec factory_ledger psql -U admin -d data_factory -c "SELECT external_id, processing_state FROM samples;"
```

---

## Next Steps

- 📖 [Architecture & Workflow](02_architecture.md) - Understand the pipeline
- 🛠️ [Command Reference](03_command_reference.md) - All available commands
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues

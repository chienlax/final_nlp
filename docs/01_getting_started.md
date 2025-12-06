# Getting Started

Quick setup guide for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.10+ | Runtime environment |
| FFmpeg | Latest | Audio processing |
| Git | 2.x+ | Version control |
| NVIDIA GPU | 4GB+ VRAM | DeepFilterNet denoising (optional) |

---

## Architecture Overview

This project uses a **lightweight local-first architecture**:

```
┌──────────────────────────────────────────────────────────────────┐
│                    LOCAL MACHINE (Your Desktop)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │   SQLite    │  │  Streamlit  │  │ Audio Files │               │
│  │ lab_data.db │  │   (8501)    │  │  data/raw/  │               │
│  └─────────────┘  └─────────────┘  └─────────────┘               │
└──────────────────────────────────────────────────────────────────┘
                            │
                    Open localhost:8501
                    in your web browser
```

**Benefits**:
- ✅ No Docker required
- ✅ SQLite database - portable, no server needed
- ✅ Streamlit review app - intuitive web interface
- ✅ Works entirely offline after initial setup

---

## Quick Start (5 Minutes)

### 1. Run Setup Script

```powershell
# Clone the repository
git clone <repo_url>
cd final_nlp

# Run setup (creates venv, installs deps, initializes DB)
.\setup.ps1
```

The script will:
1. ✅ Check Python and FFmpeg are installed
2. ✅ Create virtual environment
3. ✅ Install all dependencies
4. ✅ Initialize SQLite database with schema upgrades

### 2. Activate Environment

After setup, always activate the virtual environment first:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Set API Keys

Create a `.env` file with your Gemini API key:

```dotenv
GEMINI_API_KEY_1=AIzaSy...your-key-here...
GEMINI_API_KEY_2=AIzaSy...optional-backup...
```

Get your API key from: https://aistudio.google.com/app/apikey

---

## Complete Pipeline Walkthrough

### Step 1: Ingest YouTube Videos

```powershell
# Single video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# Re-ingest from existing metadata
python src/ingest_youtube.py --skip-download
```

### Step 2: Denoise Audio (Optional)

```powershell
# Denoise all pending videos
python src/preprocessing/denoise_audio.py --all

# Denoise specific video
python src/preprocessing/denoise_audio.py --video-id VIDEO_ID
```

### Step 3: Process with Gemini

```powershell
# Process all pending videos
python src/preprocessing/gemini_process.py --all

# Process specific video
python src/preprocessing/gemini_process.py --video-id VIDEO_ID
```

### Step 4: Review Segments

```powershell
# Start the Streamlit review app
streamlit run src/review_app.py
```

Open http://localhost:8501 in your browser to:
- Filter by channel and chunk
- Play audio with auto-pause at segment boundaries
- Edit transcript and translation
- Split long segments (>25s)
- Assign reviewers and manage workflow
- Upload/remove transcripts
- Approve or reject segments

### Step 5: Export Dataset

```powershell
# Export approved segments
python src/export_final.py

# Export specific video
python src/export_final.py --video-id VIDEO_ID
```

Output: `data/export/audio/` + `data/export/manifest.tsv`

---

## Advanced: Remote Access with Tailscale (Optional)

For team members to access your Streamlit app remotely over secure VPN:

### Server Setup

```powershell
# Install Tailscale
winget install Tailscale.Tailscale

# Login and connect
tailscale up

# Expose Streamlit via HTTPS
tailscale serve https / http://127.0.0.1:8501
```

### Team Member Access

1. Install Tailscale on your device
2. Join the same Tailscale network  
3. Access via `https://<machine-name>.<tailnet-name>.ts.net`

**Note:** This is completely optional. For local team access, use standard network sharing or VPN solutions.

---

## API Keys Reference

### Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key**
3. Add to `.env`:
   ```dotenv
   GEMINI_API_KEY_1=AIzaSy...
   GEMINI_API_KEY_2=AIzaSy...  # Optional backup
   ```

### DVC / Google Drive (Optional)

For data versioning and backups with DVC:

```powershell
# Initialize DVC remote
dvc remote add -d gdrive gdrive://<folder-id>

# Run OAuth flow for authentication
python src/setup_gdrive_auth.py

# Manual backups can be done via:
# dvc push
```

**Note:** Automated hourly backups are not configured by default. Set up your own backup schedule if needed.

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| Streamlit | 8501 | http://localhost:8501 |
| Audio Server (Docker) | 8081 | http://localhost:8081 |

---

## Environment File Template

```dotenv
# =============================================================================
# Gemini API Keys (for audio transcription/translation)
# =============================================================================
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...  # Optional backup

# =============================================================================
# Optional: Override default paths
# =============================================================================
# DB_PATH=data/lab_data.db
# AUDIO_DIR=data/raw/audio
# DENOISED_DIR=data/denoised
```

---

## Verify Installation

```powershell
# Check Python environment
python --version
pip list | Select-String "streamlit|pydub|google"

# Check database
python -c "from src.db import init_database; print('DB module OK')"

# Start Streamlit
streamlit run src/review_app.py
```

---

## Next Steps

- 📖 [Architecture & Workflow](02_architecture.md) - Understand the pipeline
- 🛠️ [Command Reference](03_command_reference.md) - All available commands  
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer documentation

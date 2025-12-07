# Complete Workflow Guide

Everything you need to run the Vietnamese-English Code-Switching Speech Translation pipeline from start to finish.

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Setup](#setup)
3. [End-to-End Workflow](#end-to-end-workflow)
4. [Command Reference](#command-reference)
5. [Troubleshooting](#troubleshooting)

---

## Quick Reference

```powershell
# 🔧 Setup
.\setup.ps1                                              # Full setup
.\.venv\Scripts\Activate.ps1                             # Activate venv

# 📥 Pipeline Commands
python src/ingest_youtube.py <URL>                       # Download audio
python src/preprocessing/chunk_audio.py --video-id <ID>  # Chunk into 6-min segments
python src/preprocessing/denoise_audio.py --all          # Optional: denoise
python src/preprocessing/gemini_process.py --video-id <ID> # Transcribe + translate
streamlit run src/review_app.py                          # Review in web UI
python src/export_final.py                               # Export dataset

# 🛠️ Utilities
python check_db_state.py                                 # View database status
python clear_pending_segments.py                         # Reset segments to pending
python src/setup_gdrive_auth.py                          # Configure DVC auth
```

---

## Setup

### Prerequisites

| Requirement | Version | Purpose | Installation |
|-------------|---------|---------|--------------|
| **Python** | 3.10+ | Runtime | [python.org](https://www.python.org/downloads/) |
| **FFmpeg** | Latest | Audio processing | [ffmpeg.org](https://ffmpeg.org/download.html) |
| **Git** | 2.x+ | Version control | [git-scm.com](https://git-scm.com/) |
| **NVIDIA GPU** | 4GB+ VRAM | DeepFilterNet (optional) | - |

### One-Time Setup

```powershell
# 1. Clone repository
git clone <repo-url>
cd final_nlp

# 2. Run setup script
.\setup.ps1

# What it does:
#   ✓ Checks Python/FFmpeg installed
#   ✓ Creates virtual environment (.venv)
#   ✓ Installs requirements.txt
#   ✓ Initializes SQLite database with schema
#   ✓ Configures Tailscale (optional)
#   ✓ Sets up backups (optional)

# 3. Set API keys
# Create .env file with:
GEMINI_API_KEY_1=AIzaSy...your-key-here...
GEMINI_API_KEY_2=AIzaSy...optional-backup...
```

Get Gemini API key: https://aistudio.google.com/app/apikey

### Daily Activation

**ALWAYS activate the virtual environment before running commands:**

```powershell
.\.venv\Scripts\Activate.ps1
```

You'll see `(.venv)` prefix in your terminal prompt.

---

## End-to-End Workflow

### Workflow: Process YouTube Video

**Use Case:** Download, transcribe, review, and export a YouTube video.

```powershell
# Step 1: Download audio (16kHz mono WAV)
python src/ingest_youtube.py "https://www.youtube.com/watch?v=gBhbKX0pT_0"
# Output: data/raw/audio/gBhbKX0pT_0.wav

# Step 2: Chunk into 6-minute segments with 5-second overlap
python src/preprocessing/chunk_audio.py --video-id gBhbKX0pT_0
# Output: data/raw/chunks/gBhbKX0pT_0/chunk_0.wav, chunk_1.wav, ...

# Step 3 (Optional): Denoise audio
python src/preprocessing/denoise_audio.py --all
# Modifies audio_path in DB, keeps state='pending'

# Step 4: Transcribe + translate with Gemini
python src/preprocessing/gemini_process.py --video-id gBhbKX0pT_0
# Creates segments with timestamps (min:sec.ms format)
# Updates state to 'transcribed'

# Step 5: Review in Streamlit
streamlit run src/review_app.py
# Access at http://localhost:8501
# - Edit transcripts/translations/timestamps
# - Assign reviewers
# - Mark segments as approved/rejected
# - State transitions: pending → reviewed → approved

# Step 6: Export dataset
python src/export_final.py
# Output: data/export/<timestamp>/
#   - WAV files (2-25 seconds)
#   - manifest.tsv (audio_path, transcript, translation)
```

### Workflow: Batch Processing

**Use Case:** Process all pending videos at once.

```powershell
# Download multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# Chunk all pending videos
python src/preprocessing/chunk_audio.py --all

# Optional: Denoise all
python src/preprocessing/denoise_audio.py --all

# Process all pending chunks
python src/preprocessing/gemini_process.py --all

# Review in Streamlit
streamlit run src/review_app.py
```

### Workflow: Process Playlist

```powershell
# Download entire playlist
python src/ingest_youtube.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"

# Then follow batch processing steps above
```

---

## Command Reference

### ingest_youtube.py

**Purpose:** Download YouTube audio and insert metadata into database.

```powershell
# Single video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# Playlist
python src/ingest_youtube.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"

# Re-ingest from existing metadata.jsonl (skip download)
python src/ingest_youtube.py --skip-download

# Download with manual transcript
python src/ingest_youtube.py "URL" --download-transcript-vi
```

**Output:**
- Audio: `data/raw/audio/<video_id>.wav` (16kHz mono)
- Metadata: `data/raw/metadata.jsonl` (video info)
- Database: Inserts into `videos` table

**States:** `pending` (ready for chunking)

---

### chunk_audio.py

**Purpose:** Split long audio into 6-minute chunks with 5-second overlap.

```powershell
# Chunk specific video
python src/preprocessing/chunk_audio.py --video-id gBhbKX0pT_0

# Chunk all pending videos
python src/preprocessing/chunk_audio.py --all

# Re-chunk (force overwrite)
python src/preprocessing/chunk_audio.py --video-id gBhbKX0pT_0 --force
```

**Output:**
- Chunks: `data/raw/chunks/<video_id>/chunk_0.wav, chunk_1.wav, ...`
- Database: Inserts into `chunks` table with `start_time`, `end_time`, `overlap_duration`

**Settings:** 6-minute chunks (360s), 5-second overlap

---

### denoise_audio.py

**Purpose:** Remove background noise using DeepFilterNet.

```powershell
# Denoise all pending chunks
python src/preprocessing/denoise_audio.py --all

# Denoise specific video's chunks
python src/preprocessing/denoise_audio.py --video-id gBhbKX0pT_0

# Force re-denoise
python src/preprocessing/denoise_audio.py --all --force
```

**Output:**
- Denoised: `data/denoised/<video_id>/chunk_0_denoised.wav`
- Database: Updates `audio_path` in `chunks` table, keeps `state='pending'`

**Note:** This is optional. If skipped, Gemini processes the original chunks.

---

### gemini_process.py

**Purpose:** Transcribe and translate audio using Gemini 2.5 Flash multimodal API.

```powershell
# Process specific video
python src/preprocessing/gemini_process.py --video-id gBhbKX0pT_0

# Process all pending chunks
python src/preprocessing/gemini_process.py --all

# Re-process (force overwrite)
python src/preprocessing/gemini_process.py --video-id gBhbKX0pT_0 --force
```

**Output:**
- Database: Inserts into `segments` table with:
  - `transcript_vi` (Vietnamese transcript)
  - `translation_en` (English translation)
  - `start_time`, `end_time` (in seconds, from min:sec.ms format)
  - `state='transcribed'`

**Model:** `gemini-2.5-flash-preview-09-2025`  
**Timestamp Format:** `min:sec.ms` (e.g., `0:04.54`, `1:23.45`)  
**Validation:** Checks for timestamp overlaps, large gaps (>2s), overly long segments (>25s)

**API Key Rotation:** Automatically rotates between keys in `.env` (GEMINI_API_KEY_1, GEMINI_API_KEY_2, ...)

---

### review_app.py

**Purpose:** Streamlit web interface for reviewing transcriptions.

```powershell
# Start app
streamlit run src/review_app.py

# Custom port
streamlit run src/review_app.py --server.port 8502
```

**Access:** http://localhost:8501

**Features:**
- **Review Audio Transcript Tab:**
  - View videos grouped by channel
  - Filter by state (`pending`, `reviewed`, `approved`, `rejected`)
  - Pagination (25 segments per page)
  - Edit transcript, translation, timestamps (10ms precision)
  - Audio playback with segment-specific start/end
  - Bulk operations (approve/reject all segments in video)
- **Reviewer Management Tab:**
  - Assign reviewers per video
  - Bulk assign by channel
  - Add new reviewers
- **Audio Refinement Tab:**
  - Run DeepFilterNet denoising from UI (subprocess integration)
- **Light/Dark Mode:**
  - Automatic based on system preference
  - CSS variables for custom styling

**Caching:** Database queries cached with 10-60s TTL for performance

---

### export_final.py

**Purpose:** Export approved segments to HuggingFace-compatible dataset.

```powershell
# Export all approved segments
python src/export_final.py

# Export with custom output directory
python src/export_final.py --output-dir data/my_export
```

**Output:**
```
data/export/<timestamp>/
├── manifest.tsv          # audio_path, transcript, translation
├── <video_id>_seg_0.wav
├── <video_id>_seg_1.wav
└── ...
```

**Filters:** Only exports segments with `state='approved'` and `is_exported=0`  
**Audio Processing:** Trims to exact timestamps, applies fade in/out  
**Updates Database:** Sets `is_exported=1` after export

---

### Utility Scripts

#### check_db_state.py

```powershell
# View database status
python check_db_state.py
```

**Output:** Video counts by state, chunk counts, segment counts, reviewer statistics.

#### clear_pending_segments.py

```powershell
# Reset all segments to pending state
python clear_pending_segments.py
```

**Use Case:** Re-run Gemini processing after prompt changes.

#### check_segment_dist.py

```powershell
# Analyze segment duration distribution
python check_segment_dist.py
```

**Output:** Histogram of segment lengths, statistics.

---

## Troubleshooting

### Setup Issues

#### Python Version Error

**Symptom:** `setup.ps1` fails with "Python 3.10+ required"

**Solution:**
```powershell
# Check version
python --version

# Download Python 3.10+ from https://www.python.org/downloads/
# Ensure "Add to PATH" is checked during installation
```

#### FFmpeg Not Found

**Symptom:** `ffmpeg: command not found`

**Solution:**
```powershell
# Download FFmpeg from https://ffmpeg.org/download.html
# Extract to C:\ffmpeg\
# Add C:\ffmpeg\bin\ to PATH environment variable
# Restart PowerShell and verify:
ffmpeg -version
```

#### Virtual Environment Not Activating

**Symptom:** Commands fail with "module not found"

**Solution:**
```powershell
# Manually activate
.\.venv\Scripts\Activate.ps1

# If execution policy error:
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

### Gemini API Issues

#### API Key Invalid

**Symptom:** `401 Unauthorized` or `Invalid API key`

**Solution:**
```powershell
# Verify .env file exists and has correct key
cat .env

# Get new key from https://aistudio.google.com/app/apikey
# Format:
GEMINI_API_KEY_1=AIzaSy...
```

#### Rate Limit Exceeded

**Symptom:** `429 Too Many Requests` or `RESOURCE_EXHAUSTED`

**Solution:**
```powershell
# Add second API key to .env for rotation
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...

# Or wait 1 minute and retry
```

#### thinking_config Error

**Symptom:** `Unknown field for GenerationConfig: thinking_config`

**Solution:** This feature is NOT supported by `gemini-2.5-flash-preview-09-2025`. The error has been fixed in latest version.

---

### Database Issues

#### Database Locked

**Symptom:** `database is locked`

**Solution:**
```powershell
# Stop Streamlit before running batch scripts
# Ctrl+C in Streamlit terminal

# Run batch operation
python src/preprocessing/gemini_process.py --all

# Restart Streamlit
streamlit run src/review_app.py
```

**Explanation:** SQLite allows only one writer at a time. Streamlit holds database connections.

#### Missing review_state Column

**Symptom:** `no such column: review_state`

**Solution:**
```powershell
# Run migration script
python migrate_add_review_state.py

# Output: "Migration complete. 383 segments updated."
```

---

### Streamlit Issues

#### Port Already in Use

**Symptom:** `Address already in use`

**Solution:**
```powershell
# Kill existing Streamlit process
Get-Process python | Stop-Process -Force

# Or use different port
streamlit run src/review_app.py --server.port 8502
```

#### MediaFileHandler Error

**Symptom:** `Missing file <hash>.wav` or `Bad filename`

**Solution:** This error has been fixed with `@st.cache_data` decorators on audio loading. Update to latest version.

#### Laggy Interface

**Solution:** Performance optimizations implemented:
- Database query caching (10-60s TTL)
- Pagination (25 segments per page)
- Lazy audio loading

Ensure you're on latest version.

---

### Audio Processing Issues

#### Chunk Duration Mismatch

**Symptom:** `Chunk duration: 350.0s (expected: 360.0s)`

**Explanation:** Last chunk may be shorter than 6 minutes. This is normal.

#### Denoising Too Slow

**Symptom:** DeepFilterNet takes >1 minute per chunk

**Solution:**
```powershell
# Check GPU availability
nvidia-smi

# If no GPU, denoising will be CPU-only (slower)
# Consider skipping denoising or using smaller batches
```

#### Timestamp Validation Warnings

**Symptom:** `Large gap of 5.23s (from 62.83s to 68.06s)`

**Explanation:** Gemini detected potential missing speech. Review the segment in Streamlit to verify accuracy.

---

### Export Issues

#### No Segments Exported

**Symptom:** `export_final.py` completes but no files created

**Solution:**
```powershell
# Check for approved segments
python check_db_state.py

# If 0 approved segments, review and approve in Streamlit first
streamlit run src/review_app.py
```

#### Audio Export Quality

**Symptom:** Exported audio has clicks/pops

**Explanation:** Likely due to abrupt cuts at timestamps. The export script applies fade in/out (50ms) to minimize this. If persistent, adjust timestamps in Streamlit review.

---

### DVC & Sync Issues

#### DVC Pull Fails

**Symptom:** `ERROR: failed to pull data from the cloud`

**Solution:**
```powershell
# Re-authenticate with Google Drive
python src/setup_gdrive_auth.py

# Follow browser authentication flow
# Ensure you're added as test user in Google Cloud Console
```

#### Backup Not Running

**Symptom:** Automated backups not appearing in Google Drive

**Solution:**
```powershell
# Check Windows Task Scheduler
Get-ScheduledTask -TaskName "NLP_DB_Backup"

# Re-run setup with backup configuration
.\setup.ps1
```

---

### Network Issues

#### Tailscale Not Connecting

**Symptom:** Cannot access Streamlit from remote machine

**Solution:**
```powershell
# Check Tailscale status
tailscale status

# Restart Tailscale service
net stop Tailscale
net start Tailscale

# Verify firewall allows port 8501
New-NetFirewallRule -DisplayName "Streamlit" -Direction Inbound -LocalPort 8501 -Protocol TCP -Action Allow
```

---

## Getting Help

**Still stuck?** Check these resources:

1. **Developer Docs:** [DEVELOPER.md](DEVELOPER.md) for API reference and architecture
2. **Changelog:** [../CHANGELOG.md](../CHANGELOG.md) for recent updates
3. **Code Comments:** Most scripts have detailed docstrings

**Common debugging commands:**
```powershell
# Check database state
python check_db_state.py

# View segment distribution
python check_segment_dist.py

# Test Gemini API connection
python -c "import google.generativeai as genai; genai.configure(api_key='YOUR_KEY'); print(genai.list_models())"

# Verify audio file
ffprobe data/raw/audio/gBhbKX0pT_0.wav
```

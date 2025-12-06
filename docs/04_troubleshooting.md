# Troubleshooting

Common issues and solutions for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Setup & Environment](#1-setup--environment)
2. [SQLite Database](#2-sqlite-database)
3. [Streamlit Review App](#3-streamlit-review-app)
4. [Gemini API](#4-gemini-api)
5. [Audio Processing](#5-audio-processing)
6. [DVC & Data Sync](#6-dvc--data-sync)
7. [Tailscale & Network](#7-tailscale--network)

---

## 1. Setup & Environment

### Python Version Issues

**Symptom**: `setup.ps1` fails with Python version error

```powershell
# Check Python version
python --version

# Requires Python 3.10+
# Download from: https://www.python.org/downloads/
```

### Virtual Environment Not Activating

**Symptom**: Commands fail with "module not found"

```powershell
# Manually activate
.\.venv\Scripts\Activate.ps1

# If activation script blocked by execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify activation (should show .venv path)
Get-Command python | Select-Object Source
```

### Requirements Installation Failed

**Symptom**: `pip install` errors during setup

```powershell
# Upgrade pip
python -m pip install --upgrade pip

# Install with verbose output
pip install -r requirements.txt -v

# If specific package fails, install separately
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install deepfilternet
```

### FFmpeg Not Found

**Symptom**: Audio processing fails with "ffmpeg not found"

```powershell
# Check if FFmpeg is installed
ffmpeg -version

# Install via winget
winget install ffmpeg

# Or via chocolatey
choco install ffmpeg

# Restart terminal after installation
```

---

## 2. SQLite Database

### Database Locked

**Symptom**: `database is locked` error

**Causes**:
1. Multiple processes accessing database simultaneously
2. Streamlit app is running while running batch scripts

**Solutions**:
```powershell
# Stop Streamlit before running batch operations
# Ctrl+C in terminal running Streamlit

# Check for processes using database
Get-Process python | Where-Object {$_.MainWindowTitle -like "*streamlit*"}

# Force close (if needed)
Stop-Process -Name python -Force
```

### Database Corruption

**Symptom**: `database disk image is malformed`

```powershell
# Check database integrity
sqlite3 data/lab_data.db "PRAGMA integrity_check;"

# If corrupted, restore from backup
Copy-Item "data/backups/lab_data_YYYYMMDD_HHMMSS.db" "data/lab_data.db"

# Or restore from DVC
dvc pull data/db_sync.dvc
```

### WAL File Issues

**Symptom**: Database shows stale data or `-wal` file is large

```powershell
# Force WAL checkpoint (merges WAL into main database)
sqlite3 data/lab_data.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Check WAL mode status
sqlite3 data/lab_data.db "PRAGMA journal_mode;"
```

### Missing Tables

**Symptom**: `no such table` error

```powershell
# Re-initialize schema
sqlite3 data/lab_data.db < init_scripts/sqlite_schema.sql

# Verify tables exist
sqlite3 data/lab_data.db ".tables"
```

---

## 3. Streamlit Review App

### App Won't Start

**Symptom**: `streamlit run` fails or shows errors

```powershell
# Check if port 8501 is in use
netstat -an | findstr "8501"

# Kill process using port (if needed)
Get-Process -Id (Get-NetTCPConnection -LocalPort 8501).OwningProcess | Stop-Process

# Start with explicit port
streamlit run src/review_app.py --server.port 8502
```

### Audio Not Playing

**Symptom**: Audio player doesn't work in Streamlit

**Causes**:

1. **Audio file path incorrect**:
   ```powershell
   # Check if segment audio exists
   Test-Path "data/segments/VIDEO_ID/segment_000.wav"
   ```

2. **Browser blocking autoplay**:
   - Click the audio player manually
   - Check browser console for errors

### Session State Lost

**Symptom**: Progress resets when navigating

**Solution**: This is expected Streamlit behavior. The app saves changes to database immediately, so data is not lost.

### Slow Performance

**Symptom**: App is sluggish with many segments

```powershell
# Check segment count
sqlite3 data/lab_data.db "SELECT COUNT(*) FROM segments;"

# If very large (>10000), consider:
# 1. Process videos in smaller batches
# 2. Export and archive completed videos
```

### Cannot Connect Remotely

**Symptom**: Tailscale IP doesn't load Streamlit

```powershell
# Start with network binding
streamlit run src/review_app.py --server.address 0.0.0.0

# Check Tailscale status
tailscale status

# Verify firewall allows port 8501
New-NetFirewallRule -DisplayName "Streamlit" -Direction Inbound -LocalPort 8501 -Protocol TCP -Action Allow
```

---

## 4. Gemini API

### No API Key

**Symptom**: `GEMINI_API_KEY not found in environment`

```powershell
# Create .env file
echo "GEMINI_API_KEY=your_key_here" > .env

# Or set in environment
$env:GEMINI_API_KEY = "your_key_here"
```

Get API key from: https://aistudio.google.com/app/apikey

### Rate Limited

**Symptom**: `429 Too Many Requests` or `Resource exhausted`

**Solutions**:
- Wait for rate limit reset (usually 1 minute for Gemini 2.5 Pro)
- Use multiple API keys (add `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, etc.)
- Reduce batch processing speed

### JSON Parse Errors

**Symptom**: `Failed to parse JSON response`

- Script retries automatically up to 3 times
- Usually succeeds on retry
- If persistent, check if audio is corrupted or too noisy

### Context Length Exceeded

**Symptom**: `Request payload size exceeds limit`

**Solution**: Audio is automatically chunked at 10-minute intervals with 10-second overlap. If still failing:
```powershell
# Check audio duration
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "data/raw/audio/VIDEO_ID.wav"
```

### Processing Stalled

**Symptom**: Script hangs on a specific video

```powershell
# Check current state
sqlite3 data/lab_data.db "SELECT video_id, status FROM videos WHERE status='processing';"

# Reset stalled videos
sqlite3 data/lab_data.db "UPDATE videos SET status='pending' WHERE status='processing';"
```

---

## 5. Audio Processing

### GPU Not Detected

**Symptom**: DeepFilterNet runs on CPU (slow)

```powershell
# Check NVIDIA driver
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Reinstall PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Out of Memory (GPU)

**Symptom**: `CUDA out of memory` error

```powershell
# Process fewer files at a time
python src/preprocessing/denoise_audio.py --limit 5

# Clear GPU memory
python -c "import torch; torch.cuda.empty_cache()"

# Use CPU fallback (slower but works)
$env:CUDA_VISIBLE_DEVICES = ""
python src/preprocessing/denoise_audio.py
```

### DeepFilterNet Installation Failed

**Symptom**: `deepfilternet` module not found

```powershell
# DeepFilterNet requires Rust compiler
# Install from: https://rustup.rs/

# Then install DeepFilterNet
pip install deepfilternet

# If still failing, use pre-built wheel
pip install deepfilternet --only-binary=:all:
```

### Audio Quality Issues

**Symptom**: Denoised audio sounds distorted

**Solutions**:
1. Original audio may be too noisy - check source quality
2. Reduce denoising strength (modify script if needed)
3. Skip denoising for already clean audio

### Segment Duration Wrong

**Symptom**: Segments are outside 2-25 second range

```powershell
# Check segment durations
sqlite3 data/lab_data.db "SELECT segment_id, (end_ms - start_ms)/1000.0 as duration FROM segments ORDER BY duration DESC LIMIT 10;"

# Re-process affected video
python src/preprocessing/gemini_process.py --video-id VIDEO_ID
```

---

## 6. DVC & Data Sync

### DVC Push/Pull Fails

**Symptom**: `ERROR: failed to push/pull`

```powershell
# Re-authenticate Google Drive
python src/setup_gdrive_auth.py

# Check DVC status
dvc status

# Verify remote configuration
dvc remote list
```

### Credentials Missing

**Symptom**: `Unable to authenticate` or credentials prompt

```powershell
# Check if credentials exist
Test-Path "$HOME\.cache\pydrive2fs\credentials.json"

# Run auth setup
python src/setup_gdrive_auth.py

# Follow browser prompts to authenticate
```

### Sync Conflicts

**Symptom**: Local and remote data differ

```powershell
# Force pull (overwrite local)
dvc pull --force

# Or force push (overwrite remote - use with caution)
dvc push --force
```

### Large File Upload Timeout

**Symptom**: Push hangs on large files

```powershell
# Push with progress
dvc push -v

# Push specific files only
dvc push data/segments.dvc
```

---

## 7. Tailscale & Network

### Tailscale Not Connected

**Symptom**: Cannot reach remote machine

```powershell
# Check Tailscale status
tailscale status

# Re-authenticate
tailscale login

# Check if Tailscale service is running
Get-Service Tailscale
Start-Service Tailscale
```

### Cannot Access Streamlit via Tailscale

**Symptom**: Connection refused when accessing via Tailscale IP

**Solutions**:
1. Start Streamlit with network binding:
   ```powershell
   streamlit run src/review_app.py --server.address 0.0.0.0
   ```

2. Check Windows Firewall:
   ```powershell
   # Allow Streamlit port
   New-NetFirewallRule -DisplayName "Streamlit" -Direction Inbound -LocalPort 8501 -Protocol TCP -Action Allow
   ```

3. Check Tailscale ACLs (in Tailscale admin console)

### Audio Server Not Accessible

**Symptom**: Audio files don't load via Tailscale

```powershell
# Check audio server is running
docker compose ps audio_server

# Verify port is accessible
curl http://localhost:8081/audio/

# Check firewall for port 8081
New-NetFirewallRule -DisplayName "AudioServer" -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow
```

---

## Quick Diagnostic Commands

```powershell
# Environment check
python --version
pip list | Select-String "streamlit|torch|deepfilternet"

# Database status
sqlite3 data/lab_data.db "PRAGMA integrity_check;"
sqlite3 data/lab_data.db "SELECT status, COUNT(*) FROM videos GROUP BY status;"
sqlite3 data/lab_data.db "SELECT status, COUNT(*) FROM segments GROUP BY status;"

# Audio files
(Get-ChildItem data/raw/audio/*.wav).Count
(Get-ChildItem data/segments -Recurse -Filter *.wav).Count

# Streamlit check
netstat -an | findstr "8501"

# Tailscale status
tailscale status
tailscale ip

# GPU status
nvidia-smi
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"

# DVC status
dvc status
dvc remote list
```

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `database is locked` | Multiple processes | Stop Streamlit before batch ops |
| `no such table: videos` | Schema not initialized | Run `sqlite3 data/lab_data.db < init_scripts/sqlite_schema.sql` |
| `GEMINI_API_KEY not found` | Missing env var | Add to `.env` file |
| `429 Too Many Requests` | Rate limited | Wait or add more API keys |
| `CUDA out of memory` | GPU overloaded | Reduce batch size or use CPU |
| `ffmpeg not found` | FFmpeg not installed | `winget install ffmpeg` |
| `Module not found` | Venv not activated | `.\.venv\Scripts\Activate.ps1` |

---

---

## 8. Database Sync Issues

### DVC Push Fails

**Symptoms:**
```
ERROR: failed to push data to the cloud
```

**Solutions:**
1. Check authentication:
   ```powershell
   python -m dvc doctor
   python src/setup_gdrive_auth.py
   ```

2. Verify remote configuration:
   ```powershell
   python -m dvc remote list
   ```

3. Check Google Drive permissions on folder `1bn9HIlEzbBX_Vofb5Y3gp530_kH938wr`

### Database Lock During Backup

**Symptoms:**
```
database is locked
```

**Solutions:**
1. Close Streamlit review app
2. Check for WAL files:
   ```powershell
   Get-ChildItem data/lab_data.db*
   ```
3. Wait for WAL checkpoint, then retry backup

### Merge Conflicts in .dvc File

**Symptoms:**
```
CONFLICT (content): Merge conflict in data/lab_data.db.dvc
```

**Solutions:**
1. Keep most recent database version:
   ```powershell
   git checkout --theirs data/lab_data.db.dvc
   python -m dvc checkout data/lab_data.db.dvc
   ```

2. Or manually merge based on timestamp in md5 hash

See [Database Sync Guide](09_database_sync.md#disaster-recovery-procedures) for detailed recovery procedures.

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🛠️ [Command Reference](03_command_reference.md) - All commands
- 💾 [Database Sync](09_database_sync.md) - Team collaboration
- ⚠️ [Known Caveats](06_known_caveats.md) - Limitations

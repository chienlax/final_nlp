# Command Reference

Complete reference for all commands in the Vietnamese-English CS Speech Translation pipeline.

---

## Quick Reference

```powershell
# Setup
.\setup.ps1                                    # Full setup
.\.venv\Scripts\Activate.ps1                   # Activate environment

# Pipeline
python src/ingest_youtube.py <URL>             # Ingest video
python src/preprocessing/denoise_audio.py --all # Denoise
python src/preprocessing/gemini_process.py --all # Process
streamlit run src/review_app.py                # Review
python src/export_final.py                     # Export
```

---

## Setup Commands

### setup.ps1

Comprehensive setup script for the project.

```powershell
# Full setup (venv + deps + DB + Tailscale + backups)
.\setup.ps1

# Skip Tailscale configuration
.\setup.ps1 -SkipTailscale

# Skip backup scheduling
.\setup.ps1 -SkipBackup

# Development mode (includes extra tools)
.\setup.ps1 -DevMode

# Custom backup path
.\setup.ps1 -DriveBackupPath "D:\Backups\NLP"
```

### Virtual Environment

```powershell
# Activate (required before running any Python script)
.\.venv\Scripts\Activate.ps1

# Deactivate
deactivate
```

---

## Ingestion Commands

### ingest_youtube.py

Download YouTube videos and add to database.

```powershell
# Single video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# From channel
python src/ingest_youtube.py "https://www.youtube.com/@ChannelName"

# Download with manual Vietnamese transcript
python src/ingest_youtube.py "URL" --download-transcript-vi

# Re-ingest from existing metadata (skip download)
python src/ingest_youtube.py --skip-download

# Dry run (see what would happen)
python src/ingest_youtube.py --skip-download --dry-run

# Custom database path
python src/ingest_youtube.py --db data/custom.db "URL"
```

**Options:**

| Option | Description |
|--------|-------------|
| `--skip-download` | Use existing metadata.jsonl |
| `--download-transcript-vi` | Download manual Vietnamese transcript if available |
| `--db PATH` | Custom SQLite database path |
| `--dry-run` | Simulate without writing to DB |

---

## Preprocessing Commands

### denoise_audio.py

Remove background noise using DeepFilterNet.

```powershell
# Denoise all pending videos (state=pending)
python src/preprocessing/denoise_audio.py --all

# Denoise specific video
python src/preprocessing/denoise_audio.py --video-id VIDEO_ID

# Limit number of videos
python src/preprocessing/denoise_audio.py --all --limit 5

# Custom output directory
python src/preprocessing/denoise_audio.py --all --output data/clean

# Custom database
python src/preprocessing/denoise_audio.py --all --db data/custom.db
```

**Options:**

| Option | Description |
|--------|-------------|
| `--all` | Process all pending videos |
| `--video-id ID` | Process specific video |
| `--limit N` | Maximum videos to process |
| `--output DIR` | Output directory for denoised audio |
| `--db PATH` | Custom SQLite database path |

**Note:** Denoising updates `denoised_audio_path` but keeps `processing_state='pending'` for Gemini processing.

### chunk_audio.py (NEW)

Split long videos into manageable chunks for processing.

```powershell
# Chunk specific video
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID

# Chunk all pending long videos (>10 minutes)
python src/preprocessing/chunk_audio.py --all

# Custom chunk duration (in seconds)
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID --chunk-duration 600

# Custom database
python src/preprocessing/chunk_audio.py --all --db data/custom.db
```

**Options:**

| Option | Description |
|--------|-------------|
| `--all` | Chunk all pending long videos |
| `--video-id ID` | Chunk specific video |
| `--chunk-duration N` | Chunk duration in seconds (default: 600) |
| `--db PATH` | Custom SQLite database path |

**Chunking Strategy:**
- Default chunk size: 10 minutes (600 seconds)
- Overlap: 10 seconds between chunks
- Output: `data/raw/chunks/{video_id}/chunk_*.wav`
- Creates chunk records in database

### gemini_process.py

Transcribe and translate audio using Gemini 2.5 Pro.

```powershell
# Process all pending videos (state=pending)
python src/preprocessing/gemini_process.py --all

# Process specific video
python src/preprocessing/gemini_process.py --video-id VIDEO_ID

# Process specific chunk (for chunked videos)
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --chunk-id CHUNK_ID

# Dry run (test without API calls)
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --dry-run

# Standalone mode (process audio file directly, no DB)
python src/preprocessing/gemini_process.py --standalone path/to/audio.wav

# Limit number of videos
python src/preprocessing/gemini_process.py --all --limit 3

# Custom database
python src/preprocessing/gemini_process.py --all --db data/custom.db

# Verbose output
python src/preprocessing/gemini_process.py --all --verbose
```

**Options:**

| Option | Description |
|--------|-------------|
| `--all` | Process all pending videos |
| `--video-id ID` | Process specific video |
| `--chunk-id ID` | Process specific chunk (requires --video-id) |
| `--standalone PATH` | Process audio file directly without database |
| `--dry-run` | Test mode without actual API calls |
| `--limit N` | Maximum videos to process |
| `--db PATH` | Custom SQLite database path |
| `--verbose` | Enable debug logging |

| Option | Description |
|--------|-------------|
| `--all` | Process all pending videos |
| `--video-id ID` | Process specific video |
| `--limit N` | Maximum videos to process |
| `--db PATH` | Custom SQLite database path |
| `--verbose` | Enable debug logging |

**Environment Variables:**

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY_1` | Primary Gemini API key |
| `GEMINI_API_KEY_2` | Backup Gemini API key |

---

## Review Commands

### review_app.py (Streamlit)

Launch the Streamlit review interface.

```powershell
# Start review app (default port 8501)
streamlit run src/review_app.py

# Custom port
streamlit run src/review_app.py --server.port 8080

# Allow external access
streamlit run src/review_app.py --server.address 0.0.0.0

# Disable browser auto-open
streamlit run src/review_app.py --server.headless true
```

**Access:** http://localhost:8501

**Features:**

| Feature | Description |
|---------|-------------|
| Dashboard | Statistics and state overview |
| Video selector | Choose video to review |
| Channel filter | Filter videos by channel name |
| Chunk selector | Select specific chunk for chunked videos |
| Audio player | Click to play with auto-pause at segment end |
| Segment editor | Edit transcript/translation |
| Duration badges | Warnings for >25s segments |
| Reviewer assignment | Assign reviewers via dropdown (with add option) |
| Transcript upload/remove | Manage transcript files per video |
| Keyboard shortcuts | Alt+A (approve), Alt+S (save), Alt+R (reject) |
| Split button | Split long segments |
| Reject toggle | Exclude segments |
| Upload tab | Add new videos via file upload |
| Download Audios tab | YouTube ingestion with playlist metadata |

---

## Export Commands

### export_final.py

Export approved segments to HuggingFace dataset format.

```powershell
# Export all approved segments
python src/export_final.py

# Export specific video
python src/export_final.py --video-id VIDEO_ID

# Custom output directory
python src/export_final.py --output data/dataset

# Overwrite existing files
python src/export_final.py --overwrite

# Custom database
python src/export_final.py --db data/custom.db

# Verbose output
python src/export_final.py -v
```

**Options:**

| Option | Description |
|--------|-------------|
| `--video-id ID` | Export specific video only |
| `--output DIR` | Output directory |
| `--overwrite` | Overwrite existing files |
| `--db PATH` | Custom SQLite database path |
| `-v, --verbose` | Enable debug logging |

**Output:**

```
data/export/
├── audio/
│   ├── VIDEO_ID_000001.wav
│   └── ...
└── manifest.tsv
```

---

## Database Commands

### SQLite CLI

```powershell
# Open database
sqlite3 data/lab_data.db

# Common queries
sqlite3 data/lab_data.db "SELECT video_id, processing_state FROM videos;"
sqlite3 data/lab_data.db "SELECT COUNT(*) FROM segments WHERE is_rejected = 0;"
sqlite3 data/lab_data.db "SELECT video_id, COUNT(*) FROM segments GROUP BY video_id;"

# Export to CSV
sqlite3 -header -csv data/lab_data.db "SELECT * FROM segments;" > segments.csv
```

### Python Database Operations

```python
from src.db import get_connection, init_database
from pathlib import Path

# Initialize database
init_database(Path("data/lab_data.db"))

# Query videos
conn = get_connection(Path("data/lab_data.db"))
cursor = conn.cursor()
cursor.execute("SELECT * FROM videos WHERE processing_state = 'processed'")
videos = cursor.fetchall()
conn.close()
```

---

## Database Management

### Backup Database

```powershell
# Manual backup to Google Drive
.\backup_db.ps1

# View recent backups
Get-ChildItem "G:\My Drive\NLP_Backups" | Sort-Object LastWriteTime -Descending | Select-Object -First 10
```

### Sync Database via DVC

```powershell
# Snapshot current database state
python -m dvc add data/lab_data.db
git add data/lab_data.db.dvc
git commit -m "DB snapshot: milestone description"

# Upload to Google Drive
python -m dvc push

# Download latest from Google Drive
python -m dvc pull data/lab_data.db.dvc
```

### Restore from Backup

```powershell
# Restore from latest hourly backup
Copy-Item "G:\My Drive\NLP_Backups\lab_data_latest.db" data/lab_data.db

# Or restore from specific timestamp
Copy-Item "G:\My Drive\NLP_Backups\lab_data_20251206_143022.db" data/lab_data.db

# Or restore from DVC history
git checkout abc123 data/lab_data.db.dvc
python -m dvc checkout data/lab_data.db.dvc
```

See [`docs/09_database_sync.md`](09_database_sync.md) for detailed sync workflow.

---

## DVC Commands (Optional)

### Data Versioning

```powershell
# Track data directory
dvc add data/raw

# Push to remote
dvc push

# Pull from remote
dvc pull

# Check status
dvc status
```

### Run Pipeline

```powershell
# Run export stage
dvc repro export_final
```

---

## Backup Commands

### Manual Backup

```powershell
# Run backup script
powershell -File backup_db.ps1

# Or directly copy
Copy-Item data/lab_data.db "G:\My Drive\NLP_Backups\lab_data_$(Get-Date -Format 'yyyy-MM-dd').db"
```

### Scheduled Task

```powershell
# Check task status
Get-ScheduledTask -TaskName "NLP_DB_Hourly_Backup"

# Run task manually
Start-ScheduledTask -TaskName "NLP_DB_Hourly_Backup"

# Disable task
Disable-ScheduledTask -TaskName "NLP_DB_Hourly_Backup"

# Remove task
Unregister-ScheduledTask -TaskName "NLP_DB_Hourly_Backup"
```

---

## Tailscale Commands

### Setup

```powershell
# Login
tailscale up

# Check status
tailscale status

# Get IP
tailscale ip
```

### Serve Configuration

```powershell
# Expose Streamlit
tailscale serve https / http://127.0.0.1:8501

# Check serve status
tailscale serve status

# Reset serve
tailscale serve reset
```

---

## Common Workflows

### Process New Video (End-to-End)

```powershell
# 1. Ingest
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 2. (Optional) Chunk if long video (>10 min)
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID

# 3. (Optional) Denoise
python src/preprocessing/denoise_audio.py --video-id VIDEO_ID

# 4. Process with Gemini
python src/preprocessing/gemini_process.py --video-id VIDEO_ID

# 5. Review (in browser)
streamlit run src/review_app.py

# 6. Export
python src/export_final.py --video-id VIDEO_ID
```

### Batch Processing

```powershell
# Ingest multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# Chunk long videos
python src/preprocessing/chunk_audio.py --all

# (Optional) Denoise all pending
python src/preprocessing/denoise_audio.py --all

# Process all pending
python src/preprocessing/gemini_process.py --all

# Export all approved
python src/export_final.py
```

### Check Pipeline Status

```powershell
# Count by state
sqlite3 data/lab_data.db "
SELECT processing_state, COUNT(*) 
FROM videos 
GROUP BY processing_state;
"

# Count approved segments
sqlite3 data/lab_data.db "
SELECT COUNT(*) as approved 
FROM segments 
WHERE is_rejected = 0;
"
```

---

## Next Steps

- 📖 [Complete Workflow Guide](08_complete_workflow.md) - Detailed workflow examples
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer documentation
- ⚠️ [Known Caveats](06_known_caveats.md) - Limitations

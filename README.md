# Vietnamese-English Code-Switching Speech Translation

End-to-End Speech Translation pipeline for Vietnamese-English Code-Switching data. Downloads audio from **YouTube**, processes with **Gemini 2.5 Flash** for transcription + translation, and includes human-in-the-loop review via **NiceGUI**.

---

## Features

- ✅ **YouTube Audio Ingestion**: Download and chunk videos as 16kHz mono WAV
- ✅ **DeepFilterNet Denoising**: Optional background noise removal
- ✅ **Gemini 2.5 Flash Processing**: Multimodal transcription + translation with min:sec.ms timestamps
- ✅ **NiceGUI Review App**: Event-driven web UI with keyboard shortcuts, audio player, inline editing
- ✅ **SQLite Database**: Lightweight storage with `review_state` workflow tracking
- ✅ **Tailscale Remote Access**: Secure remote access to review interface
- ✅ **DVC Integration**: Google Drive versioning for data artifacts

---

## Quick Start (5 Minutes)

### 1. Setup

```powershell
# Clone repository
git clone <repo-url>
cd final_nlp

# Run setup script (creates venv, installs deps, initializes DB)
.\setup.ps1

# Activate environment
.\.venv\Scripts\Activate.ps1
```

**Prerequisites:** Python 3.10+, FFmpeg, Gemini API key in `.env`

### 2. Process a YouTube Video

```powershell
# Download audio
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Chunk into 6-minute segments
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID

# Optional: Denoise with DeepFilterNet
python src/preprocessing/denoise_audio.py --all

# Transcribe and translate
python src/preprocessing/gemini_process.py --video-id VIDEO_ID
```

### 3. Review in NiceGUI

```powershell
# Start web interface
python src/gui_app.py

# Access at http://localhost:8501
# Features: 
# - Keyboard shortcuts (Ctrl+S save, Ctrl+Enter approve, Ctrl+R reject, Ctrl+Space play)
# - Tab-based navigation (Dashboard, Review, Upload, Refinement, Download)
# - Audio player with timestamp control
# - Inline editing for transcripts/translations
# - Bulk operations (approve all, reset all)
```

### 4. Export Dataset

```powershell
# Export approved segments to HuggingFace format
python src/export_final.py
# Output: data/export/<timestamp>/ with WAV files + manifest.tsv
```

---

## Documentation

| File | Purpose |
|------|---------|
| **[WORKFLOW.md](docs/WORKFLOW.md)** | Complete workflow guide, commands, troubleshooting |
| **[DEVELOPER.md](docs/DEVELOPER.md)** | Architecture, API reference, database schema, limitations |
| [CHANGELOG.md](CHANGELOG.md) | Project updates and migration notes |

---

## Project Structure

```
final_nlp/
├── src/
│   ├── ingest_youtube.py         # Download YouTube audio
│   ├── preprocessing/
│   │   ├── chunk_audio.py        # Split audio into 6-min chunks
│   │   ├── denoise_audio.py      # DeepFilterNet noise removal
│   │   └── gemini_process.py     # Gemini transcription/translation
│   ├── gui_app.py                # NiceGUI review interface (SPA)
│   ├── export_final.py           # Export final dataset
│   └── db.py                     # SQLite utilities
├── data/
│   ├── lab_data.db               # SQLite database (WAL mode)
│   ├── raw/audio/                # Downloaded YouTube audio
│   ├── raw/chunks/               # Chunked audio segments
│   └── export/                   # Exported datasets
├── docs/                         # Documentation
├── archive/                      # Archived implementations
│   ├── streamlit/                # Original Streamlit implementation
│   └── nicegui/                  # Experimental NiceGUI versions
├── init_scripts/                 # SQL schema + migrations
└── setup.ps1                     # Automated setup script
```

---

## Tech Stack

- **Audio Processing**: FFmpeg, pydub, DeepFilterNet
- **AI**: Google Gemini 2.5 Flash (multimodal API)
- **Database**: SQLite with WAL mode
- **UI**: NiceGUI (event-driven SPA)
- **Data Versioning**: DVC + Google Drive remote
- **Networking**: Tailscale for remote access

---

## Current Status

**Model**: `gemini-2.5-flash-preview-09-2025`  
**Timestamp Format**: `min:sec.ms` (e.g., `0:04.54`, `1:23.45`)  
**Database Schema**: Migrated with `review_state` column (`pending`/`reviewed`/`approved`/`rejected`)  
**Performance**: Cached queries (10-60s TTL), pagination (25 segments/page), event-driven UI  
**UI**: NiceGUI SPA with keyboard shortcuts, tab navigation, inline editing

See [CHANGELOG.md](CHANGELOG.md) for recent updates.

**Note:** Denoising is optional and keeps state as `pending`. See [Complete Workflow Guide](docs/08_complete_workflow.md) for details.

---

## Project Structure

```
final_nlp/
├── data/
│   ├── lab_data.db             # SQLite database
│   ├── raw/audio/              # Raw audio from YouTube
│   ├── raw/chunks/             # Chunked audio for long videos
│   ├── denoised/               # Denoised audio files
│   ├── segments/               # Processed segment audio
│   └── export/                 # Final dataset output
├── src/
│   ├── db.py                   # SQLite utilities
│   ├── ingest_youtube.py       # YouTube ingestion
│   ├── gui_app.py              # NiceGUI review app (SPA)
│   ├── export_final.py         # Dataset export
│   └── preprocessing/
│       ├── chunk_audio.py      # Audio chunking for long videos
│       ├── gemini_process.py   # Transcription + translation
│       └── denoise_audio.py    # DeepFilterNet denoising
├── archive/
│   ├── streamlit/              # Deprecated Streamlit implementation
│   └── nicegui/                # Experimental NiceGUI versions
├── init_scripts/
│   └── sqlite_schema.sql       # Database schema
├── docs/                       # Documentation
├── setup.ps1                   # Setup script
├── docker-compose.yml          # Optional Docker services
└── requirements.txt            # Python dependencies
```

---

## Audio Specifications

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16 kHz |
| Channels | Mono |
| Format | WAV (PCM 16-bit) |
| Video Duration | 2-60 minutes (input) |
| Segment Duration | 2-25 seconds (output) |
| Chunking | 10-min chunks, 10s overlap |

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| NiceGUI Review App | 8501 | http://localhost:8501 |

---

## Database Synchronization (Team Collaboration)

For team collaboration between development and lab machines, we use **DVC (Data Version Control)** with Google Drive as the remote storage.

### Quick Sync Commands

```powershell
# Pull latest database from team
python -m dvc pull

# Push local database updates to team
python -m dvc add data/lab_data.db
git add data/lab_data.db.dvc data/.gitignore
git commit -m "Update database with new annotations"
python -m dvc push
git push
```

### Workflow Summary

1. **Dev Machine**: Ingest/process videos → commit → push via DVC
2. **Lab Machine**: Pull via DVC → run NiceGUI for annotation → push updates back
3. **Automated Backups**: Hourly snapshots to `data/db_sync/backups/`

📖 **Full sync guide**: [docs/09_database_sync.md](docs/09_database_sync.md)

---

## Documentation

📚 **[Start Here: DOCS_INDEX.md](DOCS_INDEX.md)** - Documentation navigation hub

### Quick Links

| Document | Audience | Purpose |
|----------|----------|---------|
| **[USER_GUIDE.md](docs/USER_GUIDE.md)** | End-users, reviewers | Complete UI tutorial, keyboard shortcuts, workflow |
| **[DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** | Developers, MLOps | Architecture, API reference, development workflow |
| **[WORKFLOW.md](docs/WORKFLOW.md)** | Data engineers | Pipeline stages, CLI tools, data formats |

**Version**: 2.0 (Tab-based UI, consolidated documentation)  
**Last Updated**: 2025-01-15

---

## License

MIT License

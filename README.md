# Vietnamese-English Code-Switching Speech Translation

End-to-End Speech Translation pipeline for Vietnamese-English Code-Switching data. Ingests audio from **YouTube videos**, processes with **Gemini 2.5 Pro** for transcription + translation, and includes human-in-the-loop review via **Streamlit**.

## Features

- **YouTube Audio Pipeline**: Download and process YouTube videos as 16kHz mono WAV
- **DeepFilterNet Denoising**: Background noise removal for cleaner audio
- **Gemini 2.5 Pro Processing**: Intelligent chunking with 10-min segments, 10s overlap
- **Streamlit Review App**: Web-based review with waveform visualization, segment editing
- **SQLite Database**: Lightweight, portable data storage with WAL mode
- **Tailscale Remote Access**: Secure remote access to review app
- **DVC Integration**: Google Drive remote for data versioning

---

## Quick Start

### 1. Setup Environment

```powershell
# Clone and setup
git clone <repo-url>
cd final_nlp

# Run setup script (creates venv, installs deps, initializes DB)
.\setup.ps1
```

### 2. Ingest YouTube Video

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Download and ingest a video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### 3. Process Audio

```powershell
# Denoise audio (optional but recommended)
python src/preprocessing/denoise_audio.py --all

# Transcribe and translate with Gemini
python src/preprocessing/gemini_process.py --all
```

### 4. Review Segments

```powershell
# Start the Streamlit review app
streamlit run src/review_app.py

# Access at http://localhost:8501
```

### 5. Export Dataset

```powershell
# Export approved segments to HuggingFace format
python src/export_final.py
```

📖 **Full setup guide**: [docs/01_getting_started.md](docs/01_getting_started.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [01_getting_started.md](docs/01_getting_started.md) | Setup guide, credentials, quick start |
| [02_architecture.md](docs/02_architecture.md) | Pipeline workflow, database schema |
| [03_command_reference.md](docs/03_command_reference.md) | All commands and options |
| [04_troubleshooting.md](docs/04_troubleshooting.md) | Common issues and solutions |
| [05_api_reference.md](docs/05_api_reference.md) | Developer API documentation |
| [06_known_caveats.md](docs/06_known_caveats.md) | Known issues and limitations |
| [CHANGELOG.md](CHANGELOG.md) | Project history and updates |

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                   │
│                                                                           │
│  YouTube ──► Denoise ──► Gemini Process ──► Streamlit ──► Export Dataset │
│  Ingest     (DeepFilterNet)  (Transcribe+    Review      (2-25s WAV +    │
│                               Translate)                  manifest.tsv)   │
│                                                                           │
│  ingested ───► denoised ─────► processed ───► reviewed ───► exported     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
final_nlp/
├── data/
│   ├── lab_data.db             # SQLite database
│   ├── raw/audio/              # Raw audio from YouTube
│   ├── denoised/               # Denoised audio files
│   ├── segments/               # Processed segment audio
│   └── export/                 # Final dataset output
├── src/
│   ├── db.py                   # SQLite utilities
│   ├── ingest_youtube.py       # YouTube ingestion
│   ├── review_app.py           # Streamlit review app
│   ├── export_final.py         # Dataset export
│   └── preprocessing/
│       ├── gemini_process.py   # Transcription + translation
│       └── denoise_audio.py    # DeepFilterNet denoising
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
| Streamlit | 8501 | http://localhost:8501 |
| Audio Server | 8081 | http://localhost:8081 |

---

## License

MIT License

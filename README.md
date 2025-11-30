# Vietnamese-English Code-Switching Speech Translation

End-to-End Speech Translation pipeline for Vietnamese-English Code-Switching data. Ingests audio from **YouTube videos with transcripts**, processes with Gemini for transcription + translation, and includes human-in-the-loop review via Label Studio.

## Features

- **YouTube-Only Pipeline**: Mandatory transcripts for quality control
- **Gemini Processing**: Single-pass transcription + translation with structured output
- **Human-in-the-Loop**: 3-stage Label Studio review
- **Adaptive Chunking**: Auto-splits long audio with overlap deduplication
- **DVC Integration**: Google Drive remote for data versioning
- **PostgreSQL Backend**: Revision tracking with audit logs

---

## Quick Start (5 Minutes)

### 1. Start Services

```powershell
git clone <repo-url>
cd final_nlp
docker compose up -d
```

### 2. Setup Label Studio

1. Open http://localhost:8085 and **sign up**
2. Enable legacy tokens:
   ```powershell
   docker exec -it factory_ledger psql -U admin -d label_studio -c "UPDATE django_site SET domain='localhost:8085', name='localhost:8085' WHERE id=1;"
   ```
3. Get API token: User icon → **Account & Settings** → **Access Token**
4. Update `.env` with your token

### 3. Ingest & Process

```powershell
# Ingest YouTube video
docker compose run --rm ingestion python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Run Gemini transcription + translation
docker compose run --rm ingestion python src/preprocessing/gemini_process.py --batch

# Push to Label Studio for review
docker compose run --rm -e AUDIO_PUBLIC_URL=http://localhost:8081 ingestion python src/label_studio_sync.py push --task-type translation_review
```

📖 **Full setup guide**: [docs/01_getting_started.md](docs/01_getting_started.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [01_getting_started.md](docs/01_getting_started.md) | Setup guide, credentials, quick start |
| [02_architecture.md](docs/02_architecture.md) | Pipeline workflow, database schema, data specs |
| [03_command_reference.md](docs/03_command_reference.md) | All commands and options |
| [04_troubleshooting.md](docs/04_troubleshooting.md) | Common issues and solutions |
| [05_api_reference.md](docs/05_api_reference.md) | Developer API documentation |
| [CHANGELOG.md](CHANGELOG.md) | Project history and updates |

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                  │
│                                                                          │
│  YouTube  ──►  Gemini Processing  ──►  Label Studio  ──►  Training      │
│  Ingest       (Transcribe+Translate)    Review           Export          │
│                                                                          │
│  RAW ─────────► TRANSLATED ─────────► VERIFIED ─────────► FINAL         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
final_nlp/
├── data/
│   ├── raw/                    # DVC-tracked (audio + transcripts)
│   ├── segments/               # Segmented audio chunks
│   └── db_sync/                # Database backups
├── src/
│   ├── ingest_youtube.py       # YouTube ingestion
│   ├── label_studio_sync.py    # Label Studio integration
│   └── preprocessing/
│       ├── gemini_process.py   # Transcription + translation
│       ├── gemini_repair_translation.py
│       ├── whisperx_align.py   # Word-level alignment
│       ├── segment_audio.py    # Audio segmentation
│       └── denoise_audio.py    # Noise removal
├── init_scripts/               # Database schema
├── label_studio_templates/     # Annotation templates
├── docs/                       # Documentation
└── docker-compose.yml
```

---

## Audio Specifications

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16 kHz |
| Channels | Mono |
| Format | WAV (PCM 16-bit) |
| Video Duration | 2-60 minutes |
| Segment Duration | 10-30 seconds |

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| PostgreSQL | 5432 | `localhost:5432` |
| Label Studio | 8085 | http://localhost:8085 |
| Audio Server | 8081 | http://localhost:8081 |

---

## License

MIT License

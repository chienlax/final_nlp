# 01. Project Setup

## Overview

This document outlines the setup process for the Vietnamese-English Code-Switching Speech Translation project. The project uses a **Docker-based** architecture for data ingestion, preprocessing, and annotation.

**Key Features:**
- YouTube-only pipeline with mandatory transcripts
- 3-stage human review: Transcript → Segment → Translation
- WhisperX alignment, Gemini translation, DeepFilterNet denoising
- PostgreSQL backend for both `data_factory` and `label_studio`
- DVC with Google Drive for large file synchronization

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose)
- **Python 3.10+** (for local development)
- **NVIDIA GPU** with CUDA 12.4+ (for preprocessing)
- **Git** and **DVC**
- **DVC credentials** (Google Drive service account)

## Installation

### 1. Environment Setup

1. **Clone the repository**:
   ```bash
   git clone <repo_url>
   cd final_nlp
   ```

2. **Create a Local Virtual Environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate  # Windows
   # source .venv/bin/activate  # Linux/Mac
   pip install -r requirements.txt
   ```

3. **Copy environment configuration**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Set up DVC credentials**:
   ```powershell
   mkdir -Force "$HOME\.cache\pydrive2fs"
   Copy-Item "path\to\shared\credentials.json" "$HOME\.cache\pydrive2fs\credentials.json"
   ```

### 2. Infrastructure (Docker)

1. **Start Core Services**:
   ```bash
   docker-compose up -d postgres label_studio audio_server
   ```
   
   Services:
   - **`postgres`**: PostgreSQL on port `5432`
   - **`label_studio`**: Annotation UI on port `8085`
   - **`audio_server`**: nginx audio server on port `8081`

2. **Verify Status**:
   ```bash
   docker-compose ps
   ```

3. **Database Initialization**:
   Schemas are applied automatically on first start:
   - `00_create_label_studio_db.sql` - Creates Label Studio database
   - `01_schema.sql` - Current schema with segments and translations

### 3. GPU Preprocessing Container

For WhisperX alignment and DeepFilterNet denoising:

```bash
# Build preprocessing container
docker build -f Dockerfile.preprocess -t nlp-preprocess .

# Run with GPU
docker run --gpus all -v $(pwd):/app nlp-preprocess python src/preprocessing/whisperx_align.py --batch
```

### 4. Label Studio Setup

1. **Access Label Studio**: http://localhost:8085
2. **Create admin account** on first launch
3. **Get API key**: Settings → Account & Settings → Access Token
4. **Update `.env`** with `LABEL_STUDIO_API_KEY=your_key`
5. **Create 3 projects** using templates from `label_studio_templates/`:
   - Transcript Correction (Round 1)
   - Segment Review (Round 2)
   - Translation Review (Round 3)

See [07_label_studio.md](07_label_studio.md) for detailed setup.

### 5. Data Management (DVC)

```bash
# Pull existing data
dvc pull

# After adding new data
dvc add data/raw
git add data/raw.dvc
git commit -m "Add new data"
dvc push
```

## Project Structure

```
final_nlp/
├── data/
│   ├── raw/                    # DVC-tracked raw data
│   │   ├── audio/              # Full video audio (16kHz mono WAV)
│   │   ├── text/               # Transcripts (JSON with timestamps)
│   │   └── metadata.jsonl
│   ├── segments/               # Segmented audio chunks
│   │   └── {sample_id}/
│   └── teencode.txt            # Vietnamese teencode dictionary
├── src/
│   ├── ingest_youtube.py       # YouTube ingestion
│   ├── label_studio_sync.py    # Label Studio integration
│   ├── preprocessing/          # Audio processing pipeline
│   │   ├── whisperx_align.py   # WhisperX forced alignment
│   │   ├── segment_audio.py    # Audio segmentation (10-30s)
│   │   ├── translate.py        # Gemini translation
│   │   └── denoise_audio.py    # DeepFilterNet denoising
│   └── utils/
│       ├── data_utils.py       # Database utilities
│       ├── video_downloading_utils.py
│       ├── transcript_downloading_utils.py
│       └── text_utils.py
├── init_scripts/
│   ├── 00_create_label_studio_db.sql
│   └── 01_schema.sql           # Current schema
├── label_studio_templates/
│   ├── transcript_correction.xml   # Round 1
│   ├── segment_review.xml          # Round 2
│   └── translation_review.xml      # Round 3
├── Dockerfile.preprocess       # GPU preprocessing container
├── docker-compose.yml
└── requirements.txt
```

## Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Database |
| Label Studio | 8085 | Annotation UI |
| Audio Server | 8081 | Serve audio files |

## Database Access

```bash
# Connect to database
docker exec -it postgres_nlp psql -U admin -d data_factory

# View pipeline stats
SELECT * FROM v_pipeline_stats;

# View sample overview
SELECT * FROM v_sample_overview LIMIT 10;
```

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql://admin:secret_password@localhost:5432/data_factory

# Label Studio
LABEL_STUDIO_URL=http://localhost:8085
LABEL_STUDIO_API_KEY=your_api_key

# Gemini API (multiple keys for rotation)
GEMINI_API_KEY_1=your_first_key
GEMINI_API_KEY_2=your_second_key
GEMINI_API_KEY_3=your_third_key

# Audio Server
AUDIO_SERVER_URL=http://localhost:8081
```

## Quick Start Commands

```bash
# 1. Start services
docker-compose up -d postgres label_studio audio_server

# 2. Ingest YouTube videos
python src/ingest_youtube.py https://www.youtube.com/@SomeChannel

# 3. Run preprocessing (requires GPU)
docker run --gpus all -v $(pwd):/app nlp-preprocess \
    python src/preprocessing/whisperx_align.py --batch --limit 10

# 4. Push to Label Studio for review
python src/label_studio_sync.py push --task-type transcript_correction
```

## Troubleshooting

### PowerShell: Running SQL scripts manually

```powershell
Get-Content init_scripts\01_schema.sql | docker exec -i postgres_nlp psql -U admin -d data_factory
```

### DVC pull fails

```powershell
Test-Path "$HOME\.cache\pydrive2fs\credentials.json"
```

### GPU not detected

```bash
docker run --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## Related Documentation

- [04_workflow.md](04_workflow.md) - Pipeline workflow
- [06_database_design.md](06_database_design.md) - Schema reference
- [07_label_studio.md](07_label_studio.md) - Annotation setup

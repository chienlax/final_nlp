# Vietnamese-English Code-Switching Speech Translation

An End-to-End (E2E) Speech Translation pipeline for Vietnamese-English Code-Switching (CS) data. The system ingests code-switched audio from **YouTube videos with transcripts**, processes them through a streamlined pipeline with human-in-the-loop review, and produces aligned transcripts with translations ready for training.

## Features

- **YouTube-Only Pipeline**: Focus on audio-first workflow with mandatory transcripts
- **Human-in-the-Loop**: 3-stage Label Studio review (transcript → segment → translation)
- **WhisperX Alignment**: Forced alignment with Vietnamese language model for word-level timestamps
- **Segment-Based Processing**: 10-30s audio chunks optimized for training
- **Gemini Translation**: Multi-key rotation strategy with rate limit handling
- **DeepFilterNet Denoising**: Background noise removal for clean training data
- **Data Versioning**: DVC integration with Google Drive remote storage
- **PostgreSQL Backend**: Multi-table schema with revision tracking and audit logs

## Quick Start

### 1. Prerequisites

- Python 3.10+
- PostgreSQL 15+
- ffmpeg
- DVC

### 2. Setup

```bash
# Clone and setup virtual environment
git clone <repo-url>
cd final_nlp
python -m venv .venv
.venv\Scripts\activate  # Windows
# or: source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Start database
docker-compose up -d postgres

# Initialize DVC
dvc pull
```

### 3. Ingest Data

```bash
# YouTube video (requires transcript)
python src/ingest_youtube_v3.py https://www.youtube.com/@SomeChannel

# Re-ingest existing metadata (no download)
python src/ingest_youtube_v3.py --skip-download

# Dry run (no database changes)
python src/ingest_youtube_v3.py --skip-download --dry-run

# Version new data
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
│   │   └── metadata.jsonl      # Ingestion metadata
│   ├── segments/               # Segmented audio chunks
│   │   └── {sample_id}/        # Per-sample segment folder
│   │       ├── 0000.wav
│   │       ├── 0001.wav
│   │       └── ...
│   └── teencode.txt            # Vietnamese teencode dictionary
├── src/
│   ├── ingest_youtube_v3.py    # YouTube ingestion (v3, transcript required)
│   ├── label_studio_sync.py    # Label Studio integration
│   ├── preprocessing/          # Audio processing pipeline
│   │   ├── whisperx_align.py   # WhisperX forced alignment
│   │   ├── segment_audio.py    # Audio segmentation (10-30s)
│   │   ├── translate.py        # Gemini translation with key rotation
│   │   └── denoise_audio.py    # DeepFilterNet noise removal
│   └── utils/
│       ├── data_utils_v3.py    # Database utilities (v3 schema)
│       ├── video_downloading_utils.py
│       ├── transcript_downloading_utils.py
│       └── text_utils.py
├── init_scripts/
│   ├── 01_schema.sql           # Legacy schema (v1)
│   ├── 02_schema_v2.sql        # Legacy schema (v2)
│   └── 03_schema_v3.sql        # Current schema (v3)
├── label_studio_templates/
│   ├── transcript_correction.xml   # Round 1: Transcript review
│   ├── segment_review.xml          # Round 2: Segment verification
│   └── translation_review.xml      # Round 3: Translation review
├── docs/                       # Documentation
├── Dockerfile.preprocess       # GPU preprocessing container
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Documentation

| Document | Description |
|----------|-------------|
| [01_setup_project.md](docs/01_setup_project.md) | Environment setup, Docker, DVC configuration |
| [02_project_progress.md](docs/02_project_progress.md) | Development progress and milestones |
| [03_data_requirements.md](docs/03_data_requirements.md) | Audio/text specifications, quality criteria |
| [04_workflow.md](docs/04_workflow.md) | End-to-end pipeline workflow (legacy) |
| [05_scripts_details.md](docs/05_scripts_details.md) | Script reference with parameters and examples |
| [06_database_design.md](docs/06_database_design.md) | Database schema, tables, indexes, functions |
| [09_simplified_workflow_v3.md](docs/09_simplified_workflow_v3.md) | **Current** simplified pipeline workflow |

## Audio Specifications

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16 kHz |
| Channels | Mono |
| Format | WAV (PCM 16-bit) |
| Video Duration | 2-60 minutes per video |
| Segment Duration | 10-30 seconds per segment |

## Pipeline Overview (v3)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     YOUTUBE PIPELINE (v3)                               │
│                                                                         │
│  RAW → TRANSCRIPT_REVIEW → TRANSCRIPT_VERIFIED → ALIGNED → SEGMENTED   │
│      → SEGMENT_REVIEW → SEGMENT_VERIFIED → TRANSLATED                  │
│      → TRANSLATION_REVIEW → DENOISED → FINAL                           │
└─────────────────────────────────────────────────────────────────────────┘

Human Review Stages:
  ├── Round 1: TRANSCRIPT_REVIEW (fix transcript errors)
  ├── Round 2: SEGMENT_REVIEW (verify segment boundaries)
  └── Round 3: TRANSLATION_REVIEW (verify translations)
```

### Processing Scripts

```bash
# Build GPU preprocessing container
docker build -f Dockerfile.preprocess -t nlp-preprocess .

# Run with GPU
docker run --gpus all -v $(pwd):/app nlp-preprocess

# Individual preprocessing steps
python src/preprocessing/whisperx_align.py --batch --limit 10
python src/preprocessing/segment_audio.py --batch --limit 10
python src/preprocessing/translate.py --batch --limit 10
python src/preprocessing/denoise_audio.py --batch --limit 10
```

## Development

```bash
# Run tests (when available)
pytest tests/

# Check for syntax errors
python -m py_compile src/ingest_youtube.py

# Database access
docker exec -it postgres_nlp psql -U admin -d data_factory
```

## License

MIT License

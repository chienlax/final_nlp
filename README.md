# Vietnamese-English Code-Switching Speech Translation

An End-to-End (E2E) Speech Translation pipeline for Vietnamese-English Code-Switching (CS) data. The system ingests code-switched audio from YouTube and text from Substack blogs, processes them through dual pipelines, and produces aligned transcripts with translations.

## Features

- **Dual-Pipeline Architecture**: Supports both audio-first (YouTube) and text-first (Substack) workflows
- **Automated Ingestion**: Download audio, transcripts, and articles with metadata
- **Data Versioning**: DVC integration with Google Drive remote storage
- **PostgreSQL Backend**: Multi-table schema with revision tracking and audit logs
- **Label Studio Ready**: Designed for integration with annotation workflows

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
# YouTube video (audio + transcript)
python src/ingest_youtube.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --dry-run

# Substack article (text)
python src/ingest_substack.py --url "https://blog.substack.com/p/article-slug" --dry-run

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
│   ├── raw/                    # DVC-tracked data
│   │   ├── audio/              # 16kHz mono WAV files
│   │   ├── text/               # Transcripts (JSON) and articles
│   │   └── metadata.jsonl      # Ingestion metadata
│   └── teencode.txt            # Vietnamese teencode dictionary
├── src/
│   ├── ingest_youtube.py       # YouTube ingestion orchestrator
│   ├── ingest_substack.py      # Substack ingestion orchestrator
│   ├── label_studio_sync.py    # Label Studio integration
│   └── utils/
│       ├── data_utils.py       # Database utilities
│       ├── video_downloading_utils.py
│       ├── transcript_downloading_utils.py
│       ├── substack_utils.py
│       └── text_utils.py
├── init_scripts/
│   ├── 01_schema.sql           # Legacy schema (v1)
│   └── 02_schema_v2.sql        # Current schema (v2)
├── docs/                       # Documentation
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
| [04_workflow.md](docs/04_workflow.md) | End-to-end pipeline workflow |
| [05_scripts_details.md](docs/05_scripts_details.md) | Script reference with parameters and examples |
| [06_database_design.md](docs/06_database_design.md) | Database schema, tables, indexes, functions |

## Audio Specifications

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16 kHz |
| Channels | Mono |
| Format | WAV (PCM 16-bit) |
| Duration | 2-60 minutes per video |

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     AUDIO-FIRST PIPELINE                        │
│  YouTube → Download → Extract Audio → Download Transcript →     │
│  MFA Align → Segment → Enhance → Translate → Review             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     TEXT-FIRST PIPELINE                         │
│  Substack → Download Article → Normalize → Detect CS Chunks →   │
│  TTS Generate → Translate → Review                              │
└─────────────────────────────────────────────────────────────────┘
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

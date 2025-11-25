# 02. Project Progress & Architecture Status

**Update:** November 25, 2025

## 1. Infrastructure & Environment

### Containerization
We have transitioned to a Docker-based workflow to ensure consistent environments for data ingestion and database management.
- **`docker-compose.yml`**: Orchestrates the services (PostgreSQL + ingestion container).
- **`Dockerfile.ingest`**: Defines the environment for data ingestion tasks.
    - Includes: `ffmpeg`, `yt-dlp`, `youtube-transcript-api`, `psycopg2-binary`, `dvc[gdrive]`.

### Database Migration
- **Previous:** SQLite (`dataset/db/cs_corpus.db`).
- **Current:** PostgreSQL.
    - Data persistence is handled via the `database_data/` volume (ignored in git).
    - Initialization scripts are located in `init_scripts/`.
    - **Schema**: The `dataset_ledger` table tracks samples with fields for metadata (`source_metadata`, `acoustic_meta`, `linguistic_meta`), transcripts (`transcript_raw`, `transcript_corrected`), translations, and processing states (`RAW`, `DENOISED`, `SEGMENTED`, `REVIEWED`).

## 2. Data Management (DVC)

Data Version Control (DVC) has been integrated to manage large raw data files.
- **`data/raw.dvc`**: Tracks the raw data directory.
- **`data/raw/`**: Local storage for raw audio/text data (managed by DVC).
    - `data/raw/audio/` - 16kHz mono WAV files.
    - `data/raw/text/` - Transcript text files.
    - `data/raw/metadata.jsonl` - Batch metadata file.

## 3. Codebase Status

### Ingestion Pipeline (`src/`)
- **`ingest_youtube.py`**: Orchestrator script for the full YouTube ingestion workflow.
    - Downloads audio → Downloads transcripts → Calculates CS ratio → Inserts into database.
    - Usage: `python src/ingest_youtube.py <url1> <url2> ...`
    - Supports `--skip-download` flag to re-ingest existing metadata.

### Utilities (`src/utils/`)
- **`video_downloading_utils.py`**:
    - Downloads YouTube audio as **16kHz mono WAV** files.
    - Filters videos by duration (2-60 minutes).
    - Outputs metadata to `data/raw/metadata.jsonl` (JSONL format).
    - Uses `pathlib` for path handling.

- **`transcript_downloading_utils.py`**:
    - Downloads transcripts with **subtitle type detection** (Manual vs Auto-generated).
    - Prioritizes manual transcripts over auto-generated.
    - Supports English and Vietnamese transcripts.
    - Outputs to `data/raw/text/{video_id}_transcript.txt`.

- **`data_utils.py`**:
    - **PostgreSQL connector**: `get_pg_connection()` reads from `DATABASE_URL` env var.
    - **Database operations**: `insert_raw_sample()`, `sample_exists()`.
    - **Linguistic analysis**: `calculate_cs_ratio()` for Code-Switching ratio calculation.

### Setup
- **`setup_project.py`**: Script to initialize the local project directory structure.
- **`requirements.txt`**: Python dependencies (includes `yt-dlp`, `youtube-transcript-api`, `psycopg2-binary`).

## 4. Data Flow Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                   YouTube Ingestion Pipeline                  │
├───────────────────────────────────────────────────────────────┤
│  INPUT: YouTube URL(s)                                        │
│           ↓                                                   │
│  video_downloading_utils.py                                   │
│     - Download audio → data/raw/audio/{video_id}.wav (16kHz)  │
│     - Extract metadata → data/raw/metadata.jsonl              │
│           ↓                                                   │
│  transcript_downloading_utils.py                              │
│     - Fetch transcript → data/raw/text/{video_id}.txt         │
│     - Detect subtitle type (Manual/Auto-generated)            │
│           ↓                                                   │
│  data_utils.py                                                │
│     - Calculate CS ratio                                      │
│     - INSERT into dataset_ledger (processing_state='RAW')     │
│           ↓                                                   │
│  DVC: dvc add data/raw && dvc push                            │
└───────────────────────────────────────────────────────────────┘
```

## 5. Next Steps
- [ ] Test the ingestion pipeline end-to-end with sample YouTube channels.
- [ ] Verify DVC remote storage configuration (Google Drive).
- [ ] Implement audio denoising stage (`DENOISED` processing state).
- [ ] Add segmentation logic for long audio files (`SEGMENTED` state).

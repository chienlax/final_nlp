# 01. Project Setup

## Overview
This document outlines the setup process for the Vietnamese-English Code-Switching Speech Translation project. The project uses a **Docker-based** architecture for data ingestion, storage, and annotation.

## Prerequisites
- **Docker Desktop** (or Docker Engine + Compose)
- **Python 3.11+** (for local development and IDE support)
- **Git**

## Installation

### 1. Environment Setup

1.  **Clone the repository**:
    ```bash
    git clone <repo_url>
    cd final_nlp
    ```

2.  **Create a Local Virtual Environment** (Optional but recommended for IDEs):
    ```bash
    python -m venv .venv
    .\.venv\Scripts\Activate
    pip install -r requirements.txt
    ```

3.  **Copy environment configuration**:
    ```bash
    cp .env.example .env
    # Edit .env with your settings (Label Studio API key, etc.)
    ```

### 2. Infrastructure (Docker)

We use Docker Compose to manage PostgreSQL, Label Studio, and supporting services.

1.  **Start the Services**:
    ```bash
    docker-compose up -d --build
    ```
    
    Services started:
    - **`postgres`**: PostgreSQL database on port `5432`
    - **`label_studio`**: Annotation interface on port `8080`
    - **`audio_server`**: nginx audio file server on port `8081`
    - **`sync_service`**: DVC sync daemon (5-minute interval)
    - **`ingestion`**: Python environment for data processing

2.  **Verify Status**:
    ```bash
    docker-compose ps
    ```

3.  **Apply Database Migrations**:
    ```bash
    # Schema V2 (core tables) - runs automatically on first start
    # Schema V3 (Label Studio additions) - run manually:
    docker exec -i factory_ledger psql -U admin -d data_factory < init_scripts/03_schema_label_studio_v1.sql
    ```

### 3. Label Studio Setup

1.  **Access Label Studio**: http://localhost:8080
2.  **Create admin account** on first launch
3.  **Get API key**: Settings → Account & Settings → Access Token
4.  **Update `.env`** with `LABEL_STUDIO_API_KEY=your_key`
5.  **Create projects** using templates from `label_studio_templates/`

See [07_label_studio.md](07_label_studio.md) for detailed setup instructions.

### 4. Data Management (DVC)

Large files (audio/raw text) are managed via DVC with Google Drive as remote.

1.  **Pull Data**:
    ```bash
    dvc pull
    ```

2.  **Automatic Sync**: The `sync_service` container pulls every 5 minutes.

## Project Structure

```text
project_root/
│
├── data/                   # DVC-managed data storage
│   ├── raw/                # Raw downloads (audio, text)
│   ├── reviewed/           # Human-reviewed exports
│   └── raw.dvc             # DVC tracking file
│
├── database_data/          # PostgreSQL data volume (Do not commit)
├── init_scripts/           # SQL scripts for DB initialization
│   ├── 01_schema.sql       # Legacy schema (deprecated)
│   ├── 02_schema_v2.sql    # Core V2 schema
│   └── 03_schema_label_studio_v1.sql  # Label Studio additions
│
├── src/                    # Source code
│   ├── ingest_youtube.py   # YouTube ingestion
│   ├── ingest_substack.py  # Substack ingestion
│   ├── label_studio_sync.py # Label Studio sync
│   ├── sync_daemon.py      # DVC sync service
│   ├── export_reviewed.py  # Export reviewed data
│   ├── webhook_server.py   # FastAPI webhook handler
│   └── utils/              # Helper functions
│
├── label_studio_templates/ # Labeling interface XML configs
│   ├── transcript_correction.xml
│   ├── translation_review.xml
│   └── audio_segmentation.xml
│
├── docs/                   # Documentation
├── docker-compose.yml      # Service orchestration
├── Dockerfile.ingest       # Ingestion container definition
├── nginx.conf              # Audio server configuration
├── dvc.yaml                # DVC pipeline definition
├── .env.example            # Environment template
└── requirements.txt        # Python dependencies
```

## Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Database |
| Label Studio | 8080 | Annotation UI |
| Audio Server | 8081 | Serve audio files |
| Webhook Server | 8000 | Label Studio callbacks (if running locally) |

## Database Access

- **Host**: `localhost` (mapped from container)
- **Port**: `5432`
- **User**: `admin`
- **Password**: `secret_password`
- **Database**: `data_factory`

## Related Documentation

- [02. Project Progress](02_project_progress.md) - Current implementation status
- [04. Workflow](04_workflow.md) - Pipeline workflows
- [06. Database Design](06_database_design.md) - Schema reference
- [07. Label Studio](07_label_studio.md) - Annotation setup

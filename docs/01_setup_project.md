# 01. Project Setup

## Overview
This document outlines the setup process for the Vietnamese-English Code-Switching Speech Translation project. The project uses a **Docker-based** architecture for data ingestion, storage, and annotation.

**Key Features:**
- PostgreSQL backend for both `data_factory` (samples) and `label_studio` (annotations)
- All data persists in `./database_data/` - survives container restarts
- DVC with Google Drive for large file synchronization

## Prerequisites
- **Docker Desktop** (or Docker Engine + Compose)
- **Python 3.11+** (for local development and IDE support)
- **Git**
- **DVC credentials** (Google Drive service account - get from project owner)

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
    .venv\Scripts\Activate
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121
    ```

3.  **Copy environment configuration**:
    ```bash
    cp .env.example .env
    # Edit .env with your settings (Label Studio API key, etc.)
    ```

4.  **Set up DVC credentials** (for team members):
    ```powershell
    # Create the credentials directory
    mkdir -Force "$HOME\.cache\pydrive2fs"
    
    # Copy credentials from project owner
    Copy-Item "path\to\shared\credentials.json" "$HOME\.cache\pydrive2fs\credentials.json"
    ```

### 2. Infrastructure (Docker)

We use Docker Compose to manage PostgreSQL, Label Studio, and supporting services.

1.  **Start the Services**:
    ```bash
    docker-compose up -d --build
    ```
    
    Services started:
    - **`postgres`**: PostgreSQL database on port `5432` (hosts both `data_factory` and `label_studio` databases)
    - **`label_studio`**: Annotation interface on port `8080` (uses PostgreSQL backend)
    - **`audio_server`**: nginx audio file server on port `8081`
    - **`sync_service`**: DVC sync daemon (5-minute interval)
    - **`ingestion`**: Python environment for data processing

2.  **Verify Status**:
    ```bash
    docker-compose ps
    ```
    
    All services should show "healthy" or "running" status.

3.  **Database Initialization**:
    The database schemas are applied **automatically** on first start:
    - `00_create_label_studio_db.sql` - Creates Label Studio database
    - `01_schema.sql` - Legacy schema (deprecated)
    - `02_schema_v2.sql` - Complete schema with Label Studio integration
    
    > **Note:** No manual schema application needed! All schemas run automatically when `database_data/` is empty.

### 3. Label Studio Setup

1.  **Access Label Studio**: http://localhost:8085
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
│                           # Contains both data_factory and label_studio DBs
│
├── init_scripts/           # SQL scripts for DB initialization (run alphabetically)
│   ├── 00_create_label_studio_db.sql  # Creates label_studio database
│   ├── 01_schema.sql                  # Legacy schema (deprecated)
│   └── 02_schema_v2.sql               # Complete schema with Label Studio integration
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
| PostgreSQL | 5432 | Database (data_factory + label_studio) |
| Label Studio | 8085 | Annotation UI |
| Audio Server | 8081 | Serve audio files |
| Webhook Server | 8000 | Label Studio callbacks (if running locally) |

## Database Access

Two databases in the same PostgreSQL instance:

| Database | Purpose | User |
|----------|---------|------|
| `data_factory` | Samples, transcripts, translations | `admin` |
| `label_studio` | Label Studio internal data | `admin` |

**Connection details:**
- **Host**: `localhost` (mapped from container)
- **Port**: `5432`
- **User**: `admin`
- **Password**: `secret_password`

## ⚠️ Important: Data Persistence

### What persists where:
| Data | Location | Persists after `docker-compose down`? |
|------|----------|--------------------------------------|
| PostgreSQL (samples + Label Studio) | `./database_data/` | ✅ Yes |
| Audio/text files | `./data/` | ✅ Yes |
| DVC cache | `~/.cache/pydrive2fs/` | ✅ Yes |

### Clean Reset (DANGER!)
If you need to completely reset the database:

```powershell
# WARNING: This deletes ALL data including Label Studio accounts/projects!
docker-compose down
Remove-Item -Recurse -Force .\database_data\*
docker-compose up -d
```

After a clean reset, you'll need to:
1. Re-create your Label Studio account
2. Re-create Label Studio projects
3. Re-import any projects/tasks

### Safe Restart (preserves data)
```powershell
docker-compose down
docker-compose up -d
```

## Troubleshooting

### PowerShell: Running SQL scripts manually

PowerShell doesn't support `<` redirection. Use one of these methods:

**Method 1: Get-Content pipe (recommended)**
```powershell
Get-Content init_scripts\02_schema_v2.sql | docker exec -i factory_ledger psql -U admin -d data_factory
```

**Method 2: Copy and execute**
```powershell
docker cp init_scripts\02_schema_v2.sql factory_ledger:/tmp/schema.sql
docker exec factory_ledger psql -U admin -d data_factory -f /tmp/schema.sql
```

### Label Studio not connecting to PostgreSQL
Check that the postgres container is healthy first:
```powershell
docker-compose ps
docker logs factory_ledger
```

### DVC pull fails
Ensure credentials are in place:
```powershell
Test-Path "$HOME\.cache\pydrive2fs\credentials.json"
```

## Team Onboarding Checklist

For new team members:

- [ ] Clone repository
- [ ] Get DVC credentials from project owner
- [ ] Place credentials at `~/.cache/pydrive2fs/credentials.json`
- [ ] Copy `.env.example` to `.env`
- [ ] Run `docker-compose up -d --build`
- [ ] Wait for all services to be healthy
- [ ] Create Label Studio account at http://localhost:8085
- [ ] Get API key and update `.env`
- [ ] Run `dvc pull` to get data

## Related Documentation

- [02. Project Progress](02_project_progress.md) - Current implementation status
- [04. Workflow](04_workflow.md) - Pipeline workflows
- [06. Database Design](06_database_design.md) - Schema reference
- [07. Label Studio](07_label_studio.md) - Annotation setup and PostgreSQL backend

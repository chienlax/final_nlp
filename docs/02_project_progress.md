# 02. Project Progress & Architecture Status

**Date:** November 24, 2025

## 1. Infrastructure & Environment

### Containerization
We have transitioned to a Docker-based workflow to ensure consistent environments for data ingestion and database management.
- **`docker-compose.yml`**: Orchestrates the services.
- **`Dockerfile.ingest`**: Defines the environment for data ingestion tasks.

### Database Migration
- **Previous:** SQLite (`dataset/db/cs_corpus.db`).
- **Current:** PostgreSQL.
    - Data persistence is handled via the `database_data/` volume (ignored in git).
    - Initialization scripts are located in `init_scripts/`.
    - **Schema**: The `dataset_ledger` table tracks samples with fields for metadata (`source`, `acoustic`, `linguistic`), transcripts, and processing states (`RAW`, `DENOISED`, `SEGMENTED`, `REVIEWED`).

## 2. Data Management (DVC)

Data Version Control (DVC) has been integrated to manage large raw data files.
- **`data/raw.dvc`**: Tracks the raw data directory.
- **`data/raw/`**: Local storage for raw audio/text data (managed by DVC).

## 3. Codebase Status

### Utilities (`src/utils/`)
- **`data_utils.py`**:
    - Contains logic for calculating Code-Switching (CS) ratios using regex for Vietnamese character detection.
    - *Note:* Currently contains legacy SQLite connection code (`get_db_connection`). This may need to be updated or deprecated in favor of a PostgreSQL connector (e.g., `psycopg2` or `SQLAlchemy`).

### Setup
- **`setup_project.py`**: Script to initialize the local project directory structure.
- **`requirements.txt`**: Python dependencies.

## 4. Next Steps
- Update `src/utils/data_utils.py` to support PostgreSQL connections.
- Implement data ingestion pipelines using the new Docker setup.
- Verify DVC remote storage configuration.

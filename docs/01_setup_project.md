# 01. Project Setup

## Overview
This document outlines the setup process for the Vietnamese-English Code-Switching Speech Translation project. The project uses a **Docker-based** architecture for data ingestion and storage, ensuring a consistent environment.

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
    ```

### 2. Infrastructure (Docker)

We use Docker Compose to manage the PostgreSQL database and the Ingestion service.

1.  **Start the Services**:
    ```bash
    docker-compose up -d --build
    ```
    *   **`postgres`**: Starts the database on port `5432`.
    *   **`ingestion`**: Builds the Python environment for data processing.

2.  **Verify Status**:
    ```bash
    docker-compose ps
    ```

### 3. Data Management (DVC)

Large files (audio/raw text) are managed via DVC.

1.  **Pull Data**:
    ```bash
    dvc pull
    ```

## Project Structure

```text
project_root/
│
├── data/                   # DVC-managed data storage
│   ├── raw/                # Raw downloads
│   └── raw.dvc             # DVC tracking file
│
├── database_data/          # PostgreSQL data volume (Do not commit)
├── init_scripts/           # SQL scripts for DB initialization
│   └── 01_schema.sql
│
├── src/                    # Source code
│   ├── preprocessing/      # Cleaning and cutting scripts
│   ├── training/           # Training scripts
│   └── utils/              # Helper functions
│
├── docs/                   # Documentation
├── docker-compose.yml      # Service orchestration
└── Dockerfile.ingest       # Ingestion container definition
```

## Database Access

- **Host**: `localhost` (mapped from container)
- **Port**: `5432`
- **User**: `admin`
- **Password**: `secret_password`
- **Database**: `data_factory`

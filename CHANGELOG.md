# Changelog

All notable changes to the Vietnamese-English Code-Switching Speech Translation project.

---

## [2025-01-15] - SQLite + Streamlit Migration

### 🔄 Major Architecture Change

Migrated from PostgreSQL + Label Studio to a simplified SQLite + Streamlit stack.

### Added

#### New Core Components
- **`src/db.py`**: SQLite database utilities
  - Connection management with WAL mode
  - Context managers with auto-commit/rollback
  - Full CRUD operations for videos and segments
  - Segment splitting, review updates, statistics
  - JSON validation for manual uploads

- **`src/review_app.py`**: Streamlit review interface
  - Video selection with progress tracking
  - Segment-by-segment review with audio playback
  - Edit transcript, translation, and timestamps
  - Segment splitting for long segments
  - Approve/reject controls

- **`src/export_final.py`**: Dataset export
  - Export reviewed segments with audio slices
  - Manifest generation with statistics
  - State transition to `exported`

- **`init_scripts/sqlite_schema.sql`**: SQLite schema
  - `videos` table with processing states
  - `segments` table with review fields
  - Views: `v_video_progress`, `v_long_segments`, `v_export_ready`
  - Triggers for automatic timestamps

- **`setup.ps1`**: Unified setup script
  - Python virtual environment setup
  - Dependency installation
  - SQLite database initialization
  - Tailscale configuration for team access
  - Optional scheduled backup task

### Changed

#### Renamed Files
- `gemini_process_v2.py` → `gemini_process.py`
- `denoise_audio_v2.py` → `denoise_audio.py`

#### Updated Files
- **`Dockerfile.ingest`**: Removed psycopg2, added streamlit
- **`Dockerfile.preprocess`**: Removed psycopg2, added streamlit
- **`dvc.yaml`**: Updated pipeline stages for new scripts
- **`requirements.txt`**: SQLite-based dependencies

#### Processing States
Old: `RAW` → `TRANSLATED` → `REVIEW_PREPARED` → `FINAL`
New: `pending` → `transcribed` → `reviewed` → `exported`

### Removed

#### Deleted Scripts
- `src/db_backup.py` (PostgreSQL backup)
- `src/db_restore.py` (PostgreSQL restore)
- `src/export_reviewed.py` (Label Studio export)
- `src/label_studio_sync.py` (Label Studio sync)
- `src/sync_daemon.py` (PostgreSQL sync daemon)
- `src/preprocessing/prepare_review_audio.py`
- `src/preprocessing/apply_review.py`
- `src/preprocessing/gemini_repair_translation.py`
- `src/utils/data_utils.py` (PostgreSQL utilities)
- `src/utils/transcript_downloading_utils.py`

#### Deleted Folders
- `init_scripts/00_create_label_studio_db.sql`
- `init_scripts/01_schema.sql`
- `label_studio_templates/` (entire directory)
- `database_data/` (PostgreSQL data directory)

### Documentation

All documentation rewritten for SQLite + Streamlit workflow:
- `README.md`: New quick start and feature overview
- `docs/01_getting_started.md`: Tailscale setup, .env configuration
- `docs/02_architecture.md`: New pipeline diagram, SQLite schema
- `docs/03_command_reference.md`: Updated command examples
- `docs/04_troubleshooting.md`: SQLite and Streamlit issues
- `docs/05_api_reference.md`: db.py API documentation
- `docs/06_known_caveats.md`: SQLite limitations

### Why This Change?

1. **Simplified Deployment**: No Docker required for core workflow
2. **Portable Database**: Single SQLite file, easy backup/sync
3. **Integrated Review**: Streamlit UI runs alongside processing
4. **Team Access**: Tailscale for secure remote access
5. **Reduced Complexity**: Fewer moving parts, easier debugging

---

## [2024-11-30] - Gemini Unified Processing

### Added
- **`gemini_process.py`**: Unified script combining transcription and translation
  - Hybrid single-pass approach with structured JSON output
  - Few-shot prompting with Vietnamese-English code-switching examples
  - Automatic audio chunking for files >27 minutes
  - Overlap deduplication (>80% text similarity + ±2s timestamp overlap)
  - Translation issue detection and flagging
  
- **`gemini_repair_translation.py`**: Repair script for problematic translations
  - Queries samples with `has_translation_issues = TRUE`
  - Re-translates specific sentences by index
  - Clears `needs_translation_review` flag after repair

- **Database Schema Updates**:
  - `transcript_revisions.has_translation_issues` (BOOLEAN)
  - `transcript_revisions.translation_issue_indices` (INTEGER[])
  - `samples.needs_translation_review` (BOOLEAN)
  - `translation_revisions.sentence_translations` (JSONB)
  - Updated `add_transcript_revision()` function

### Changed
- Dockerfile.ingest now includes `google-generativeai` and `pydub` packages
- docker-compose.yml passes `GEMINI_API_KEY_1` and `GEMINI_API_KEY_2` to ingestion service

---

## [2024-11-29] - Label Studio Integration

### Added
- Complete Label Studio workflow documentation
- Legacy API token setup instructions
- Three annotation templates:
  - `transcript_correction.xml` (Round 1)
  - `segment_review.xml` (Round 2)
  - `translation_review.xml` (Round 3)

### Fixed
- Label Studio API authentication (JWT vs hex token issue)
- Audio URL resolution (internal vs external hostname)
- Database hostname in Docker network

---

## [2024-11-28] - Database & DVC Setup

### Added
- `db_backup.py` and `db_restore.py` for database synchronization
- DVC integration with Google Drive remote
- `sync_daemon.py` for automatic continuous sync

### Changed
- Schema updated with `segments` and `segment_translations` tables
- Removed deprecated `sample_lineage` table

---

## [2024-11-24] - Initial Pipeline

### Added
- YouTube-only ingestion pipeline
- `ingest_youtube.py` with transcript requirement
- Subtitle type detection (manual vs auto-generated)
- Code-switching ratio calculation

### Infrastructure
- Docker Compose setup with PostgreSQL, Label Studio, Audio Server
- `Dockerfile.ingest` for data ingestion
- `Dockerfile.preprocess` for GPU preprocessing

### Preprocessing Scripts
- `whisperx_align.py` - WhisperX forced alignment
- `segment_audio.py` - Audio segmentation (10-30s)
- `denoise_audio.py` - DeepFilterNet noise removal

### Utilities
- `data_utils.py` - Database operations
- `text_utils.py` - Text normalization, CS detection
- `video_downloading_utils.py` - YouTube audio download
- `transcript_downloading_utils.py` - Transcript download

---

## Project Status

### Current Architecture ✅

| Component | Technology |
|-----------|------------|
| Database | SQLite (WAL mode) |
| Review UI | Streamlit |
| Transcription | Gemini 2.5 Pro |
| Translation | Gemini 2.5 Pro |
| Denoising | DeepFilterNet |
| Team Access | Tailscale |
| Data Versioning | DVC + Google Drive |
| Audio Specs | 16kHz, Mono, WAV |

### Pipeline Stages

1. **Ingestion**: YouTube → Audio + Transcript → SQLite (`pending`)
2. **Denoising**: DeepFilterNet noise removal
3. **Processing**: Gemini transcription + translation (`transcribed`)
4. **Review**: Streamlit human review (`reviewed`)
5. **Export**: Final dataset generation (`exported`)

### GPU Requirements

| Script | Min VRAM | Recommended |
|--------|----------|-------------|
| denoise_audio.py | 2GB | 4GB |

### Planned 📋
- Multi-user review support
- Automatic quality metrics
- Training pipeline integration
- Model fine-tuning workflow

# Changelog

All notable changes to the Vietnamese-English Code-Switching Speech Translation project.

---

## [Unreleased]

### Added
- Unified `gemini_process.py` script for single-pass transcription + translation
- `gemini_repair_translation.py` for fixing problematic translations
- Adaptive audio chunking for files >27 minutes with overlap deduplication
- Translation issue flagging with `has_translation_issues` and `translation_issue_indices` columns
- New database columns: `needs_translation_review`, `sentence_translations` JSONB
- Migration script `02_gemini_process_migration.sql` for existing databases

### Changed
- Documentation reorganized from 8 files to 5 focused documents
- Audio chunking now uses adaptive sizing instead of fixed 28-minute chunks
- Chunk overlap reduced from 30s to 18s for better deduplication

### Removed
- Deprecated `translate.py` (replaced by `gemini_process.py`)
- Deprecated `gemini_transcribe.py` (merged into `gemini_process.py`)

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

### Completed ✅
- YouTube ingestion pipeline
- Database schema with versioned revisions
- Label Studio integration (3-stage review)
- Gemini unified processing (transcription + translation)
- DVC data versioning with Google Drive
- WhisperX alignment
- Audio segmentation
- DeepFilterNet denoising

### In Progress 🔄
- Translation review workflow
- Training data export

### Planned 📋
- Training pipeline implementation
- Data augmentation at training time
- Evaluation metrics and monitoring
- Model fine-tuning

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 15 |
| Annotation | Label Studio |
| Transcription | Gemini 2.5 Flash/Pro |
| Translation | Gemini 2.5 Flash/Pro |
| Alignment | WhisperX + wav2vec2-vi |
| Denoising | DeepFilterNet3 |
| Data Versioning | DVC + Google Drive |
| Containerization | Docker Compose |

---

## GPU Requirements

| Script | Min VRAM | Recommended |
|--------|----------|-------------|
| whisperx_align.py | 4GB | 8GB |
| denoise_audio.py | 2GB | 4GB |

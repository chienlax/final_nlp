# Changelog

All notable changes to the Vietnamese-English Code-Switching Speech Translation project.

---

## [Unreleased]

### Added

#### Unified Review System
- **`prepare_review_audio.py`**: Pre-cut sentence audio for Label Studio review
  - Creates `data/review/{sample_id}/sentences/{idx:04d}.wav` with 0.2s padding
  - Groups sentences into review chunks (default 15 per task)
  - Transitions: TRANSLATED → REVIEW_PREPARED
  
- **`apply_review.py`**: Apply corrections from unified review
  - Re-cuts audio with reviewed timestamps (or original if unchanged)
  - Creates `data/final/{sample_id}/sentences/` with TSV manifest
  - Cleans up review audio after successful apply
  - Transitions: REVIEW_PREPARED → FINAL

- **`unified_review.xml`**: Single Label Studio template for all review tasks
  - Paragraphs tag with `contextScroll="true"` for audio region playback
  - Sentence-level audio with individual playback controls
  - Editable transcript, translation, and timing per sentence
  - Delete sentence option for bad segments

- **Database Schema (`02_review_system_migration.sql`)**:
  - `REVIEW_PREPARED` processing state
  - `review_chunks` table (sample_id, chunk_index, sentence range, ls_task_id)
  - `sentence_reviews` table (corrections per sentence)
  - Helper functions: `create_review_chunk()`, `save_sentence_review()`, `check_chunk_completion()`

- **Nginx location blocks** for `/review/` and `/final/` audio serving

### Changed
- **`label_studio_sync.py`**: Complete rewrite for unified review workflow (v2)
  - Commands: `push unified_review`, `pull unified_review`, `reopen`, `status`
  - Creates Paragraphs predictions with sentence boundaries
  - Extracts sentence-level corrections from annotations
  
- **`export_reviewed.py`**: Updated for FINAL state workflow (v2)
  - Exports from `data/final/` instead of database exports
  - Generates TSV manifest + metadata.json per sample
  - Supports `--sample-id` and `--batch` modes

- Simplified processing states: RAW → TRANSLATED → REVIEW_PREPARED → FINAL

### Deprecated
- Legacy 3-stage review workflow (transcript → segment → translation)
- Old Label Studio templates archived to `label_studio_templates/archive/`
- Old sync script backed up to `label_studio_sync_v1.py`
- Old export script backed up to `export_reviewed_v1.py`

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
- **Unified Label Studio review system (NEW)**
  - 15 sentences per task
  - Sentence-level audio playback
  - Transcript + Translation + Timing corrections
- Gemini unified processing (transcription + translation)
- DVC data versioning with Google Drive
- Training data export pipeline

### Optional Preprocessing
- WhisperX alignment (if needed)
- DeepFilterNet denoising (if needed)

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

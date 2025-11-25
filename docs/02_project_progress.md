# 02. Project Progress & Architecture Status

**Update:** December 2025 (Schema V2)

## 1. Infrastructure & Environment

### Containerization
Docker-based workflow for consistent environments:
- **`docker-compose.yml`**: Orchestrates PostgreSQL + ingestion container.
- **`Dockerfile.ingest`**: Environment for data ingestion tasks.
    - Includes: `ffmpeg`, `yt-dlp`, `youtube-transcript-api`, `psycopg2-binary`, `dvc[gdrive]`.

### Database Architecture (V2)
- **Engine:** PostgreSQL 15
- **Schema:** Multi-table design supporting dual-modality pipelines
- **Init Scripts:** `init_scripts/02_schema_v2.sql`

#### Core Tables
| Table | Purpose |
|-------|---------|
| `sources` | Origin tracking (YouTube channels, Substack blogs) |
| `samples` | Central sample registry with processing state |
| `transcript_revisions` | Versioned transcripts (original → MFA → human-corrected) |
| `translation_revisions` | Versioned translations (LLM → human-corrected) |
| `annotations` | Label Studio task tracking |
| `sample_lineage` | Parent-child relationships (segments from full audio) |
| `processing_logs` | Audit trail for all processing steps |

#### ENUMs
- `source_type`: youtube, substack, podcast, other
- `processing_state`: RAW, ALIGNED, SEGMENTED, VAD_SEGMENTED, ENHANCED, TRANSLATED, REVIEWED
- `content_type`: audio, text, audio_text
- `annotation_task`: transcript_correction, translation_review, audio_segmentation, quality_check
- `annotation_status`: pending, in_progress, completed, rejected

#### Key Views
- `v_sample_current_state`: Latest transcript/translation for each sample
- `v_review_queue`: Samples ready for human review
- `v_pipeline_stats`: Processing statistics by state and type

## 2. Data Management (DVC)

- **`data/raw.dvc`**: Tracks the raw data directory.
- **`data/raw/`**: Local storage for raw audio/text data.
    - `data/raw/audio/` - 16kHz mono WAV files
    - `data/raw/text/` - Transcript text files
    - `data/raw/metadata.jsonl` - Batch metadata file
- **`data/teencode.txt`**: Vietnamese teencode dictionary for text normalization
- **`data/substack_downloads/`**: Downloaded Substack articles (Markdown)

## 3. Pipeline Architecture

### Audio-First Pipeline (YouTube)
```
YouTube URL → Download Audio (16kHz WAV) → Download Transcript
    ↓
samples (content_type='audio', pipeline_type='youtube')
    ↓
[If has transcript] → MFA Alignment → ALIGNED
    ↓
Silero VAD Segmentation → VAD_SEGMENTED
    ↓
DeepFilterNet Enhancement → ENHANCED
    ↓
Label Studio Review → REVIEWED
    ↓
LLM Translation → TRANSLATED
```

### Text-First Pipeline (Substack)
```
Substack URL → sbstck-dl Download → Markdown Files
    ↓
samples (content_type='text', pipeline_type='substack')
    ↓
Teencode Normalization → NORMALIZED (via transcript_revisions)
    ↓
CS Chunk Extraction → CS_CHUNKED
    ↓
TTS Generation (XTTS v2) → TTS_GENERATED
    ↓
Label Studio Review → REVIEWED
    ↓
LLM Translation → TRANSLATED
```

## 4. Codebase Status

### Ingestion Scripts (`src/`)
| Script | Purpose | Status |
|--------|---------|--------|
| `ingest_youtube.py` | YouTube audio ingestion orchestrator | ✅ Updated for V2 schema |
| `ingest_substack.py` | Substack article ingestion orchestrator | ✅ New |
| `label_studio_sync.py` | Push/pull annotations from Label Studio | ✅ New |

### Utilities (`src/utils/`)
| Module | Functions | Status |
|--------|-----------|--------|
| `data_utils.py` | `insert_sample()`, `insert_transcript_revision()`, `insert_translation_revision()`, `get_review_queue()`, `transition_state()`, `log_processing()` | ✅ Rewritten for V2 |
| `video_downloading_utils.py` | YouTube audio download (16kHz WAV) | ✅ Existing |
| `transcript_downloading_utils.py` | YouTube transcript download | ✅ Existing |
| `substack_utils.py` | `run_downloader()`, `list_downloaded_articles()`, `extract_blog_slug()` | ✅ New |
| `text_utils.py` | `load_teencode_dict()`, `normalize_text()`, `extract_cs_chunks()`, `contains_code_switching()` | ✅ New |

## 5. Label Studio Integration

### Environment Variables
```bash
LABEL_STUDIO_URL=http://localhost:8080
LABEL_STUDIO_API_KEY=your_api_key
LS_PROJECT_TRANSCRIPT=1
LS_PROJECT_TRANSLATION=2
LS_PROJECT_SEGMENTATION=3
```

### Commands
```bash
# Push samples to Label Studio for annotation
python src/label_studio_sync.py push --task-type transcript_correction

# Pull completed annotations back to database
python src/label_studio_sync.py pull --task-type transcript_correction

# Check connection status
python src/label_studio_sync.py status
```

## 6. Quick Start

### YouTube Ingestion
```bash
# Start database
docker-compose up -d postgres

# Ingest YouTube videos
python src/ingest_youtube.py "https://youtube.com/watch?v=VIDEO_ID"
```

### Substack Ingestion
```bash
# Create URLs file
echo "https://example.substack.com" > data/substack_urls.txt

# Run ingestion (requires sbstck-dl installed)
python src/ingest_substack.py --urls-file data/substack_urls.txt

# Or process existing downloads
python src/ingest_substack.py --skip-download
```

## 7. Next Steps
- [ ] Implement MFA alignment processor (`processing_state` → ALIGNED)
- [ ] Implement Silero VAD segmentation (`processing_state` → VAD_SEGMENTED)
- [ ] Implement DeepFilterNet enhancement (`processing_state` → ENHANCED)
- [ ] Set up Label Studio projects with annotation templates
- [ ] Implement TTS generation for text-first pipeline
- [ ] Add webhook handlers for real-time Label Studio sync

# 02. Project Progress

**Last Updated:** November 2024

## Current Status: YouTube-Only Pipeline with Human Review

The project has been simplified to focus exclusively on YouTube videos with transcripts, implementing a human-in-the-loop workflow for quality assurance.

---

## 1. Architecture Overview

### Pipeline Flow

```
RAW → TRANSCRIPT_REVIEW → TRANSCRIPT_VERIFIED → ALIGNED → SEGMENTED
    → SEGMENT_REVIEW → SEGMENT_VERIFIED → TRANSLATED
    → TRANSLATION_REVIEW → DENOISED → FINAL
```

### Key Design Decisions

1. **YouTube-only source** - Removed Substack/TTS pipeline for simplicity
2. **Transcript required** - Only process videos with manual or auto-generated subtitles
3. **Segment-level processing** - 10-30s audio chunks for training
4. **3-stage human review** - Transcript → Segment → Translation verification
5. **Deferred augmentation** - Apply at training time, not preprocessing

---

## 2. Infrastructure Status

### Containerization ✅

| Container | Purpose | Status |
|-----------|---------|--------|
| `Dockerfile.ingest` | Data ingestion | ✅ Complete |
| `Dockerfile.preprocess` | GPU preprocessing | ✅ Complete |
| `docker-compose.yml` | Service orchestration | ✅ Complete |

### Database ✅

- **Engine:** PostgreSQL 15
- **Schema:** `init_scripts/01_schema.sql`
- **Key tables:** `samples`, `segments`, `transcript_revisions`, `translation_revisions`, `segment_translations`

### Data Management ✅

- **DVC:** Google Drive remote for raw data
- **Audio format:** 16kHz mono WAV
- **Segment storage:** `data/segments/{sample_id}/`

---

## 3. Scripts Status

### Ingestion ✅

| Script | Purpose | Status |
|--------|---------|--------|
| `ingest_youtube.py` | YouTube video ingestion | ✅ Complete |

### Preprocessing ✅

| Script | Purpose | Status |
|--------|---------|--------|
| `preprocessing/whisperx_align.py` | WhisperX forced alignment | ✅ Complete |
| `preprocessing/segment_audio.py` | Audio segmentation (10-30s) | ✅ Complete |
| `preprocessing/translate.py` | Gemini translation with key rotation | ✅ Complete |
| `preprocessing/denoise_audio.py` | DeepFilterNet noise removal | ✅ Complete |

### Utilities ✅

| Module | Purpose | Status |
|--------|---------|--------|
| `utils/data_utils.py` | Database operations | ✅ Complete |
| `utils/video_downloading_utils.py` | YouTube audio download | ✅ Complete |
| `utils/transcript_downloading_utils.py` | YouTube transcript download | ✅ Complete |
| `utils/text_utils.py` | Text processing | ✅ Complete |

### Label Studio Integration ⚠️

| Script | Purpose | Status |
|--------|---------|--------|
| `label_studio_sync.py` | Push/pull annotations | ⚠️ Needs update for segments |

---

## 4. Label Studio Templates

| Template | Purpose | Status |
|----------|---------|--------|
| `transcript_correction.xml` | Round 1: Transcript review | ✅ Complete |
| `segment_review.xml` | Round 2: Segment verification | ✅ Complete |
| `translation_review.xml` | Round 3: Translation review | ✅ Complete |

---

## 5. Processing States

| State | Description | Human Review? |
|-------|-------------|---------------|
| RAW | Just ingested | No |
| TRANSCRIPT_REVIEW | In Label Studio for transcript correction | **Yes** |
| TRANSCRIPT_VERIFIED | Transcript reviewed | No |
| ALIGNED | WhisperX alignment complete | No |
| SEGMENTED | Audio segmented into chunks | No |
| SEGMENT_REVIEW | In Label Studio for segment verification | **Yes** |
| SEGMENT_VERIFIED | Segments verified | No |
| TRANSLATED | Gemini translation complete | No |
| TRANSLATION_REVIEW | In Label Studio for translation review | **Yes** |
| DENOISED | DeepFilterNet processing complete | No |
| FINAL | Ready for training export | No |
| REJECTED | Failed QC | No |

---

## 6. Technical Stack

### Preprocessing

| Tool | Purpose | Version |
|------|---------|---------|
| WhisperX | Forced alignment | 3.7.4 |
| DeepFilterNet | Noise removal | Latest |
| Gemini API | Translation | gemini-1.5-flash |

### Vietnamese Alignment

- **Model:** `nguyenvulebinh/wav2vec2-base-vi-vlsp2020`
- **Framework:** WhisperX with HuggingFace backend

### GPU Requirements

| Script | Min VRAM | Recommended |
|--------|----------|-------------|
| whisperx_align.py | 4GB | 8GB |
| denoise_audio.py | 2GB | 4GB |

---

## 7. Database Views

| View | Purpose |
|------|---------|
| `v_pipeline_stats` | Processing statistics by state |
| `v_sample_overview` | Sample details with current state |
| `v_api_key_status` | Gemini API key rotation status |
| `v_export_ready_segments` | Segments ready for training |

---

## 8. Next Steps

### Immediate

- [ ] Update `label_studio_sync.py` for segment-level tasks
- [ ] Create training data export script
- [ ] Test full pipeline end-to-end

### Future

- [ ] Implement training pipeline
- [ ] Add data augmentation at training time
- [ ] Evaluation metrics and monitoring

---

## 9. Quick Reference

### Ingest Videos

```bash
python src/ingest_youtube.py https://www.youtube.com/@SomeChannel
```

### Run Preprocessing

```bash
# WhisperX alignment
python src/preprocessing/whisperx_align.py --batch --limit 10

# Segmentation
python src/preprocessing/segment_audio.py --batch --limit 10

# Translation
python src/preprocessing/translate.py --batch --limit 10

# Denoising
python src/preprocessing/denoise_audio.py --batch --limit 10
```

### Check Pipeline Stats

```sql
SELECT * FROM v_pipeline_stats;
```

---

## Related Documentation

- [01_setup_project.md](01_setup_project.md) - Environment setup
- [04_workflow.md](04_workflow.md) - Detailed workflow
- [05_scripts_details.md](05_scripts_details.md) - Script reference


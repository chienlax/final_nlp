# Simplified Pipeline Workflow (v3)

## Overview

This document describes the streamlined audio processing workflow for Vietnamese-English code-switched (CS) speech translation, focusing exclusively on **YouTube videos with transcripts**.

### Key Simplifications from v2

1. **YouTube-only source** - Removed Substack/TTS pipeline
2. **Transcript required** - Only process videos with manual or auto-generated subtitles
3. **Segment-level translations** - Store translations per audio segment for training export
4. **3-stage human review** - Transcript → Segment → Translation verification
5. **Deferred augmentation** - Apply augmentation during training, not preprocessing

---

## Pipeline Stages

```
RAW → TRANSCRIPT_REVIEW → TRANSCRIPT_VERIFIED → ALIGNED → SEGMENTED 
    → SEGMENT_REVIEW → SEGMENT_VERIFIED → TRANSLATED → TRANSLATION_REVIEW 
    → DENOISED → FINAL
```

### Stage Descriptions

| Stage | Description | Human Review? | Script |
|-------|-------------|---------------|--------|
| RAW | Just crawled, raw transcript stored | No | `ingest_youtube_v3.py` |
| TRANSCRIPT_REVIEW | In Label Studio for transcript correction | **Yes** | `label_studio_sync.py` |
| TRANSCRIPT_VERIFIED | Transcript reviewed and corrected | No | - |
| ALIGNED | WhisperX alignment complete (word timestamps) | No | `whisperx_align.py` |
| SEGMENTED | Audio segmented into 10-30s chunks | No | `segment_audio.py` |
| SEGMENT_REVIEW | In Label Studio for segment verification | **Yes** | `label_studio_sync.py` |
| SEGMENT_VERIFIED | Segments verified, ready for translation | No | - |
| TRANSLATED | Gemini translation complete (draft) | No | `translate.py` |
| TRANSLATION_REVIEW | In Label Studio for translation review | **Yes** | `label_studio_sync.py` |
| DENOISED | DeepFilterNet noise removal complete | No | `denoise_audio.py` |
| FINAL | All reviews passed, ready for training | No | - |
| REJECTED | Failed QC, excluded from training | No | - |

---

## Detailed Workflow

### Phase 1: Ingestion (RAW)

**Script:** `src/ingest_youtube_v3.py`

```bash
# Download and ingest from YouTube channel
python src/ingest_youtube_v3.py https://www.youtube.com/@SomeChannel

# Re-ingest existing metadata
python src/ingest_youtube_v3.py --skip-download

# Dry run (no database changes)
python src/ingest_youtube_v3.py --skip-download --dry-run
```

**Process:**
1. Download audio as 16kHz mono WAV (2-60 min filter)
2. Download transcripts with **subtitle type detection**
   - Manual (human-created) - higher priority
   - Auto-generated - lower priority
   - None - **REJECTED**
3. Calculate code-switching ratio
4. Insert into database with `RAW` state

**Database Tables:**
- `sources` - YouTube channel info
- `samples` - Video records with `subtitle_type`
- `transcript_revisions` - Initial transcript (version 0)

---

### Phase 2: Human Review - Transcript (TRANSCRIPT_REVIEW)

**Template:** `label_studio_templates/transcript_correction.xml`

**Human Tasks:**
- Listen to full audio
- Correct transcript errors (especially auto-generated)
- Fix Vietnamese diacritics
- Fix English words/phrases
- Flag quality issues

**After Review:**
- Corrected transcript → new `transcript_revisions` entry (version 1)
- State → `TRANSCRIPT_VERIFIED`

---

### Phase 3: Alignment (ALIGNED)

**Script:** `src/preprocessing/whisperx_align.py`

```bash
# Align specific sample
python src/preprocessing/whisperx_align.py --sample-id <uuid>

# Batch processing
python src/preprocessing/whisperx_align.py --batch --limit 10
```

**Process:**
1. Load WhisperX with Vietnamese alignment model (`nguyenvulebinh/wav2vec2-base-vi-vlsp2020`)
2. Force-align verified transcript with audio
3. Extract word-level timestamps
4. Extract sentence-level timestamps
5. Store in `transcript_revisions.word_timestamps` and `sentence_timestamps`

**Output:**
```json
{
  "word_timestamps": [
    {"word": "Xin", "start": 0.5, "end": 0.7, "score": 0.95},
    {"word": "chào", "start": 0.7, "end": 1.0, "score": 0.92}
  ],
  "sentence_timestamps": [
    {"text": "Xin chào everybody", "start": 0.5, "end": 2.1, "words": [...]}
  ]
}
```

---

### Phase 4: Segmentation (SEGMENTED)

**Script:** `src/preprocessing/segment_audio.py`

```bash
# Segment specific sample
python src/preprocessing/segment_audio.py --sample-id <uuid>

# Batch processing
python src/preprocessing/segment_audio.py --batch --limit 10
```

**Process:**
1. Group sentences into 10-30s segments
2. Prefer sentence boundaries for clean cuts
3. Split long sentences at word boundaries if needed
4. Slice audio files
5. Create segment records in database

**Output:**
- `data/segments/{sample_id}/0000.wav`, `0001.wav`, ...
- `segments` table records with:
  - `transcript_text` - Segment transcript
  - `word_timestamps` - Word-level timing
  - `alignment_score` - Average confidence

---

### Phase 5: Human Review - Segments (SEGMENT_REVIEW)

**Template:** `label_studio_templates/segment_review.xml`

**Human Tasks:**
- Listen to segment audio
- Verify segment boundaries (no cut words)
- Confirm transcript matches audio
- Flag alignment issues

**After Review:**
- `segments.is_verified = TRUE`
- State → `SEGMENT_VERIFIED`

---

### Phase 6: Translation (TRANSLATED)

**Script:** `src/preprocessing/translate.py`

```bash
# Translate specific sample
python src/preprocessing/translate.py --sample-id <uuid>

# Batch processing
python src/preprocessing/translate.py --batch --limit 10

# Check API key status
python src/preprocessing/translate.py --check-keys
```

**Process:**
1. Get next available API key (rotation)
2. Translate FULL transcript (global context)
3. Split translation to match segments
4. Store both full and per-segment translations

**API Key Rotation:**
```bash
# Environment variables
export GEMINI_API_KEY_1="your-first-key"
export GEMINI_API_KEY_2="your-second-key"
export GEMINI_API_KEY_3="your-third-key"
```

When a key hits rate limit:
1. Mark key as rate-limited in database
2. Switch to next available key
3. If all keys exhausted → stop and wait for next day

**Output:**
- `translation_revisions` - Full translation
- `segment_translations` - Per-segment translations

---

### Phase 7: Human Review - Translation (TRANSLATION_REVIEW)

**Template:** `label_studio_templates/translation_review.xml`

**Human Tasks:**
- Listen to segment audio
- Verify transcript matches audio
- Review translation accuracy
- Correct translation errors
- Make final approve/reject decision

**After Review:**
- `segment_translations.is_verified = TRUE`
- State → ready for DENOISED

---

### Phase 8: Denoising (DENOISED)

**Script:** `src/preprocessing/denoise_audio.py`

```bash
# Denoise specific sample
python src/preprocessing/denoise_audio.py --sample-id <uuid>

# Batch processing
python src/preprocessing/denoise_audio.py --batch --limit 10
```

**Process:**
1. Load DeepFilterNet3 model
2. Process each verified segment
3. Remove background noise (NO enhancement/upscaling)
4. Save denoised audio to same path (replace)

**Note:** DeepFilterNet only removes noise, does not enhance or upscale audio quality.

---

### Phase 9: Final (FINAL)

Sample is ready for training export when:
- All segments verified
- All translations verified  
- Audio denoised

```bash
# Export training data
python src/export_training.py --format hf_datasets
```

---

## Data Augmentation

**Strategy:** Apply augmentation **at training time**, not during preprocessing.

**Rationale:**
1. Storage efficiency - Don't multiply dataset size
2. Flexibility - Try different augmentation strategies
3. Reproducibility - Original data preserved

**Augmentation Types (at training):**
- Speed perturbation (0.9x - 1.1x)
- Volume normalization
- Background noise addition (optional)

---

## Docker Setup

### GPU Preprocessing Container

```bash
# Build
docker build -f Dockerfile.preprocess -t nlp-preprocess .

# Run with GPU
docker run --gpus all -v $(pwd):/app nlp-preprocess

# Run specific script
docker exec -it <container> python src/preprocessing/whisperx_align.py --batch
```

### Required GPU Memory

| Script | Min VRAM | Recommended |
|--------|----------|-------------|
| whisperx_align.py | 4GB | 8GB |
| denoise_audio.py | 2GB | 4GB |

---

## Database Schema (v3)

Key tables:
- `samples` - Parent videos with `subtitle_type`
- `segments` - Audio chunks (10-30s)
- `transcript_revisions` - Transcript versions with timestamps
- `translation_revisions` - Translation versions
- `segment_translations` - Per-segment translations for training
- `api_keys` - Gemini API key rotation tracking

See `init_scripts/03_schema_v3.sql` for full schema.

---

## File Structure

```
data/
├── raw/
│   ├── audio/          # Full video audio files
│   │   └── {video_id}.wav
│   ├── text/           # Raw transcripts (JSON with timestamps)
│   │   └── {video_id}_transcript.json
│   └── metadata.jsonl
├── segments/           # Segmented audio chunks
│   └── {sample_id}/
│       ├── 0000.wav
│       ├── 0001.wav
│       └── ...
└── exports/            # Training data exports
    └── {export_name}/
```

---

## Monitoring & Stats

```sql
-- Pipeline statistics
SELECT * FROM v_pipeline_stats;

-- Sample overview
SELECT * FROM v_sample_overview WHERE processing_state = 'SEGMENT_REVIEW';

-- API key status
SELECT * FROM v_api_key_status;

-- Export-ready segments
SELECT COUNT(*) FROM v_export_ready_segments;
```

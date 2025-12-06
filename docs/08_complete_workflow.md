# Complete Workflow Guide

Comprehensive guide covering all workflows for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Overview

This guide covers three main workflows:

1. **YouTube CLI Workflow** - Command-line processing of YouTube videos
2. **Streamlit GUI Workflow** - Web interface for ingestion and review
3. **Direct Upload Workflow** - Upload pre-recorded audio files

---

## Workflow A: YouTube CLI Processing

Full command-line workflow for processing YouTube videos.

### Step 1: Download YouTube Audio

```powershell
# Single video
python src/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
python src/ingest_youtube.py "URL1" "URL2" "URL3"

# Playlist (downloads all videos)
python src/ingest_youtube.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"

# Re-ingest from existing metadata (skip download)
python src/ingest_youtube.py --skip-download

# Download with manual transcripts
python src/ingest_youtube.py "URL" --download-transcript-vi
```

**Output:**
- Audio: `data/raw/audio/{channel_id}/{video_id}.wav`
- Metadata: `data/raw/metadata.jsonl`
- Database: Video record with `state='pending'`
- Queue: Chunking jobs in `data/raw/chunk_jobs.jsonl`

### Step 2: (Optional) Chunk Long Videos

For videos longer than 10 minutes, split into manageable chunks:

```powershell
# Chunk specific video
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID

# Chunk all pending long videos
python src/preprocessing/chunk_audio.py --all
```

**Chunking Strategy:**
- Chunk size: ~10 minutes
- Overlap: 10 seconds
- Creates chunks table records
- Output: `data/raw/chunks/{video_id}/chunk_*.wav`

**When to chunk:**
- Videos >10 minutes: Recommended
- Videos >20 minutes: Strongly recommended
- Allows independent processing and better error recovery

### Step 3: (Optional) Denoise Audio

Apply DeepFilterNet for background noise removal:

```powershell
# Denoise all pending videos
python src/preprocessing/denoise_audio.py --all

# Denoise specific video
python src/preprocessing/denoise_audio.py --video-id VIDEO_ID

# Skip if no GPU available
```

**Important:** Denoising modifies `denoised_audio_path` but keeps `state='pending'` so Gemini processing can find the video.

**Output:**
- Denoised audio: `data/denoised/{video_id}_denoised.wav`
- Database: `denoised_audio_path` updated

### Step 4: Process with Gemini

Transcribe and translate using Gemini 2.5 Pro:

```powershell
# Process all pending videos (full videos)
python src/preprocessing/gemini_process.py --all

# Process specific video
python src/preprocessing/gemini_process.py --video-id VIDEO_ID

# Process specific chunk (for chunked videos)
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --chunk-id CHUNK_ID

# Dry run (test without API calls)
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --dry-run

# Standalone mode (process audio file directly)
python src/preprocessing/gemini_process.py --standalone audio.wav
```

**Processing:**
- Uses denoised audio if available, otherwise original
- Auto-chunks long audio (>10 min) with 10s overlap
- Deduplicates overlapping segments (80% similarity)
- Multi-API key support with automatic rotation
- Retry logic with exponential backoff

**Output:**
- Database: Segments inserted, `state='transcribed'`
- Structured JSON with timestamps

### Step 5: Review in Streamlit

Launch the review interface:

```powershell
streamlit run src/review_app.py
```

**Review Features:**
- Filter by channel and chunk
- Play audio with auto-pause at segment boundaries
- Edit transcript and translation
- Adjust start/end timestamps
- Assign reviewers (dropdown with add option)
- Split long segments
- Approve/reject segments
- Upload/remove transcript files
- Keyboard shortcuts: Alt+A (approve), Alt+S (save), Alt+R (reject)

**Workflow:**
1. Select video from "Review Audio Transcript" tab
2. Filter by channel if needed
3. Select chunk for chunked videos
4. Play segment to verify timing
5. Edit transcript/translation as needed
6. Approve or reject each segment
7. Save changes

### Step 6: Export Dataset

Export approved segments for training:

```powershell
# Export all reviewed videos
python src/export_final.py

# Export specific video
python src/export_final.py --video-id VIDEO_ID
```

**Output:**
- Audio segments: `data/export/audio/{video_id}_{index}.wav`
- Manifest: `data/export/manifest.tsv`
- Format: 16kHz mono WAV, 2-25 seconds
- Database: `state='exported'`

---

## Workflow B: Streamlit GUI Processing

Complete workflow using only the Streamlit web interface.

### Step 1: Launch Streamlit

```powershell
streamlit run src/review_app.py
```

Open http://localhost:8501

### Step 2: Download YouTube Videos (GUI)

Navigate to **"Download Audios"** tab:

1. **Single Video:**
   - Paste YouTube URL
   - Optionally: Download Vietnamese manual transcript
   - Click "Download"

2. **Playlist:**
   - Paste playlist URL
   - Click "Fetch Playlist Info"
   - Review video list with thumbnails and metadata
   - Filter by date range if needed
   - Select videos to download
   - Click "Download Selected Videos"

3. **Options:**
   - Dry run mode (test without downloading)
   - Re-ingest from metadata

**Advantages:**
- Visual preview of playlist videos
- Date filtering for selective download
- Thumbnail and metadata display
- Progress tracking in real-time

### Step 3: Review Segments (GUI)

Navigate to **"Review Audio Transcript"** tab:

1. **Filter Videos:**
   - Select channel from dropdown
   - Choose video to review
   - Filter: Show all / Unreviewed only / Reviewed only / Rejected

2. **Select Chunk (if applicable):**
   - For chunked videos, select specific chunk
   - Progress indicator shows completion percentage

3. **Review Segments:**
   - Click play button to hear audio
   - Audio auto-pauses at segment end
   - Edit transcript/translation in text boxes
   - Adjust timing if needed
   - Click "Save Changes" or press Alt+S
   - Click "Approve" (Alt+A) or "Reject" (Alt+R)

4. **Manage Workflow:**
   - Assign reviewer from dropdown (or add new)
   - Upload transcript file if available
   - Remove transcript file if needed
   - Add reviewer notes

### Step 4: Export from Dashboard

Navigate to **"Dashboard"** tab:

- View statistics (total videos, segments, reviewed count)
- Check processing state distribution
- Once review complete, use CLI export:
  ```powershell
  python src/export_final.py
  ```

---

## Workflow C: Direct Upload

For pre-recorded audio files without YouTube source.

### Step 1: Prepare Files

1. **Audio file:**
   - Format: WAV, MP3, M4A, or other common formats
   - Will be converted to 16kHz mono WAV

2. **Transcript JSON (optional):**
   ```json
   {
     "segments": [
       {
         "text": "Original Vietnamese/English transcript",
         "start": 0.0,
         "end": 5.5,
         "translation": "English translation"
       }
     ]
   }
   ```

### Step 2: Upload via Streamlit

Navigate to **"Upload Data"** tab:

1. Upload audio file
2. (Optional) Upload transcript JSON
3. Enter metadata:
   - Title
   - Source description
4. Click "Upload"

**Behavior:**
- Audio converted to 16kHz mono WAV
- Stored in `data/raw/audio/`
- Database: `source_type='upload'`, `state='transcribed'` (if JSON provided) or `'pending'`
- Skips Gemini if transcript provided

### Step 3: Process or Review

**If transcript provided:**
- Go directly to review (Workflow B, Step 3)

**If no transcript:**
- Process with Gemini:
  ```powershell
  python src/preprocessing/gemini_process.py --video-id VIDEO_ID
  ```
- Then review

### Step 4: Export

Same as other workflows:

```powershell
python src/export_final.py --video-id VIDEO_ID
```

---

## Advanced: Chunking Strategy

### When to Chunk

| Video Duration | Recommendation |
|----------------|----------------|
| <10 minutes | No chunking needed |
| 10-20 minutes | Optional, for easier review |
| >20 minutes | Strongly recommended |
| >60 minutes | Required for stability |

### Chunking Process

```powershell
# After ingest, before Gemini processing
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID
```

**How it works:**
1. Splits audio into ~10 minute chunks
2. 10 second overlap between chunks
3. Creates chunk records in database
4. Links segments to specific chunks

**Benefits:**
- Independent processing (one chunk fails, others continue)
- Easier review (focus on one chunk at a time)
- Better memory management
- Parallel processing capability

### Processing Chunks

```powershell
# Process all chunks for a video
python src/preprocessing/gemini_process.py --video-id VIDEO_ID

# Process specific chunk
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --chunk-id CHUNK_ID
```

### Reviewing Chunks

In Streamlit:
1. Select video
2. Chunk selector appears if video is chunked
3. Select specific chunk to review
4. Review segments for that chunk
5. Progress bar shows overall completion

---

## State Transition Reference

### State Flow Diagram

```
                    ┌─────────────┐
                    │   pending   │ (after download)
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                                 │
  ┌───────▼────────┐               ┌───────▼────────┐
  │    denoise     │               │  gemini_process │
  │  (optional)    │               │                 │
  └───────┬────────┘               └───────┬─────────┘
          │                                 │
          │ (updates denoised_audio_path,   │
          │  keeps state='pending')         │
          │                                 │
          └────────────────┬────────────────┘
                           │
                    ┌──────▼──────┐
                    │ transcribed │ (after Gemini)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   reviewed  │ (after human review)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  exported   │ (dataset ready)
                    └─────────────┘

             Alternative: rejected (at any review stage)
```

### State Descriptions

| State | Meaning | Next Step |
|-------|---------|-----------|
| `pending` | Downloaded, ready for processing | Denoise OR process with Gemini |
| `transcribed` | Gemini processing complete | Human review in Streamlit |
| `reviewed` | Human review complete | Export dataset |
| `exported` | Final dataset generated | Use for training |
| `rejected` | Video unusable | Archive or delete |

### Important Notes

1. **Denoising is optional** - Keeps state as `pending` to allow Gemini processing
2. **Direct uploads with JSON** - Start at `transcribed` state
3. **Chunk states** - Tracked independently, video state updates when all chunks complete
4. **State transitions are one-way** - No automatic rollback

---

## Troubleshooting Workflows

### Issue: Gemini can't find video after denoising

**Cause:** State transition mismatch (if denoising set state to `denoised`)

**Solution:**
```powershell
# Update state back to pending
python -c "from src.db import get_db; db = get_db(); db.execute('UPDATE videos SET processing_state=\"pending\" WHERE video_id=\"VIDEO_ID\"'); db.commit()"
```

### Issue: Long video processing fails

**Cause:** Memory or timeout issues

**Solution:**
```powershell
# Chunk the video first
python src/preprocessing/chunk_audio.py --video-id VIDEO_ID

# Process chunks individually
python src/preprocessing/gemini_process.py --video-id VIDEO_ID --chunk-id CHUNK_ID
```

### Issue: Duplicate segments in review

**Cause:** Video processed multiple times

**Solution:**
- Check database for duplicate entries
- Use `--dry-run` before actual processing
- Clear segments before reprocessing:
  ```powershell
  python -c "from src.db import get_db; db = get_db(); db.execute('DELETE FROM segments WHERE video_id=\"VIDEO_ID\"'); db.commit()"
  ```

### Issue: Can't play audio in Streamlit

**Cause:** Audio path mismatch or file not found

**Solution:**
- Verify audio file exists at path in database
- Check file permissions
- Ensure audio is in WAV format (16kHz mono)

---

## Best Practices

### 1. Always Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Use Dry Run First

```powershell
python src/ingest_youtube.py "URL" --dry-run
python src/preprocessing/gemini_process.py --video-id ID --dry-run
```

### 3. Chunk Long Videos Early

```powershell
# Right after ingestion, before any processing
python src/preprocessing/chunk_audio.py --all
```

### 4. Review Regularly

- Don't wait until all videos are processed
- Review in small batches
- Assign reviewers early for team workflows

### 5. Backup Database

```powershell
# Before major operations
Copy-Item data/lab_data.db data/lab_data.db.backup
```

### 6. Monitor API Usage

- Track Gemini API quota
- Use multiple API keys for high-volume processing
- Check logs for failed requests

### 7. Export Incrementally

```powershell
# Export per video as review completes
python src/export_final.py --video-id VIDEO_ID
```

---

## Next Steps

- 📖 [Architecture](02_architecture.md) - Technical deep-dive
- 🛠️ [Command Reference](03_command_reference.md) - All CLI commands
- 📚 [API Reference](05_api_reference.md) - Developer documentation
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues

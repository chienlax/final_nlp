# Known Caveats & Limitations

This document tracks known limitations, edge cases, and areas for future improvement in the Vietnamese-English Code-Switching (CS) Speech Translation pipeline.

---

## Table of Contents

1. [Database & Concurrency](#1-database--concurrency)
2. [Audio Processing](#2-audio-processing)
3. [Gemini API](#3-gemini-api)
4. [Review Interface](#4-review-interface)
5. [Data Quality](#5-data-quality)
6. [Security Considerations](#6-security-considerations)

---

## 1. Database & Concurrency

### SQLite Single-Writer Limitation

**Issue**: SQLite allows only one writer at a time. Concurrent writes will block.

**Impact**:
- Stop Streamlit before running batch processing scripts
- Only one batch process should run at a time

**Workaround**:
```powershell
# Stop Streamlit before batch operations
# Ctrl+C in Streamlit terminal

# Run batch process
python src/preprocessing/gemini_process.py

# Restart Streamlit after
streamlit run src/review_app.py
```

**Status**: Known limitation of SQLite. WAL mode helps with concurrent reads.

---

### Database Locking Timeout

**Issue**: Busy timeout is set to 5 seconds. Very long transactions may still fail.

**Impact**: "database is locked" error in edge cases

**Mitigation**: The `get_db()` context manager uses `PRAGMA busy_timeout=5000` which handles most cases.

---

### No Automatic Backup

**Issue**: Database must be backed up manually or via scheduled task.

**Mitigation**: 
- Manual backup: `Copy-Item data/lab_data.db data/backups/`
- DVC tracks `data/db_sync.dvc` for version control
- Google Drive sync script available: `src/setup_gdrive_auth.py`

**Note**: Automated hourly backups are not configured by default. Set up your own backup schedule if needed.

---

### State Transition After Denoising (IMPORTANT)

**Issue**: `denoise_audio.py` updates `denoised_audio_path` but the behavior regarding `processing_state` may vary.

**Current Behavior**: Denoising keeps state as `pending` so `gemini_process.py` can find videos.

**Impact**: If state is set to `denoised`, Gemini processing won't find the video (it looks for `pending` state).

**Workaround** (if issue occurs):
```powershell
# Reset state to pending after denoising
python -c "from src.db import get_db; db = get_db(); db.execute('UPDATE videos SET processing_state=\"pending\" WHERE processing_state=\"denoised\"'); db.commit()"
```

**Proper Workflow**:
1. Ingest (state=`pending`)
2. (Optional) Denoise (keeps state=`pending`, updates `denoised_audio_path`)
3. Process with Gemini (looks for state=`pending`, uses denoised path if available)
4. Review (state=`transcribed` → `reviewed`)
5. Export (state=`exported`)

**Status**: Documented in [Complete Workflow Guide](08_complete_workflow.md).

---

## 2. Audio Processing

### DeepFilterNet Memory Usage

**Issue**: DeepFilterNet can use significant GPU memory for long audio files.

**Impact**: OOM errors on GPUs with <4GB VRAM

**Workaround**:
```powershell
# Process fewer files at a time
python src/preprocessing/denoise_audio.py --limit 5

# Or use CPU (slower but more stable)
$env:CUDA_VISIBLE_DEVICES = ""
python src/preprocessing/denoise_audio.py
```

---

### Audio Chunk Overlap Edge Cases

**Issue**: When audio is split into 10-minute chunks, sentence deduplication at boundaries may occasionally fail.

**Impact**: Rare duplicate sentences near chunk boundaries

**Detection**: Check for sentences with identical timestamps in review

**Status**: Deduplication uses 80% text similarity threshold. Adjust if issues persist.

---

### Large Audio Files

**Issue**: Very long audio (>2 hours) may cause memory issues during processing.

**Impact**: Processing may fail or be very slow

**Workaround**: Consider splitting large files before ingestion:
```powershell
ffmpeg -i long_video.wav -f segment -segment_time 3600 -c copy part_%03d.wav
```

---

## 3. Gemini API

### Rate Limits

**Issue**: Gemini 2.5 Pro has rate limits that vary by tier.

**Impact**: 
- Free tier: ~2 RPM, ~32k TPM
- Paid tier: Higher limits

**Workaround**: The processing script includes delays between requests. For heavy workloads, consider:
- Using multiple API keys
- Processing during off-peak hours
- Upgrading to paid tier

---

### Non-Deterministic Output

**Issue**: Gemini responses can vary between runs for the same input.

**Impact**: 
- Timestamps may differ slightly
- Translation wording may vary

**Mitigation**: This is acceptable for initial processing; human review catches issues.

---

### JSON Parsing Failures

**Issue**: Gemini occasionally returns malformed JSON.

**Impact**: Processing fails for that video

**Mitigation**: 
- Script retries up to 3 times with exponential backoff
- Failed videos remain in "pending" state for retry

---

### Context Length Limits

**Issue**: Very long audio chunks may exceed Gemini's input limits.

**Impact**: Processing fails with context length error

**Mitigation**: Audio is chunked at 10-minute intervals to stay within limits.

---

## 4. Review Interface

### Streamlit Session State

**Issue**: Streamlit session state resets on page refresh.

**Impact**: Current position in review is lost on refresh

**Mitigation**: All changes are saved to database immediately. Only navigation position is lost.

---

### Audio Player Browser Compatibility

**Issue**: HTML5 audio player behavior varies across browsers.

**Impact**: Some browsers may not autoplay or seek correctly

**Recommended**: Use Chrome or Firefox for best experience.

---

### Single-User Design

**Issue**: Streamlit app is designed for single-user access.

**Impact**: Multiple reviewers accessing simultaneously may cause conflicts

**Mitigation**: 
- Use different ports for different reviewers
- Or process different videos in sequence

---

### No Undo for Segment Splits

**Issue**: Segment splitting cannot be undone through the UI.

**Impact**: Must manually edit database to merge split segments

**Workaround**:
```sql
-- To undo a split, delete the second segment and update the first
DELETE FROM segments WHERE segment_id = <second_id>;
UPDATE segments SET end_ms = <original_end>, transcript = <combined>, translation = <combined>
WHERE segment_id = <first_id>;
```

---

## 5. Data Quality

### Segment Duration Constraints

**Issue**: Target duration is 2-25 seconds, but Gemini may produce segments outside this range.

**Impact**: Very short or very long segments require manual adjustment

**Detection**: Use `v_long_segments` view to find segments >25s:
```sql
SELECT * FROM v_long_segments;
```

---

### Code-Switching Detection Accuracy

**Issue**: CS detection uses simple keyword matching (Intersection Rule).

**Impact**: 
- May miss complex CS patterns
- May over-detect on borrowed words

**Status**: Acceptable for initial filtering; human review is primary quality gate.

---

### Translation Quality Variance

**Issue**: Gemini translation quality varies with audio clarity and CS complexity.

**Impact**: Some translations may require significant correction

**Mitigation**: This is why human review is mandatory before export.

---

## 6. Security Considerations

### API Key Storage

**Issue**: GEMINI_API_KEY stored in `.env` file.

**Impact**: Anyone with file access can read the key

**Mitigation**:
- Ensure `.env` is in `.gitignore`
- Use file permissions to restrict access
- Rotate keys periodically

---

### Tailscale Access

**Issue**: Tailscale makes Streamlit accessible to all Tailnet members.

**Impact**: All Tailnet members can access the review interface

**Mitigation**:
- Use Tailscale ACLs to restrict access
- Only add trusted team members to Tailnet

---

### SQLite File Permissions

**Issue**: Database file may have overly permissive permissions.

**Impact**: Other system users could read/modify data

**Mitigation**:
```powershell
# Restrict to current user (Windows)
icacls "data/lab_data.db" /inheritance:r /grant:r "$($env:USERNAME):(F)"
```

---

## Future Improvements

### Planned Features

**Currently Under Development:**

1. **Audio Refinement Tab**: Wire up DeepFilterNet UI in Streamlit (placeholder exists)
2. **Reviewer Assignment by Channel**: Currently per-video, expand to channel-level defaults
3. **Automated Download/Chunking Pipeline**: Background job queue for video processing
4. **Improved State Handling**: Unified state machine for all processing steps

**Database Synchronization (Completed - December 2025):**

- ✅ DVC tracking for database version control
- ✅ Automated hourly backups to Google Drive
- ✅ Hybrid sync strategy (backups + DVC snapshots)
- ✅ Team collaboration workflow via Tailscale
- See [`docs/09_database_sync.md`](09_database_sync.md)

**Automation Features (Planned):**

- Automated chunking queue processing
- Batch processing orchestration
- Progress notifications
- Automated quality checks

### Longer-Term Enhancements

1. **Multi-user support**: User authentication and per-user review tracking
2. **Batch review UI**: Review multiple segments simultaneously
3. **Automatic quality metrics**: Calculate and display quality scores
4. **Incremental export**: Export only newly reviewed segments

### Under Consideration

1. **PostgreSQL option**: For larger teams/datasets
2. **Real-time collaboration**: Multiple reviewers on same video
3. **Mobile-friendly review**: Responsive Streamlit layout
4. **Audio waveform visualization**: Visual editing interface
5. **Prompt engineering**: Improve Gemini timestamp accuracy

---

## Reporting Issues

If you encounter issues not documented here:

1. Check [Troubleshooting Guide](04_troubleshooting.md)
2. Verify database integrity: `sqlite3 data/lab_data.db "PRAGMA integrity_check;"`
3. Check logs for error details
4. Document reproduction steps
5. Add to this document if confirmed

---

## Related Documentation

- 📖 [Getting Started](01_getting_started.md) - Setup guide
- 🏗️ [Architecture](02_architecture.md) - Pipeline overview
- 🔧 [Troubleshooting](04_troubleshooting.md) - Common issues
- 📚 [API Reference](05_api_reference.md) - Developer docs

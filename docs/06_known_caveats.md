# Known Caveats & Future Improvements

This document tracks known limitations, edge cases, and areas for future refinement in the Vietnamese-English Code-Switching (CS) Speech Translation pipeline.

---

## 1. Manual Transcript Loss with Gemini-Only Processing

### Issue
When using `gemini_process.py` for transcription, videos with high-quality **manual/human-created YouTube captions** lose this valuable resource. Gemini re-transcribes from audio, potentially missing nuances captured by the original uploader.

### Impact
- Manual captions often contain proper noun spellings, technical terms, and speaker intent.
- Auto-generated + Gemini may introduce transcription errors that manual captions already solved.

### Current Behavior
- `subtitle_type` is tracked in the database (`manual`, `auto_generated`, `none`).
- Gemini processing treats all samples the same regardless of subtitle quality.

### Proposed Solutions
1. **Hybrid Approach**: For `manual` subtitle videos, use YouTube transcript as the base and only use Gemini for:
   - Translation (vi-en → pure vi)
   - Sentence-level timestamping
   - Code-switching normalization

2. **Quality Flag**: Add a flag to `gemini_process.py` like `--preserve-manual-transcript` that:
   - Keeps manual transcript text intact
   - Only uses Gemini for sentence segmentation and translation

3. **Two-Pass Processing**: 
   - Pass 1: Gemini for timestamping only (no transcription)
   - Pass 2: Gemini for translation only

### Priority: **HIGH** - Affects data quality for videos with professional subtitles.

---

## 2. Database Function Signature Conflicts

### Issue
When schema migrations add parameters to existing PostgreSQL functions (e.g., `add_transcript_revision`), the old function signature isn't automatically dropped. This causes "function is not unique" errors.

### Current Workaround
Manually drop the old function:
```sql
DROP FUNCTION add_transcript_revision(uuid, text, varchar, varchar, jsonb, jsonb, varchar);
```

### Proposed Solution
Update migration scripts to use `CREATE OR REPLACE` with explicit `DROP FUNCTION IF EXISTS` for old signatures, or use function overloading carefully.

### Priority: **MEDIUM** - Causes friction during fresh deployments.

---

## 3. Long Audio Chunking Artifacts

### Issue
For videos longer than ~27 minutes (1620s), `gemini_process.py` splits audio into chunks with 18s overlap. Deduplication at chunk boundaries may:
- Miss sentences that span chunk boundaries
- Create duplicate entries if deduplication threshold is imperfect

### Current Behavior
- Adaptive chunking based on audio duration
- Timestamp-based deduplication with fuzzy matching

### Potential Improvements
1. Increase overlap for longer videos
2. Post-process to merge sentences with adjacent timestamps
3. Add confidence scoring for boundary sentences

### Priority: **LOW** - Current deduplication works reasonably well.

---

## 4. Code-Switching Ratio Calculation

### Issue
The CS ratio is calculated from raw YouTube transcripts (auto-generated or manual), which may not accurately reflect actual code-switching after Gemini processing.

### Current Behavior
- CS ratio calculated during ingestion from YouTube transcript
- Not recalculated after Gemini transcription

### Proposed Solution
Recalculate CS ratio from Gemini's transcript output and store both:
- `cs_ratio_original`: From YouTube transcript
- `cs_ratio_processed`: From Gemini transcript

### Priority: **LOW** - Primarily affects data analysis, not training.

---

## 5. YouTube API Rate Limiting

### Issue
`yt-dlp` encounters rate limiting warnings and requires JavaScript runtime for some formats (SABR streaming).

### Current Workaround
- Using fallback audio formats (251 - webm/opus)
- Sleep between downloads

### Potential Improvements
1. Install a JavaScript runtime in Docker (Deno/Node.js)
2. Implement exponential backoff for rate limits
3. Use proxy rotation for large batch ingestion

### Priority: **LOW** - Current setup works for moderate volumes.

---

## 6. Missing Transcript Handling

### Issue
Videos without any transcript (`--no-require-transcript` flag) are downloaded but may have suboptimal Gemini results since there's no reference to guide transcription.

### Current Behavior
- Audio downloaded regardless of transcript availability
- Gemini processes from scratch

### Potential Improvements
1. Add a quality warning in the database for "no original transcript" samples
2. Flag these for extra human review
3. Consider using WhisperX as a pre-processing step for reference

### Priority: **MEDIUM** - Affects quality for transcript-less videos.

---

## 7. Label Studio Setup Automation

### Issue
First-time Label Studio setup requires manual steps:
1. Sign up at localhost:8085
2. Get API token from UI
3. Update `.env` file

### Potential Improvements
1. Add CLI command to automate token retrieval
2. Document in `01_getting_started.md` with screenshots
3. Consider using Label Studio's API for programmatic setup

### Priority: **LOW** - One-time setup, documented in troubleshooting.

---

## Tracking

| Issue | Status | Assigned | Target Version |
|-------|--------|----------|----------------|
| Manual Transcript Loss | Open | - | v3.1 |
| Function Signature Conflicts | Workaround | - | v3.0.1 |
| Long Audio Chunking | Monitoring | - | - |
| CS Ratio Recalculation | Open | - | v3.2 |
| YouTube Rate Limiting | Monitoring | - | - |
| Missing Transcript Quality | Open | - | v3.1 |
| Label Studio Automation | Open | - | v3.2 |

---

*Last updated: 2024-11-30*

# Known Caveats & Future Improvements

This document tracks known limitations, edge cases, and areas for future refinement in the Vietnamese-English Code-Switching (CS) Speech Translation pipeline.

**Audit Summary**: 87 issues identified (8 Critical, 24 High, 32 Medium, 23 Low)

---

# CRITICAL Issues

## 1. Hardcoded Database Credentials

### Issue
Database credentials (`admin:secret_password`) are hardcoded in multiple locations instead of using secure secrets management.

### Affected Files
- `docker-compose.yml` (lines 6-8)
- `setup.ps1` (line 172)
- `db_backup.py` (line 59)
- `db_restore.py` (line 44)

### Impact
- Security breach if repository is public
- Credential exposure in logs and `docker inspect`

### Proposed Solution
1. Move all credentials to `.env` file only
2. Use Docker secrets for production deployments
3. Use `${ENV_VAR}` substitution in docker-compose.yml
4. Verify `.env` is in `.gitignore`

### Priority: **CRITICAL** - Security vulnerability

---

## 2. API Key Exposure

### Issue
Gemini API keys are passed as environment variables and visible in process listings.

### Affected Files
- `docker-compose.yml` (line 58)
- `setup.ps1` (line 196)

### Impact
- API keys visible via `docker inspect`, process listings, logs
- Risk of key theft and abuse

### Proposed Solution
1. Use Docker secrets or volume-mounted secret files
2. Audit all print/logging statements to ensure keys are never logged
3. Implement key rotation policy

### Priority: **CRITICAL** - Security vulnerability

---

## 3. SQL Injection Risk

### Issue
Some database queries use f-string interpolation instead of parameterized queries.

### Affected Files
- `data_utils.py` - `get_review_queue()` function

### Current Behavior
```python
query = f"""SELECT ... WHERE processing_state = '{state}'::processing_state ..."""
```

### Impact
- SQL injection if `state` comes from untrusted source

### Proposed Solution
Use parameterized queries exclusively:
```python
query = """SELECT ... WHERE processing_state = %s::processing_state ..."""
cursor.execute(query, (state,))
```

### Priority: **CRITICAL** - Security vulnerability

---

## 4. Missing Transaction Rollback

### Issue
Some database operations don't properly wrap in try/finally with rollback on failure.

### Affected Files
- `label_studio_sync.py` (lines 330-420)
- `gemini_process.py` (lines 978-1020)

### Impact
- Database left in inconsistent state on partial failures
- Orphaned records, corrupted relationships

### Proposed Solution
Add context managers or explicit try/except/finally blocks:
```python
try:
    cursor.execute(...)
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
```

### Priority: **CRITICAL** - Data integrity risk

---

## 5. No Rate Limit Handling for Label Studio API

### Issue
Label Studio API calls have no retry logic or rate limiting.

### Affected Files
- `label_studio_sync.py` (lines 82-140)

### Impact
- Push/pull operations fail on rate limits
- Potential data loss if sync interrupted

### Proposed Solution
Add retry decorator with exponential backoff:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=60))
def api_call():
    ...
```

### Priority: **CRITICAL** - Operational reliability

---

## 6. Schema Mismatch in db_restore.py

### Issue
`db_restore.py` references columns that don't exist in the current v5 schema.

### Affected Files
- `db_restore.py` (lines 193-240)

### Missing/Wrong Columns
- `parent_sample_id` (doesn't exist)
- `segment_index` (doesn't exist)
- `linguistic_metadata` (doesn't exist)

### Impact
- **Database restore will completely fail**
- No disaster recovery capability

### Proposed Solution
Update `db_restore.py` to match v5 schema exactly. Test restore process.

### Priority: **CRITICAL** - Disaster recovery broken

---

## 7. Transcript Revision Schema Mismatch

### Issue
`db_restore.py` references `timestamps` column which doesn't exist (should be `start_time_ms` and `end_time_ms`).

### Affected Files
- `db_restore.py` (lines 310-335)

### Impact
- Transcript revision restore fails

### Proposed Solution
Update column names to match current schema.

### Priority: **CRITICAL** - Disaster recovery broken

---

## 8. No Audio File Integrity Validation

### Issue
Downloaded audio files are used without verifying they downloaded correctly.

### Affected Files
- `video_downloading_utils.py`
- `gemini_process.py`

### Impact
- Corrupted audio leads to garbage transcriptions
- Wasted Gemini API costs
- Bad data in training set

### Proposed Solution
1. Add MD5/SHA checksum validation after download
2. Verify audio loads correctly before processing
3. Add file size sanity check

### Priority: **CRITICAL** - Data quality risk

---

# HIGH Issues

## 9. No Database Connection Pooling

### Issue
Creates new database connection for every operation.

### Affected Files
- `data_utils.py` - `get_pg_connection()`

### Impact
- Connection exhaustion under load
- Slow operations due to connection overhead

### Proposed Solution
Implement connection pooling:
```python
from psycopg2.pool import ThreadedConnectionPool
pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
```

### Priority: **HIGH** - Scalability bottleneck

---

## 10. Gemini API Key Rotation Logic Broken

### Issue
`_get_current_api_key()` always returns the first key; counter never decrements.

### Affected Files
- `gemini_process.py` (lines 307-340)

### Impact
- No actual key rotation
- Single key gets rate limited while others unused

### Proposed Solution
Implement actual rotation with file/database-based counter or round-robin.

### Priority: **HIGH** - API reliability

---

## 11. No Database Connection Timeout

### Issue
No `connect_timeout` specified in connection string.

### Affected Files
- `data_utils.py`

### Impact
- Script hangs indefinitely if database unreachable

### Proposed Solution
Add timeout: `connect_timeout=10` to connection parameters.

### Priority: **HIGH** - Operational reliability

---

## 12. Temp Directory Cleanup on Failure

### Issue
Temporary chunk directory cleanup only happens on success path.

### Affected Files
- `gemini_process.py` (lines 458-500)

### Impact
- Disk fills up with orphaned chunks on failures

### Proposed Solution
Use `tempfile.TemporaryDirectory` context manager:
```python
with tempfile.TemporaryDirectory() as temp_dir:
    # processing...
```

### Priority: **HIGH** - Resource leak

---

## 13. Missing Timestamp Validation

### Issue
No validation that sentence timestamps are sequential, non-overlapping, and within audio duration.

### Affected Files
- `gemini_process.py` (lines 797-830)

### Impact
- Invalid timestamp data propagates to training data
- Audio slicing fails or produces garbage

### Proposed Solution
Add validation function:
```python
def validate_timestamps(sentences, audio_duration):
    for i, s in enumerate(sentences):
        assert s['start'] < s['end']
        assert s['end'] <= audio_duration
        if i > 0:
            assert s['start'] >= sentences[i-1]['end']
```

### Priority: **HIGH** - Data quality

---

## 14. Race Condition in Batch Processing

### Issue
Multiple instances can process the same samples simultaneously.

### Affected Files
- `gemini_process.py` (lines 1200-1250)
- `prepare_review_audio.py` (lines 240-280)

### Impact
- Duplicate processing
- Database conflicts
- Wasted API calls

### Proposed Solution
Use `SELECT FOR UPDATE SKIP LOCKED`:
```sql
SELECT * FROM samples 
WHERE processing_state = 'RAW' 
FOR UPDATE SKIP LOCKED 
LIMIT 1;
```

### Priority: **HIGH** - Concurrency issue

---

## 15. DVC Push Without Commit Verification

### Issue
`dvc push` runs without verifying local changes are committed.

### Affected Files
- `sync_daemon.py` (lines 95-125)

### Impact
- Inconsistent state between git and DVC

### Proposed Solution
Check `git status --porcelain` before push.

### Priority: **HIGH** - Data consistency

---

## 16. Large Task Data May Exceed Label Studio Limits

### Issue
Entire HTML table for all sentences embedded in task data.

### Affected Files
- `label_studio_sync.py` (lines 425-480)

### Impact
- Samples with 100+ sentences may exceed payload limits
- Task creation fails silently

### Proposed Solution
Paginate large samples or use external storage.

### Priority: **HIGH** - Functional limitation

---

## 17. No Graceful Shutdown for sync_daemon

### Issue
`while True` loop with no signal handling.

### Affected Files
- `sync_daemon.py` (lines 275-310)

### Impact
- Data loss if killed during sync operation

### Proposed Solution
Add SIGTERM/SIGINT handlers:
```python
import signal
running = True
def handler(sig, frame):
    global running
    running = False
signal.signal(signal.SIGTERM, handler)
```

### Priority: **HIGH** - Operational reliability

---

## 18. No Sample Locking Before Processing

### Issue
No `locked_at`/`locked_by` columns set before processing begins.

### Affected Files
- `gemini_process.py` (lines 1050-1100)

### Impact
- Multiple workers can process same sample

### Proposed Solution
Set lock columns before processing, clear on completion/failure.

### Priority: **HIGH** - Concurrency issue

---

## 19. yt-dlp No Cookie Support

### Issue
No cookie support for age-restricted or region-locked videos.

### Affected Files
- `video_downloading_utils.py`

### Impact
- Cannot download restricted content

### Proposed Solution
Add `cookiefile` option pointing to browser cookies.

### Priority: **HIGH** - Functional limitation

---

## 20. No Review Decision Validation

### Issue
Decision values parsed without validation.

### Affected Files
- `label_studio_sync.py` (lines 350-380)

### Impact
- Invalid state transitions, data corruption

### Proposed Solution
Validate decision is in `['approve', 'reject', 'needs_revision']`.

### Priority: **HIGH** - Data integrity

---

## 21. Missing Audio Format Validation

### Issue
Assumes audio is WAV without validation.

### Affected Files
- `prepare_review_audio.py` (lines 70-80)

### Impact
- Crash if audio is different format

### Proposed Solution
Check format and convert if needed.

### Priority: **HIGH** - Robustness

---

## 22. Database Enum Updates Unsafe

### Issue
`DROP TYPE ... CASCADE` drops all dependent data.

### Affected Files
- `init_scripts/01_schema.sql` (lines 15-25)

### Impact
- Data loss during schema migration

### Proposed Solution
Use `ALTER TYPE ... ADD VALUE` for enum changes instead of drop/recreate.

### Priority: **HIGH** - Data safety

---

## 23. No Retry Logic for pydub Operations

### Issue
Audio file operations can fail on file lock issues (especially Windows).

### Affected Files
- `prepare_review_audio.py`
- `apply_review.py`

### Impact
- Batch processing fails completely on transient errors

### Proposed Solution
Add retry decorator for file I/O operations.

### Priority: **HIGH** - Windows compatibility

---

## 24. Hardcoded Port Numbers

### Issue
Ports 5433, 8085, 8081 hardcoded in multiple places.

### Affected Files
- `docker-compose.yml`
- `setup.ps1`
- Label Studio template

### Impact
- Port conflicts difficult to resolve

### Proposed Solution
Define all ports in `.env` and reference via `${VAR}`.

### Priority: **HIGH** - Configuration flexibility

---

## 25. No Backup Before Review File Deletion

### Issue
`shutil.rmtree` without backup in apply_review.py.

### Affected Files
- `apply_review.py` (lines 225-230)

### Impact
- No recovery if apply_review fails after deletion

### Proposed Solution
Move to archive directory instead of delete, or backup before apply.

### Priority: **HIGH** - Data safety

---

## 26. Missing Unicode Normalization

### Issue
No NFC/NFD normalization for Vietnamese diacritics.

### Affected Files
- `text_utils.py`

### Impact
- Inconsistent text comparison
- Duplicate detection fails

### Proposed Solution
Apply `unicodedata.normalize('NFC', text)` consistently.

### Priority: **HIGH** - Data quality

---

## 27. Gemini Response Parsing Vulnerability

### Issue
Regex extraction of JSON from markdown blocks without strict validation.

### Affected Files
- `gemini_process.py` (lines 710-730)

### Impact
- Malformed responses could cause crashes or incorrect parsing

### Proposed Solution
Add strict JSON validation and fallback handling.

### Priority: **HIGH** - Robustness

---

## 28. Unbounded Memory in Export

### Issue
All sentences loaded into memory before export.

### Affected Files
- `export_reviewed.py` (lines 160-200)

### Impact
- Memory exhaustion with large datasets

### Proposed Solution
Use streaming/generator approach for export.

### Priority: **HIGH** - Scalability

---

## 29. Missing Composite Database Index

### Issue
Queries filter by `processing_state` and `is_deleted` but index may not cover both.

### Affected Files
- `init_scripts/01_schema.sql`

### Impact
- Slow queries as data grows

### Proposed Solution
Add composite index: `(processing_state, is_deleted, priority DESC, created_at ASC)`.

### Priority: **HIGH** - Performance

---

## 30. YouTube Transcript API Version Dependency

### Issue
Uses instance method API that may change with library updates.

### Affected Files
- `transcript_downloading_utils.py`

### Impact
- May break with library updates

### Proposed Solution
Pin version in requirements.txt or use static methods.

### Priority: **HIGH** - Stability

---

## 31. Missing Error Recovery for Partial Annotation Saves

### Issue
If `pull_annotations` fails midway, partial updates may be committed.

### Affected Files
- `label_studio_sync.py` (lines 290-380)

### Impact
- Inconsistent review data

### Proposed Solution
Wrap entire save operation in single transaction.

### Priority: **HIGH** - Data integrity

---

## 32. No Health Check for Ingestion Service

### Issue
No healthcheck defined for ingestion container.

### Affected Files
- `docker-compose.yml` (lines 85-100)

### Impact
- No way to detect if service is functioning

### Proposed Solution
Add healthcheck or readiness probe.

### Priority: **HIGH** - Monitoring

---

# MEDIUM Issues

## 33. Magic Numbers Throughout Codebase

### Issue
Hardcoded values like `MAX_AUDIO_DURATION_SECONDS=1200`, `CHUNK_OVERLAP_SECONDS=20` scattered in code.

### Affected Files
- `gemini_process.py` (lines 57, 63)
- Various preprocessing scripts

### Proposed Solution
Move to central `config.py` file.

### Priority: **MEDIUM** - Maintainability

---

## 34. Inconsistent Timestamp Units

### Issue
Gemini returns seconds, database stores milliseconds in some places.

### Impact
- Confusion and potential bugs in conversion

### Proposed Solution
Standardize on milliseconds everywhere with clear naming (`_ms` suffix).

### Priority: **MEDIUM** - Data consistency

---

## 35. No Structured Logging

### Issue
Uses `print()` statements instead of Python logging module.

### Impact
- No log levels, no log rotation, no structured logging
- Difficult to debug production issues

### Proposed Solution
Implement Python logging with file rotation:
```python
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
```

### Priority: **MEDIUM** - Operations

---

## 36. Missing CLI Argument Validation

### Issue
UUID format not validated for `--sample-id` arguments.

### Impact
- Cryptic error messages for invalid input

### Proposed Solution
Add UUID format validation in argparse.

### Priority: **MEDIUM** - User experience

---

## 37. CS Ratio Not Recalculated After Processing

### Issue
CS ratio calculated from YouTube transcript, not updated after Gemini processing.

### Current Status
Already documented in original caveats.

### Proposed Solution
Add `cs_ratio_gemini` column and calculate from processed text.

### Priority: **MEDIUM** - Data quality

---

## 38. Weak Default Passwords

### Issue
Default passwords `admin123`, `annotate123` in setup script.

### Affected Files
- `setup.ps1` (line 350)

### Impact
- Easy to guess credentials

### Proposed Solution
Generate random passwords, require change on first login.

### Priority: **MEDIUM** - Security

---

## 39. Missing Database Indexes for Common Queries

### Issue
Missing indexes on `external_id`, `created_at` columns.

### Impact
- Slow lookups as data grows

### Proposed Solution
Add indexes based on query patterns from actual usage.

### Priority: **MEDIUM** - Performance

---

## 40. No Processing Log Retention Policy

### Issue
`processing_logs` table grows indefinitely.

### Impact
- Database bloat over time

### Proposed Solution
Add retention policy - archive logs older than 90 days.

### Priority: **MEDIUM** - Operations

---

## 41. No Database Migration System

### Issue
Single SQL file, no versioned migrations.

### Impact
- Schema changes require manual intervention
- No rollback capability

### Proposed Solution
Implement migration system (Alembic or Flyway).

### Priority: **MEDIUM** - DevOps

---

## 42. No Metrics Collection

### Issue
No metrics for processing times, error rates, throughput.

### Impact
- No visibility into system health

### Proposed Solution
Add Prometheus metrics or structured logging for analysis.

### Priority: **MEDIUM** - Operations

---

## 43. PowerShell-Only Setup Script

### Issue
`setup.ps1` only works on Windows.

### Impact
- Cannot use on Linux/Mac development machines

### Proposed Solution
Add bash equivalent (`setup.sh`) or Python setup script.

### Priority: **MEDIUM** - Developer experience

---

## 44. Missing Data Integrity Constraints

### Issue
No CHECK constraints on durations, ratios in database.

### Impact
- Invalid data can be inserted (negative durations, ratio > 1)

### Proposed Solution
Add constraints:
```sql
CHECK (duration_seconds > 0)
CHECK (cs_ratio BETWEEN 0 AND 1)
```

### Priority: **MEDIUM** - Data integrity

---

## 45. Manual Transcript Loss with Gemini-Only Processing

### Current Status
Already documented in original caveats (#1).

### Priority: **HIGH** - Data quality

---

## 46. Missing Transcript Handling Quality

### Current Status
Already documented in original caveats (#6).

### Priority: **MEDIUM** - Data quality

---

## 47-64. Additional Medium Issues

- No validation of Label Studio template XML
- Missing audio duration validation before slicing
- Database connection not closed on exception in some paths
- No maximum sentence length validation (>60s sentences)
- Missing chunk overlap validation against minimum chunk size
- No HTTPS for audio server (HTTP only)
- Missing backup before schema drop in init scripts
- No validation of translation quality (length ratio, character checks)
- Missing error categorization in processing_logs
- No circuit breaker for external APIs
- Incomplete JSONB column indexing (missing GIN indexes)
- No Content-Length header validation for HTTP responses
- Temporary file handling issues on Windows
- No deduplication of ingested videos by external_id only
- No audio sample rate validation (assumes 16kHz)
- Missing request ID tracking for debugging
- No concurrent export protection

### Priority: **MEDIUM** - Various improvements needed

---

# LOW Issues

## 65. No Unit Tests

### Issue
No test directory or test files in the project.

### Impact
- No automated verification of functionality
- Regressions go unnoticed

### Proposed Solution
Add pytest with coverage:
```
tests/
├── test_data_utils.py
├── test_gemini_process.py
├── test_text_utils.py
└── conftest.py
```

### Priority: **LOW** (but should be HIGH for production)

---

## 66. Missing .dockerignore

### Issue
No `.dockerignore` file.

### Impact
- Larger Docker context, slower builds
- Potential secret exposure

### Proposed Solution
Add `.dockerignore` with `.env`, `database_data/`, `__pycache__/`, `.git/`.

### Priority: **LOW** - Build optimization

---

## 67. No Pre-commit Hooks

### Issue
No `.pre-commit-config.yaml` for code quality.

### Impact
- Inconsistent code style
- Linting issues discovered late

### Proposed Solution
Add pre-commit hooks for black, isort, flake8.

### Priority: **LOW** - Developer experience

---

## 68. No Container Resource Limits

### Issue
No CPU/memory limits in docker-compose.yml.

### Impact
- Runaway containers can exhaust host resources

### Proposed Solution
Add `deploy.resources.limits` configuration.

### Priority: **LOW** - Operations

---

## 69. Missing Container Log Configuration

### Issue
Uses Docker default logging (unbounded).

### Impact
- Logs can grow unbounded

### Proposed Solution
Add `logging` configuration with max-size.

### Priority: **LOW** - Operations

---

## 70-87. Additional Low Issues

- Missing type hints in some functions
- Inconsistent docstring format
- Hardcoded file extensions (`.wav`)
- Missing `__all__` exports in modules
- Changelog may be outdated
- Unused imports in some files
- Missing API documentation (Sphinx)
- Some packages not version-pinned in requirements.txt
- No `requirements-dev.txt` for dev dependencies
- Inconsistent naming conventions in places
- No configuration validation on startup
- Missing `.gitkeep` files for required empty directories
- No Makefile for common operations
- Verbose debug output always enabled
- No data retention policy documentation
- Missing health dashboard
- No copyright/license headers in source files
- No `CONTRIBUTING.md` guidelines

### Priority: **LOW** - Polish items

---

# Previously Documented Issues

## Long Audio Chunking Artifacts
**Status**: Monitoring  
**Original**: Caveat #3  
**Note**: Updated threshold to 20 minutes (was 27 minutes) per code changes.

## Database Function Signature Conflicts
**Status**: Workaround available  
**Original**: Caveat #2

## YouTube API Rate Limiting
**Status**: Monitoring  
**Original**: Caveat #5

## Label Studio Setup Automation
**Status**: Resolved  
**Original**: Caveat #7  
**Note**: `setup.ps1` now automates user creation and API token retrieval.

---

# Tracking

| # | Issue | Severity | Status | Target |
|---|-------|----------|--------|--------|
| 1 | Hardcoded DB Credentials | CRITICAL | Open | v3.0.2 |
| 2 | API Key Exposure | CRITICAL | Open | v3.0.2 |
| 3 | SQL Injection Risk | CRITICAL | Open | v3.0.2 |
| 4 | Missing Transaction Rollback | CRITICAL | Open | v3.0.2 |
| 5 | No Label Studio Rate Limit | CRITICAL | Open | v3.0.2 |
| 6 | db_restore Schema Mismatch | CRITICAL | Open | v3.0.2 |
| 7 | Transcript Revision Mismatch | CRITICAL | Open | v3.0.2 |
| 8 | No Audio Integrity Check | CRITICAL | Open | v3.0.2 |
| 9-32 | HIGH Issues (24) | HIGH | Open | v3.1 |
| 33-64 | MEDIUM Issues (32) | MEDIUM | Open | v3.2 |
| 65-87 | LOW Issues (23) | LOW | Open | v4.0 |

---

# Remediation Priority

## Immediate (Before Production)
1. Fix hardcoded credentials (#1, #2)
2. Fix SQL injection (#3)
3. Fix db_restore schema mismatch (#6, #7)
4. Add transaction handling (#4, #31)
5. Add audio validation (#8)

## Short-term (1-2 weeks)
1. Add database connection pooling (#9)
2. Fix API key rotation (#10)
3. Add race condition protection (#14, #18)
4. Add graceful shutdown (#17)
5. Add Label Studio rate limiting (#5)

## Medium-term (1-2 months)
1. Implement migrations system (#41)
2. Add comprehensive logging (#35)
3. Add metrics collection (#42)
4. Add unit tests (#65)
5. Add circuit breakers (#48)

---

*Last updated: 2025-11-30*  
*Audit version: 2.0 (comprehensive review)*

-- =============================================================================
-- SQLite Schema for NLP Pipeline (v1)
-- =============================================================================
-- Simplified schema for E2E Speech Translation pipeline.
-- Tables: videos (metadata) + segments (training data)
-- =============================================================================

-- Enable WAL mode for better concurrency (run this after connecting)
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;

-- =============================================================================
-- VIDEOS TABLE
-- =============================================================================
-- Stores metadata about each video/audio source.

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,                      -- YouTube video ID or custom ID for uploads
    url TEXT,                                       -- Source URL (NULL for manual uploads)
    title TEXT NOT NULL,
    channel_name TEXT,                              -- YouTube channel or uploader name
    reviewer TEXT,                                  -- Assigned reviewer (per video)
    duration_seconds REAL NOT NULL,                 -- Total audio duration
    audio_path TEXT NOT NULL,                       -- Relative path to audio file
    denoised_audio_path TEXT,                       -- Path to denoised audio (if processed)
    
    -- Processing state: pending -> transcribed -> reviewed -> exported
    processing_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_state IN ('pending', 'transcribed', 'reviewed', 'exported', 'rejected')),
    
    -- Metadata
    source_type TEXT NOT NULL DEFAULT 'youtube'
        CHECK (source_type IN ('youtube', 'upload')),
    upload_metadata TEXT,                           -- JSON: original filename, uploader, etc.
    
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index for filtering by state
CREATE INDEX IF NOT EXISTS idx_videos_state ON videos(processing_state);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);


-- =============================================================================
-- SEGMENTS TABLE
-- =============================================================================
-- Stores sentence-level transcription and translation data.
-- Each segment maps to a portion of a video's audio.

CREATE TABLE IF NOT EXISTS segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    chunk_id INTEGER REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,                 -- Order within video (0-indexed)
    
    -- Timestamps in milliseconds for precision
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    
    -- Original AI-generated content
    transcript TEXT NOT NULL,                       -- Original code-switched transcript
    translation TEXT NOT NULL,                      -- Vietnamese translation
    
    -- Reviewed content (NULL until reviewed)
    reviewed_transcript TEXT,
    reviewed_translation TEXT,
    reviewed_start_ms INTEGER,
    reviewed_end_ms INTEGER,
    
    -- Review status
    is_reviewed BOOLEAN NOT NULL DEFAULT 0,
    is_rejected BOOLEAN NOT NULL DEFAULT 0,
    reviewer_notes TEXT,                            -- Optional notes from reviewer
    
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT,
    
    -- Constraints
    UNIQUE (video_id, segment_index),
    CHECK (end_ms > start_ms),
    CHECK (reviewed_end_ms IS NULL OR reviewed_end_ms > reviewed_start_ms)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_segments_video ON segments(video_id);
CREATE INDEX IF NOT EXISTS idx_segments_chunk ON segments(chunk_id);
CREATE INDEX IF NOT EXISTS idx_segments_reviewed ON segments(is_reviewed);
CREATE INDEX IF NOT EXISTS idx_segments_rejected ON segments(is_rejected);


-- =============================================================================
-- CHUNKS TABLE
-- =============================================================================
-- Optional table to track chunked audio files derived from long sources.

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    audio_path TEXT NOT NULL,
    processing_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_state IN ('pending', 'transcribed', 'reviewed', 'exported', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(video_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id);


-- =============================================================================
-- TRIGGER: Auto-update updated_at on videos
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_videos_updated_at
AFTER UPDATE ON videos
FOR EACH ROW
BEGIN
    UPDATE videos SET updated_at = datetime('now') WHERE video_id = OLD.video_id;
END;


-- =============================================================================
-- VIEWS
-- =============================================================================

-- View: Videos with segment counts and review progress
CREATE VIEW IF NOT EXISTS v_video_progress AS
SELECT 
    v.video_id,
    v.title,
    v.duration_seconds,
    v.processing_state,
    v.source_type,
    v.created_at,
    COUNT(s.segment_id) AS total_segments,
    SUM(CASE WHEN s.is_reviewed = 1 THEN 1 ELSE 0 END) AS reviewed_segments,
    SUM(CASE WHEN s.is_rejected = 1 THEN 1 ELSE 0 END) AS rejected_segments,
    ROUND(
        100.0 * SUM(CASE WHEN s.is_reviewed = 1 THEN 1 ELSE 0 END) / 
        NULLIF(COUNT(s.segment_id), 0), 
        1
    ) AS review_percent
FROM videos v
LEFT JOIN segments s ON v.video_id = s.video_id
GROUP BY v.video_id;


-- View: Segments ready for export (reviewed, not rejected)
CREATE VIEW IF NOT EXISTS v_export_ready AS
SELECT 
    s.segment_id,
    s.video_id,
    v.title AS video_title,
    v.audio_path,
    v.denoised_audio_path,
    s.segment_index,
    COALESCE(s.reviewed_start_ms, s.start_ms) AS start_ms,
    COALESCE(s.reviewed_end_ms, s.end_ms) AS end_ms,
    COALESCE(s.reviewed_end_ms, s.end_ms) - COALESCE(s.reviewed_start_ms, s.start_ms) AS duration_ms,
    COALESCE(s.reviewed_transcript, s.transcript) AS transcript,
    COALESCE(s.reviewed_translation, s.translation) AS translation
FROM segments s
JOIN videos v ON s.video_id = v.video_id
WHERE s.is_reviewed = 1 
  AND s.is_rejected = 0
  AND v.processing_state = 'reviewed';


-- View: Segments with duration warnings (>25 seconds)
CREATE VIEW IF NOT EXISTS v_long_segments AS
SELECT 
    s.segment_id,
    s.video_id,
    v.title AS video_title,
    s.segment_index,
    COALESCE(s.reviewed_start_ms, s.start_ms) AS start_ms,
    COALESCE(s.reviewed_end_ms, s.end_ms) AS end_ms,
    (COALESCE(s.reviewed_end_ms, s.end_ms) - COALESCE(s.reviewed_start_ms, s.start_ms)) / 1000.0 AS duration_seconds,
    s.transcript,
    s.is_reviewed
FROM segments s
JOIN videos v ON s.video_id = v.video_id
WHERE (COALESCE(s.reviewed_end_ms, s.end_ms) - COALESCE(s.reviewed_start_ms, s.start_ms)) > 25000
  AND s.is_rejected = 0;

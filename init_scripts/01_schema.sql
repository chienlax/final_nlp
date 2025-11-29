-- =============================================================================
-- init_scripts/03_schema_v3.sql
-- PostgreSQL Schema v3 for Vietnamese-English CS Speech Translation Pipeline
-- 
-- SIMPLIFIED PIPELINE (YouTube-only with human-in-the-loop):
--   RAW → TRANSCRIPT_REVIEW → TRANSCRIPT_VERIFIED → ALIGNED → SEGMENTED 
--       → SEGMENT_REVIEW → SEGMENT_VERIFIED → TRANSLATED → TRANSLATION_REVIEW 
--       → DENOISED → FINAL
--
-- Key Changes from v2:
--   1. Removed Substack/TTS pipeline (text-first)
--   2. Added explicit subtitle_type tracking (manual vs auto-generated)
--   3. Added segments table for audio chunks with word-level timestamps
--   4. Added segment_translations for per-segment translation storage
--   5. Simplified processing states for human-review workflow
-- =============================================================================

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

-- Drop old types
DROP TYPE IF EXISTS source_type CASCADE;
DROP TYPE IF EXISTS processing_state CASCADE;
DROP TYPE IF EXISTS content_type CASCADE;
DROP TYPE IF EXISTS annotation_task CASCADE;
DROP TYPE IF EXISTS annotation_status CASCADE;
DROP TYPE IF EXISTS subtitle_type CASCADE;

-- Pipeline source types (YouTube only)
CREATE TYPE source_type AS ENUM (
    'youtube_manual_transcript',    -- Has human-created captions
    'youtube_auto_transcript',      -- Only auto-generated captions
    'manual_upload'                 -- Direct file upload
);

-- Subtitle type for YouTube videos
CREATE TYPE subtitle_type AS ENUM (
    'manual',           -- Human-created captions
    'auto_generated',   -- YouTube auto-generated
    'none'              -- No transcript available (reject these)
);

-- Processing states for human-in-the-loop pipeline
CREATE TYPE processing_state AS ENUM (
    'RAW',                  -- Just crawled, raw transcript
    'TRANSCRIPT_REVIEW',    -- In Label Studio for transcript correction
    'TRANSCRIPT_VERIFIED',  -- Transcript reviewed and corrected
    'ALIGNED',              -- WhisperX alignment complete (word timestamps)
    'SEGMENTED',            -- Audio segmented into 10-30s chunks
    'SEGMENT_REVIEW',       -- In Label Studio for segment boundary verification
    'SEGMENT_VERIFIED',     -- Segments verified and ready for translation
    'TRANSLATED',           -- Gemini translation complete (draft)
    'TRANSLATION_REVIEW',   -- In Label Studio for translation review
    'DENOISED',             -- DeepFilterNet noise removal complete
    'FINAL',                -- All reviews passed, ready for training
    'REJECTED'              -- Failed QC, excluded from training
);

-- Content type
CREATE TYPE content_type AS ENUM (
    'audio_primary',    -- Full video audio
    'audio_segment'     -- Segmented audio chunk
);

-- Annotation task types for Label Studio
CREATE TYPE annotation_task AS ENUM (
    'transcript_correction',     -- Round 1: Fix raw transcript typos
    'segment_verification',      -- Round 2: Verify segment boundaries
    'translation_review'         -- Round 3: Verify audio/transcript/translation match
);

-- Annotation status
CREATE TYPE annotation_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'skipped',
    'disputed'
);

-- =============================================================================
-- TABLE: sources
-- Purpose: Track YouTube channels
-- =============================================================================

DROP TABLE IF EXISTS sources CASCADE;
CREATE TABLE sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source identification
    source_type source_type NOT NULL,
    external_id VARCHAR(255),           -- YouTube channel ID
    name VARCHAR(500),                  -- Channel name
    url TEXT,                           -- Channel URL
    
    -- Metadata
    metadata JSONB DEFAULT '{}',        -- Subscriber count, language, etc.
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (source_type, external_id)
);

CREATE INDEX idx_sources_type ON sources(source_type);

-- =============================================================================
-- TABLE: samples
-- Purpose: Full YouTube videos (parent samples)
-- =============================================================================

DROP TABLE IF EXISTS samples CASCADE;
CREATE TABLE samples (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    source_id UUID REFERENCES sources(source_id) ON DELETE SET NULL,
    
    -- Content identification
    external_id VARCHAR(255) NOT NULL,  -- YouTube video ID
    content_type content_type NOT NULL DEFAULT 'audio_primary',
    
    -- File references
    audio_file_path TEXT NOT NULL,      -- Path to WAV file (data/raw/audio/{video_id}.wav)
    text_file_path TEXT,                -- Path to raw transcript JSON
    
    -- YouTube subtitle info
    subtitle_type subtitle_type NOT NULL,
    subtitle_language VARCHAR(10),      -- 'en', 'vi', etc.
    
    -- Processing pipeline
    pipeline_type source_type NOT NULL,
    processing_state processing_state NOT NULL DEFAULT 'RAW',
    
    -- Current versions
    current_transcript_version INTEGER DEFAULT 0,
    current_translation_version INTEGER DEFAULT 0,
    
    -- Audio metadata
    duration_seconds NUMERIC(10, 2),
    sample_rate INTEGER DEFAULT 16000,
    
    -- Linguistic metadata
    cs_ratio NUMERIC(5, 4),             -- Code-switching ratio (0.0 to 1.0)
    detected_languages JSONB DEFAULT '["vi", "en"]',
    
    -- Flexible metadata
    source_metadata JSONB DEFAULT '{}', -- URL, upload date, title, channel info
    acoustic_metadata JSONB DEFAULT '{}', -- Audio properties
    processing_metadata JSONB DEFAULT '{}', -- WhisperX params, etc.
    
    -- Quality & priority
    quality_score NUMERIC(3, 2),        -- 0.00 to 1.00
    priority INTEGER DEFAULT 0,         -- Higher = more urgent
    
    -- Label Studio integration
    label_studio_task_id INTEGER,
    
    -- DVC sync tracking
    dvc_commit_hash VARCHAR(40),
    audio_file_md5 VARCHAR(32),
    sync_version INTEGER DEFAULT 1,
    
    -- Annotation locking
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(255),
    
    -- Gold standard for QC
    is_gold_standard BOOLEAN DEFAULT FALSE,
    gold_score NUMERIC(3, 2),
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    
    -- Soft delete
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_samples_state ON samples(processing_state) WHERE is_deleted = FALSE;
CREATE INDEX idx_samples_pipeline ON samples(pipeline_type, processing_state);
CREATE INDEX idx_samples_external_id ON samples(external_id);
CREATE INDEX idx_samples_source ON samples(source_id);
CREATE INDEX idx_samples_subtitle ON samples(subtitle_type);
CREATE INDEX idx_samples_priority ON samples(priority DESC, created_at ASC) WHERE is_deleted = FALSE;

-- =============================================================================
-- TABLE: segments
-- Purpose: Audio chunks (10-30s) derived from parent samples
-- =============================================================================

DROP TABLE IF EXISTS segments CASCADE;
CREATE TABLE segments (
    segment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Parent relationship
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Segment ordering
    segment_index INTEGER NOT NULL,     -- 0-based index within parent
    
    -- Timing (from WhisperX alignment)
    start_time_ms INTEGER NOT NULL,     -- Start in milliseconds
    end_time_ms INTEGER NOT NULL,       -- End in milliseconds
    duration_ms INTEGER GENERATED ALWAYS AS (end_time_ms - start_time_ms) STORED,
    
    -- File reference
    audio_file_path TEXT,               -- data/segments/{sample_id}/{segment_index}.wav
    
    -- Word-level alignment (from WhisperX)
    word_timestamps JSONB,              -- [{word, start, end, score}, ...]
    
    -- Transcript for this segment
    transcript_text TEXT,               -- Verified transcript for this segment
    
    -- Processing state (inherits from parent but can have segment-specific issues)
    is_verified BOOLEAN DEFAULT FALSE,  -- Segment boundary verified in Label Studio
    has_issues BOOLEAN DEFAULT FALSE,   -- Flagged for re-review
    issue_notes TEXT,                   -- Notes about issues
    
    -- Quality
    alignment_score NUMERIC(5, 4),      -- Average word alignment confidence
    
    -- Label Studio
    label_studio_task_id INTEGER,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (sample_id, segment_index)
);

CREATE INDEX idx_segments_sample ON segments(sample_id, segment_index);
CREATE INDEX idx_segments_verified ON segments(is_verified) WHERE is_verified = FALSE;
CREATE INDEX idx_segments_issues ON segments(has_issues) WHERE has_issues = TRUE;

-- =============================================================================
-- TABLE: transcript_revisions
-- Purpose: Immutable audit trail for transcript changes (sample-level)
-- =============================================================================

DROP TABLE IF EXISTS transcript_revisions CASCADE;
CREATE TABLE transcript_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Version tracking
    version INTEGER NOT NULL,
    
    -- Content (full transcript for the whole video)
    transcript_text TEXT NOT NULL,
    
    -- Revision metadata
    revision_type VARCHAR(50) NOT NULL, -- 'youtube_raw', 'human_corrected', 'whisperx_aligned'
    revision_source VARCHAR(100),       -- 'youtube_api', 'annotator_email', 'whisperx'
    
    -- Word-level timestamps (from WhisperX alignment)
    word_timestamps JSONB,              -- [{word, start, end, score}, ...]
    
    -- Sentence-level timestamps (for segmentation)
    sentence_timestamps JSONB,          -- [{text, start, end, words: [...]}, ...]
    
    -- Metadata
    metadata JSONB DEFAULT '{}',        -- Model version, confidence, etc.
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);

CREATE INDEX idx_transcript_rev_sample ON transcript_revisions(sample_id, version DESC);
CREATE INDEX idx_transcript_rev_type ON transcript_revisions(revision_type);

-- =============================================================================
-- TABLE: translation_revisions
-- Purpose: Immutable audit trail for translations (sample-level, full transcript)
-- =============================================================================

DROP TABLE IF EXISTS translation_revisions CASCADE;
CREATE TABLE translation_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Version tracking
    version INTEGER NOT NULL,
    
    -- Source transcript reference
    source_transcript_revision_id UUID REFERENCES transcript_revisions(revision_id),
    
    -- Content (full translation for the whole video)
    translation_text TEXT NOT NULL,
    source_language VARCHAR(10) DEFAULT 'vi-en',  -- Code-switched source
    target_language VARCHAR(10) NOT NULL DEFAULT 'vi',  -- Pure Vietnamese target
    
    -- Revision metadata
    revision_type VARCHAR(50) NOT NULL, -- 'gemini_draft', 'human_corrected', 'final'
    revision_source VARCHAR(100),       -- 'gemini-1.5-pro', 'annotator_email'
    
    -- Sentence-level translations (for mapping to segments)
    sentence_translations JSONB,        -- [{source, translation, segment_index}, ...]
    
    -- Quality metrics
    confidence_score NUMERIC(5, 4),
    
    -- API tracking
    api_model VARCHAR(100),             -- 'gemini-1.5-pro', 'gemini-1.5-flash'
    api_cost_usd NUMERIC(10, 6),        -- Estimated cost
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);

CREATE INDEX idx_translation_rev_sample ON translation_revisions(sample_id, version DESC);
CREATE INDEX idx_translation_rev_type ON translation_revisions(revision_type);

-- =============================================================================
-- TABLE: segment_translations
-- Purpose: Per-segment translations (derived from full translation)
-- =============================================================================

DROP TABLE IF EXISTS segment_translations CASCADE;
CREATE TABLE segment_translations (
    segment_translation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    segment_id UUID NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
    translation_revision_id UUID NOT NULL REFERENCES translation_revisions(revision_id) ON DELETE CASCADE,
    
    -- Content
    source_text TEXT NOT NULL,          -- Transcript for this segment
    translation_text TEXT NOT NULL,     -- Translation for this segment
    
    -- Verification
    is_verified BOOLEAN DEFAULT FALSE,  -- Human verified in Label Studio
    has_issues BOOLEAN DEFAULT FALSE,
    issue_notes TEXT,
    
    -- Label Studio
    label_studio_task_id INTEGER,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (segment_id, translation_revision_id)
);

CREATE INDEX idx_seg_trans_segment ON segment_translations(segment_id);
CREATE INDEX idx_seg_trans_revision ON segment_translations(translation_revision_id);
CREATE INDEX idx_seg_trans_verified ON segment_translations(is_verified) WHERE is_verified = FALSE;

-- =============================================================================
-- TABLE: annotations
-- Purpose: Track Label Studio annotation tasks
-- =============================================================================

DROP TABLE IF EXISTS annotations CASCADE;
CREATE TABLE annotations (
    annotation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Can reference either sample or segment
    sample_id UUID REFERENCES samples(sample_id) ON DELETE CASCADE,
    segment_id UUID REFERENCES segments(segment_id) ON DELETE CASCADE,
    
    -- Task definition
    task_type annotation_task NOT NULL,
    status annotation_status NOT NULL DEFAULT 'pending',
    
    -- Assignment
    assigned_to VARCHAR(255),
    assigned_at TIMESTAMPTZ,
    
    -- Label Studio integration
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    label_studio_annotation_id INTEGER,
    
    -- Results
    result JSONB,
    
    -- Quality
    time_spent_seconds INTEGER,
    
    -- Conflict tracking
    sync_version_at_start INTEGER,
    conflict_detected BOOLEAN DEFAULT FALSE,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    -- Must have either sample_id or segment_id
    CONSTRAINT chk_sample_or_segment CHECK (
        (sample_id IS NOT NULL AND segment_id IS NULL) OR
        (sample_id IS NULL AND segment_id IS NOT NULL)
    )
);

CREATE INDEX idx_annotations_sample ON annotations(sample_id) WHERE sample_id IS NOT NULL;
CREATE INDEX idx_annotations_segment ON annotations(segment_id) WHERE segment_id IS NOT NULL;
CREATE INDEX idx_annotations_task ON annotations(task_type, status);
CREATE INDEX idx_annotations_assignee ON annotations(assigned_to);

-- =============================================================================
-- TABLE: processing_logs
-- Purpose: Audit trail for all processing operations
-- =============================================================================

DROP TABLE IF EXISTS processing_logs CASCADE;
CREATE TABLE processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id) ON DELETE SET NULL,
    segment_id UUID REFERENCES segments(segment_id) ON DELETE SET NULL,
    
    -- Operation details
    operation VARCHAR(100) NOT NULL,
    previous_state processing_state,
    new_state processing_state,
    
    -- Execution context
    executor VARCHAR(255),
    execution_time_ms INTEGER,
    
    -- Details
    input_params JSONB,
    output_summary JSONB,
    error_message TEXT,
    
    success BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_logs_sample ON processing_logs(sample_id, created_at DESC);
CREATE INDEX idx_logs_segment ON processing_logs(segment_id, created_at DESC);
CREATE INDEX idx_logs_failures ON processing_logs(operation) WHERE success = FALSE;

-- =============================================================================
-- TABLE: api_keys
-- Purpose: Track Gemini API keys for rotation
-- =============================================================================

DROP TABLE IF EXISTS api_keys CASCADE;
CREATE TABLE api_keys (
    key_id SERIAL PRIMARY KEY,
    
    -- Key info (store encrypted or use env vars in production)
    key_name VARCHAR(100) NOT NULL,     -- Friendly name
    key_hash VARCHAR(64),               -- SHA256 hash for identification (not the actual key)
    
    -- Rate limiting
    daily_requests_used INTEGER DEFAULT 0,
    daily_requests_limit INTEGER DEFAULT 1500,  -- Gemini free tier
    last_used_at TIMESTAMPTZ,
    rate_limited_until TIMESTAMPTZ,     -- When rate limit expires
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_keys_active ON api_keys(is_active, rate_limited_until);

-- =============================================================================
-- TABLE: sync_conflicts (from v2)
-- =============================================================================

DROP TABLE IF EXISTS sync_conflicts CASCADE;
CREATE TABLE sync_conflicts (
    conflict_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id) ON DELETE SET NULL,
    table_name VARCHAR(100) NOT NULL,
    local_data JSONB NOT NULL,
    remote_data JSONB NOT NULL,
    winner VARCHAR(20) NOT NULL DEFAULT 'remote',
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(255),
    resolution_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sync_conflicts_unresolved ON sync_conflicts(created_at DESC) WHERE reviewed_at IS NULL;

-- =============================================================================
-- VIEWS
-- =============================================================================

-- View: Sample overview with current state
CREATE OR REPLACE VIEW v_sample_overview AS
SELECT 
    s.sample_id,
    s.external_id,
    s.subtitle_type,
    s.processing_state,
    s.duration_seconds,
    s.cs_ratio,
    s.priority,
    s.created_at,
    src.name AS channel_name,
    s.source_metadata->>'title' AS video_title,
    -- Latest transcript version
    (SELECT version FROM transcript_revisions WHERE sample_id = s.sample_id ORDER BY version DESC LIMIT 1) AS transcript_version,
    -- Latest translation version
    (SELECT version FROM translation_revisions WHERE sample_id = s.sample_id ORDER BY version DESC LIMIT 1) AS translation_version,
    -- Segment count
    (SELECT COUNT(*) FROM segments WHERE sample_id = s.sample_id) AS segment_count,
    -- Verified segment count
    (SELECT COUNT(*) FROM segments WHERE sample_id = s.sample_id AND is_verified = TRUE) AS verified_segment_count
FROM samples s
LEFT JOIN sources src ON s.source_id = src.source_id
WHERE s.is_deleted = FALSE;

-- View: Pipeline statistics
CREATE OR REPLACE VIEW v_pipeline_stats AS
SELECT 
    processing_state,
    subtitle_type,
    COUNT(*) AS sample_count,
    ROUND(AVG(duration_seconds)::NUMERIC, 1) AS avg_duration_sec,
    ROUND(AVG(cs_ratio)::NUMERIC, 3) AS avg_cs_ratio
FROM samples
WHERE is_deleted = FALSE
GROUP BY processing_state, subtitle_type
ORDER BY processing_state, subtitle_type;

-- View: Segments ready for export
CREATE OR REPLACE VIEW v_export_ready_segments AS
SELECT 
    seg.segment_id,
    seg.sample_id,
    s.external_id AS video_id,
    seg.segment_index,
    seg.audio_file_path,
    seg.transcript_text,
    seg.start_time_ms,
    seg.end_time_ms,
    seg.duration_ms,
    st.translation_text,
    seg.alignment_score
FROM segments seg
JOIN samples s ON seg.sample_id = s.sample_id
LEFT JOIN segment_translations st ON seg.segment_id = st.segment_id AND st.is_verified = TRUE
WHERE s.processing_state = 'FINAL'
  AND seg.is_verified = TRUE
  AND s.is_deleted = FALSE
ORDER BY s.external_id, seg.segment_index;

-- View: API key status
CREATE OR REPLACE VIEW v_api_key_status AS
SELECT 
    key_id,
    key_name,
    daily_requests_used,
    daily_requests_limit,
    daily_requests_limit - daily_requests_used AS requests_remaining,
    is_active,
    CASE 
        WHEN rate_limited_until IS NOT NULL AND rate_limited_until > NOW() THEN 'rate_limited'
        WHEN NOT is_active THEN 'disabled'
        WHEN daily_requests_used >= daily_requests_limit THEN 'exhausted'
        ELSE 'available'
    END AS status,
    rate_limited_until,
    last_used_at
FROM api_keys
ORDER BY 
    CASE WHEN is_active AND (rate_limited_until IS NULL OR rate_limited_until <= NOW()) 
         AND daily_requests_used < daily_requests_limit THEN 0 ELSE 1 END,
    daily_requests_used ASC;

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Function: Transition sample state with logging
CREATE OR REPLACE FUNCTION transition_sample_state(
    p_sample_id UUID,
    p_new_state processing_state,
    p_executor VARCHAR(255) DEFAULT 'system'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_old_state processing_state;
BEGIN
    SELECT processing_state INTO v_old_state
    FROM samples WHERE sample_id = p_sample_id;
    
    IF v_old_state IS NULL THEN
        RAISE EXCEPTION 'Sample not found: %', p_sample_id;
    END IF;
    
    UPDATE samples 
    SET processing_state = p_new_state,
        processed_at = NOW(),
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    INSERT INTO processing_logs (
        sample_id, operation, previous_state, new_state, executor, success
    ) VALUES (
        p_sample_id, 'state_transition', v_old_state, p_new_state, p_executor, TRUE
    );
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function: Add transcript revision
CREATE OR REPLACE FUNCTION add_transcript_revision(
    p_sample_id UUID,
    p_transcript_text TEXT,
    p_revision_type VARCHAR(50),
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_word_timestamps JSONB DEFAULT NULL,
    p_sentence_timestamps JSONB DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system'
)
RETURNS UUID AS $$
DECLARE
    v_new_version INTEGER;
    v_revision_id UUID;
BEGIN
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_new_version
    FROM transcript_revisions WHERE sample_id = p_sample_id;
    
    INSERT INTO transcript_revisions (
        sample_id, version, transcript_text, revision_type, 
        revision_source, word_timestamps, sentence_timestamps, created_by
    ) VALUES (
        p_sample_id, v_new_version, p_transcript_text, p_revision_type,
        p_revision_source, p_word_timestamps, p_sentence_timestamps, p_created_by
    ) RETURNING revision_id INTO v_revision_id;
    
    UPDATE samples 
    SET current_transcript_version = v_new_version,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    RETURN v_revision_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Add translation revision
CREATE OR REPLACE FUNCTION add_translation_revision(
    p_sample_id UUID,
    p_translation_text TEXT,
    p_revision_type VARCHAR(50),
    p_source_transcript_revision_id UUID DEFAULT NULL,
    p_sentence_translations JSONB DEFAULT NULL,
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_api_model VARCHAR(100) DEFAULT NULL,
    p_api_cost_usd NUMERIC(10,6) DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system'
)
RETURNS UUID AS $$
DECLARE
    v_new_version INTEGER;
    v_revision_id UUID;
BEGIN
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_new_version
    FROM translation_revisions WHERE sample_id = p_sample_id;
    
    INSERT INTO translation_revisions (
        sample_id, version, source_transcript_revision_id, translation_text,
        revision_type, sentence_translations, revision_source, 
        api_model, api_cost_usd, created_by
    ) VALUES (
        p_sample_id, v_new_version, p_source_transcript_revision_id, p_translation_text,
        p_revision_type, p_sentence_translations, p_revision_source,
        p_api_model, p_api_cost_usd, p_created_by
    ) RETURNING revision_id INTO v_revision_id;
    
    UPDATE samples 
    SET current_translation_version = v_new_version,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    RETURN v_revision_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Get next available API key
CREATE OR REPLACE FUNCTION get_available_api_key()
RETURNS TABLE(key_id INTEGER, key_name VARCHAR(100)) AS $$
BEGIN
    -- Reset daily counts if new day
    UPDATE api_keys
    SET daily_requests_used = 0
    WHERE DATE(last_used_at) < CURRENT_DATE;
    
    -- Return first available key
    RETURN QUERY
    SELECT ak.key_id, ak.key_name
    FROM api_keys ak
    WHERE ak.is_active = TRUE
      AND (ak.rate_limited_until IS NULL OR ak.rate_limited_until <= NOW())
      AND ak.daily_requests_used < ak.daily_requests_limit
    ORDER BY ak.daily_requests_used ASC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function: Record API key usage
CREATE OR REPLACE FUNCTION record_api_key_usage(
    p_key_id INTEGER,
    p_requests INTEGER DEFAULT 1,
    p_rate_limited BOOLEAN DEFAULT FALSE
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE api_keys
    SET daily_requests_used = daily_requests_used + p_requests,
        last_used_at = NOW(),
        rate_limited_until = CASE 
            WHEN p_rate_limited THEN NOW() + INTERVAL '1 day'
            ELSE rate_limited_until
        END,
        updated_at = NOW()
    WHERE key_id = p_key_id;
    
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function: Get or create source
CREATE OR REPLACE FUNCTION get_or_create_source(
    p_source_type source_type,
    p_external_id VARCHAR(255),
    p_name VARCHAR(500) DEFAULT NULL,
    p_url TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
)
RETURNS UUID AS $$
DECLARE
    v_source_id UUID;
BEGIN
    SELECT source_id INTO v_source_id
    FROM sources 
    WHERE source_type = p_source_type AND external_id = p_external_id;
    
    IF v_source_id IS NULL THEN
        INSERT INTO sources (source_type, external_id, name, url, metadata)
        VALUES (p_source_type, p_external_id, p_name, p_url, p_metadata)
        RETURNING source_id INTO v_source_id;
    END IF;
    
    RETURN v_source_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_samples_updated BEFORE UPDATE ON samples
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_sources_updated BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_segments_updated BEFORE UPDATE ON segments
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_annotations_updated BEFORE UPDATE ON annotations
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_api_keys_updated BEFORE UPDATE ON api_keys
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE sources IS 'YouTube channels as data sources';
COMMENT ON TABLE samples IS 'Full YouTube videos (parent samples)';
COMMENT ON TABLE segments IS 'Audio chunks (10-30s) derived from samples';
COMMENT ON TABLE transcript_revisions IS 'Immutable audit trail for transcript changes';
COMMENT ON TABLE translation_revisions IS 'Immutable audit trail for translations';
COMMENT ON TABLE segment_translations IS 'Per-segment translations for training export';
COMMENT ON TABLE annotations IS 'Label Studio annotation tasks';
COMMENT ON TABLE processing_logs IS 'Audit trail for processing operations';
COMMENT ON TABLE api_keys IS 'Gemini API keys for rotation';

COMMENT ON VIEW v_sample_overview IS 'Sample overview with counts and versions';
COMMENT ON VIEW v_pipeline_stats IS 'Pipeline statistics by state';
COMMENT ON VIEW v_export_ready_segments IS 'Segments ready for training export';
COMMENT ON VIEW v_api_key_status IS 'API key availability status';

COMMENT ON FUNCTION transition_sample_state IS 'Transition sample state with logging';
COMMENT ON FUNCTION add_transcript_revision IS 'Add new transcript revision';
COMMENT ON FUNCTION add_translation_revision IS 'Add new translation revision';
COMMENT ON FUNCTION get_available_api_key IS 'Get next available API key for rotation';
COMMENT ON FUNCTION record_api_key_usage IS 'Record API key usage and rate limiting';

-- =============================================================================
-- SAMPLE DATA: Default API keys placeholder
-- =============================================================================

-- Note: Add actual API keys via INSERT or environment variables
-- INSERT INTO api_keys (key_name, key_hash) VALUES ('gemini_key_1', 'hash_here');


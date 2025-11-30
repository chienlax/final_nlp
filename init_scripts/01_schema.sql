-- =============================================================================
-- init_scripts/01_schema.sql
-- PostgreSQL Schema v5 for Vietnamese-English CS Speech Translation Pipeline
-- 
-- UNIFIED SCHEMA (Sample-level review without chunking):
--   RAW → TRANSLATED → REVIEW_PREPARED → VERIFIED → FINAL
--
-- Key Features v5:
--   1. Sample-level review (no more 15-sentence chunks)
--   2. Per-sentence inline editing with revision history
--   3. channel_name in sources table for display
--   4. sentence_reviews with previous_* columns for tracking changes
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
    'youtube_manual_transcript',
    'youtube_auto_transcript',
    'manual_upload'
);

-- Subtitle type for YouTube videos
CREATE TYPE subtitle_type AS ENUM (
    'manual',
    'auto_generated',
    'none'
);

-- Processing states for human-in-the-loop pipeline
CREATE TYPE processing_state AS ENUM (
    'RAW',
    'TRANSLATED',
    'REVIEW_PREPARED',
    'IN_REVIEW',
    'VERIFIED',
    'FINAL',
    'REJECTED'
);

-- Content type
CREATE TYPE content_type AS ENUM (
    'audio_primary',
    'audio_segment'
);

-- Annotation task types
CREATE TYPE annotation_task AS ENUM (
    'unified_review'
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
-- =============================================================================

DROP TABLE IF EXISTS sources CASCADE;
CREATE TABLE sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type source_type NOT NULL,
    external_id VARCHAR(255),
    name VARCHAR(500),
    channel_name VARCHAR(500),
    url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_type, external_id)
);

CREATE INDEX idx_sources_type ON sources(source_type);

-- =============================================================================
-- TABLE: samples
-- =============================================================================

DROP TABLE IF EXISTS samples CASCADE;
CREATE TABLE samples (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(source_id) ON DELETE SET NULL,
    external_id VARCHAR(255) NOT NULL,
    content_type content_type NOT NULL DEFAULT 'audio_primary',
    audio_file_path TEXT NOT NULL,
    text_file_path TEXT,
    subtitle_type subtitle_type NOT NULL,
    subtitle_language VARCHAR(10),
    pipeline_type source_type NOT NULL,
    processing_state processing_state NOT NULL DEFAULT 'RAW',
    current_transcript_version INTEGER DEFAULT 0,
    current_translation_version INTEGER DEFAULT 0,
    duration_seconds NUMERIC(10, 2),
    sample_rate INTEGER DEFAULT 16000,
    cs_ratio NUMERIC(5, 4),
    detected_languages JSONB DEFAULT '["vi", "en"]',
    source_metadata JSONB DEFAULT '{}',
    acoustic_metadata JSONB DEFAULT '{}',
    processing_metadata JSONB DEFAULT '{}',
    quality_score NUMERIC(3, 2),
    priority INTEGER DEFAULT 0,
    
    -- Label Studio integration (sample-level)
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    
    -- DVC sync
    dvc_commit_hash VARCHAR(40),
    audio_file_md5 VARCHAR(32),
    sync_version INTEGER DEFAULT 1,
    
    -- Locking
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(255),
    
    -- Gold standard
    is_gold_standard BOOLEAN DEFAULT FALSE,
    gold_score NUMERIC(3, 2),
    needs_translation_review BOOLEAN DEFAULT FALSE,
    
    -- Review tracking
    review_started_at TIMESTAMPTZ,
    review_completed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(255),
    review_time_seconds INTEGER,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_samples_state ON samples(processing_state) WHERE is_deleted = FALSE;
CREATE INDEX idx_samples_pipeline ON samples(pipeline_type, processing_state);
CREATE INDEX idx_samples_external_id ON samples(external_id);
CREATE INDEX idx_samples_source ON samples(source_id);
CREATE INDEX idx_samples_subtitle ON samples(subtitle_type);
CREATE INDEX idx_samples_priority ON samples(priority DESC, created_at ASC) WHERE is_deleted = FALSE;
CREATE INDEX idx_samples_ls_task ON samples(label_studio_task_id) WHERE label_studio_task_id IS NOT NULL;

-- =============================================================================
-- TABLE: transcript_revisions
-- =============================================================================

DROP TABLE IF EXISTS transcript_revisions CASCADE;
CREATE TABLE transcript_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    transcript_text TEXT NOT NULL,
    revision_type VARCHAR(50) NOT NULL,
    revision_source VARCHAR(100),
    word_timestamps JSONB,
    sentence_timestamps JSONB,
    has_translation_issues BOOLEAN DEFAULT FALSE,
    translation_issue_indices INTEGER[],
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE (sample_id, version)
);

CREATE INDEX idx_transcript_rev_sample ON transcript_revisions(sample_id, version DESC);
CREATE INDEX idx_transcript_rev_type ON transcript_revisions(revision_type);

-- =============================================================================
-- TABLE: translation_revisions
-- =============================================================================

DROP TABLE IF EXISTS translation_revisions CASCADE;
CREATE TABLE translation_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source_transcript_revision_id UUID REFERENCES transcript_revisions(revision_id),
    translation_text TEXT NOT NULL,
    source_language VARCHAR(10) DEFAULT 'vi-en',
    target_language VARCHAR(10) NOT NULL DEFAULT 'vi',
    revision_type VARCHAR(50) NOT NULL,
    revision_source VARCHAR(100),
    sentence_translations JSONB,
    confidence_score NUMERIC(5, 4),
    api_model VARCHAR(100),
    api_cost_usd NUMERIC(10, 6),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE (sample_id, version)
);

CREATE INDEX idx_translation_rev_sample ON translation_revisions(sample_id, version DESC);
CREATE INDEX idx_translation_rev_type ON translation_revisions(revision_type);

-- =============================================================================
-- TABLE: sentence_reviews
-- Per-sentence corrections with revision history
-- =============================================================================

DROP TABLE IF EXISTS sentence_reviews CASCADE;
CREATE TABLE sentence_reviews (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    sentence_idx INTEGER NOT NULL,
    
    -- Original values (from Gemini) - immutable
    original_start_ms INTEGER NOT NULL,
    original_end_ms INTEGER NOT NULL,
    original_transcript TEXT NOT NULL,
    original_translation TEXT NOT NULL,
    
    -- Current reviewed values (NULL if unchanged)
    reviewed_start_ms INTEGER,
    reviewed_end_ms INTEGER,
    reviewed_transcript TEXT,
    reviewed_translation TEXT,
    
    -- Previous values for revision history
    previous_transcript TEXT,
    previous_translation TEXT,
    
    -- Revision tracking
    revision_count INTEGER DEFAULT 0,
    last_revised_at TIMESTAMPTZ,
    last_revised_by VARCHAR(255),
    
    -- Flags
    is_boundary_adjusted BOOLEAN DEFAULT FALSE,
    is_transcript_corrected BOOLEAN DEFAULT FALSE,
    is_translation_corrected BOOLEAN DEFAULT FALSE,
    is_rejected BOOLEAN DEFAULT FALSE,
    rejection_reason TEXT,
    review_status annotation_status DEFAULT 'pending',
    reviewer_notes TEXT,
    
    -- Audio file reference
    sentence_audio_path TEXT,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (sample_id, sentence_idx)
);

CREATE INDEX idx_sentence_reviews_sample ON sentence_reviews(sample_id, sentence_idx);
CREATE INDEX idx_sentence_reviews_status ON sentence_reviews(review_status) WHERE review_status != 'completed';
CREATE INDEX idx_sentence_reviews_corrected ON sentence_reviews(sample_id) 
    WHERE is_transcript_corrected = TRUE OR is_translation_corrected = TRUE;
CREATE INDEX idx_sentence_reviews_rejected ON sentence_reviews(is_rejected) WHERE is_rejected = TRUE;

-- =============================================================================
-- TABLE: processing_logs
-- =============================================================================

DROP TABLE IF EXISTS processing_logs CASCADE;
CREATE TABLE processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id) ON DELETE SET NULL,
    operation VARCHAR(100) NOT NULL,
    previous_state processing_state,
    new_state processing_state,
    executor VARCHAR(255),
    execution_time_ms INTEGER,
    input_params JSONB,
    output_summary JSONB,
    error_message TEXT,
    success BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_logs_sample ON processing_logs(sample_id, created_at DESC);
CREATE INDEX idx_logs_failures ON processing_logs(operation) WHERE success = FALSE;

-- =============================================================================
-- TABLE: api_keys
-- =============================================================================

DROP TABLE IF EXISTS api_keys CASCADE;
CREATE TABLE api_keys (
    key_id SERIAL PRIMARY KEY,
    key_name VARCHAR(100) NOT NULL,
    key_hash VARCHAR(64),
    daily_requests_used INTEGER DEFAULT 0,
    daily_requests_limit INTEGER DEFAULT 1500,
    last_used_at TIMESTAMPTZ,
    rate_limited_until TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_keys_active ON api_keys(is_active, rate_limited_until);

-- =============================================================================
-- VIEWS
-- =============================================================================

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
    COALESCE(src.channel_name, src.name) AS channel_name,
    s.source_metadata->>'title' AS video_title,
    (SELECT version FROM transcript_revisions WHERE sample_id = s.sample_id ORDER BY version DESC LIMIT 1) AS transcript_version,
    (SELECT version FROM translation_revisions WHERE sample_id = s.sample_id ORDER BY version DESC LIMIT 1) AS translation_version,
    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id) AS sentence_count,
    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id 
        AND (reviewed_transcript IS NOT NULL OR reviewed_translation IS NOT NULL)) AS reviewed_sentence_count
FROM samples s
LEFT JOIN sources src ON s.source_id = src.source_id
WHERE s.is_deleted = FALSE;

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

CREATE OR REPLACE VIEW v_review_queue AS
SELECT 
    s.sample_id,
    s.external_id,
    s.source_metadata->>'title' AS video_title,
    COALESCE(src.channel_name, src.name) AS channel_name,
    s.duration_seconds,
    s.processing_state,
    s.label_studio_task_id,
    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id) AS total_sentences,
    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id AND review_status = 'completed') AS completed_sentences,
    (SELECT COUNT(*) FROM sentence_reviews WHERE sample_id = s.sample_id AND is_rejected = TRUE) AS rejected_sentences,
    s.created_at,
    s.review_started_at,
    s.reviewed_by
FROM samples s
LEFT JOIN sources src ON s.source_id = src.source_id
WHERE s.processing_state IN ('REVIEW_PREPARED', 'IN_REVIEW', 'VERIFIED')
  AND s.is_deleted = FALSE
ORDER BY s.priority DESC, s.created_at ASC;

CREATE OR REPLACE VIEW v_sentence_review_stats AS
SELECT 
    sr.sample_id,
    s.external_id,
    COUNT(*) AS total_sentences,
    COUNT(*) FILTER (WHERE sr.is_boundary_adjusted) AS boundary_adjusted,
    COUNT(*) FILTER (WHERE sr.is_transcript_corrected) AS transcript_corrected,
    COUNT(*) FILTER (WHERE sr.is_translation_corrected) AS translation_corrected,
    COUNT(*) FILTER (WHERE sr.is_rejected) AS rejected,
    SUM(sr.revision_count) AS total_revisions,
    ROUND(
        COUNT(*) FILTER (WHERE sr.is_boundary_adjusted OR sr.is_transcript_corrected OR sr.is_translation_corrected)::NUMERIC 
        / NULLIF(COUNT(*), 0) * 100, 
        1
    ) AS correction_rate_pct
FROM sentence_reviews sr
JOIN samples s ON sr.sample_id = s.sample_id
GROUP BY sr.sample_id, s.external_id;

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

CREATE OR REPLACE FUNCTION add_transcript_revision(
    p_sample_id UUID,
    p_transcript_text TEXT,
    p_revision_type VARCHAR(50),
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_word_timestamps JSONB DEFAULT NULL,
    p_sentence_timestamps JSONB DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system',
    p_has_translation_issues BOOLEAN DEFAULT FALSE,
    p_translation_issue_indices INTEGER[] DEFAULT NULL
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
        revision_source, word_timestamps, sentence_timestamps, created_by,
        has_translation_issues, translation_issue_indices
    ) VALUES (
        p_sample_id, v_new_version, p_transcript_text, p_revision_type,
        p_revision_source, p_word_timestamps, p_sentence_timestamps, p_created_by,
        p_has_translation_issues, p_translation_issue_indices
    ) RETURNING revision_id INTO v_revision_id;
    
    UPDATE samples 
    SET current_transcript_version = v_new_version,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    RETURN v_revision_id;
END;
$$ LANGUAGE plpgsql;

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

CREATE OR REPLACE FUNCTION get_available_api_key()
RETURNS TABLE(key_id INTEGER, key_name VARCHAR(100)) AS $$
BEGIN
    UPDATE api_keys SET daily_requests_used = 0 WHERE DATE(last_used_at) < CURRENT_DATE;
    
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

CREATE OR REPLACE FUNCTION get_or_create_source(
    p_source_type source_type,
    p_external_id VARCHAR(255),
    p_name VARCHAR(500) DEFAULT NULL,
    p_url TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}',
    p_channel_name VARCHAR(500) DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_source_id UUID;
BEGIN
    SELECT source_id INTO v_source_id
    FROM sources WHERE source_type = p_source_type AND external_id = p_external_id;
    
    IF v_source_id IS NULL THEN
        INSERT INTO sources (source_type, external_id, name, url, metadata, channel_name)
        VALUES (p_source_type, p_external_id, p_name, p_url, p_metadata, p_channel_name)
        RETURNING source_id INTO v_source_id;
    ELSE
        IF p_channel_name IS NOT NULL THEN
            UPDATE sources 
            SET channel_name = COALESCE(sources.channel_name, p_channel_name),
                updated_at = NOW()
            WHERE source_id = v_source_id AND channel_name IS NULL;
        END IF;
    END IF;
    
    RETURN v_source_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION init_sentence_reviews(
    p_sample_id UUID
)
RETURNS INTEGER AS $$
DECLARE
    v_transcript_rev RECORD;
    v_sentences JSONB;
    v_sentence JSONB;
    v_idx INTEGER;
    v_count INTEGER := 0;
BEGIN
    SELECT * INTO v_transcript_rev
    FROM transcript_revisions
    WHERE sample_id = p_sample_id AND sentence_timestamps IS NOT NULL
    ORDER BY version DESC LIMIT 1;
    
    IF v_transcript_rev IS NULL THEN
        RAISE EXCEPTION 'No transcript revision with sentence timestamps found for sample %', p_sample_id;
    END IF;
    
    v_sentences := v_transcript_rev.sentence_timestamps;
    
    IF jsonb_array_length(v_sentences) = 0 THEN
        RAISE EXCEPTION 'No sentences found in transcript for sample %', p_sample_id;
    END IF;
    
    DELETE FROM sentence_reviews WHERE sample_id = p_sample_id;
    
    FOR v_idx IN 0..jsonb_array_length(v_sentences) - 1 LOOP
        v_sentence := v_sentences->v_idx;
        
        INSERT INTO sentence_reviews (
            sample_id, sentence_idx,
            original_start_ms, original_end_ms,
            original_transcript, original_translation
        ) VALUES (
            p_sample_id, v_idx,
            (v_sentence->>'start')::NUMERIC * 1000,
            (v_sentence->>'end')::NUMERIC * 1000,
            v_sentence->>'text',
            COALESCE(v_sentence->>'translation', '')
        );
        
        v_count := v_count + 1;
    END LOOP;
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_sentence_review(
    p_sample_id UUID,
    p_sentence_idx INTEGER,
    p_reviewed_transcript TEXT DEFAULT NULL,
    p_reviewed_translation TEXT DEFAULT NULL,
    p_reviewed_start_ms INTEGER DEFAULT NULL,
    p_reviewed_end_ms INTEGER DEFAULT NULL,
    p_is_rejected BOOLEAN DEFAULT FALSE,
    p_rejection_reason TEXT DEFAULT NULL,
    p_reviewer_notes TEXT DEFAULT NULL,
    p_reviewed_by VARCHAR(255) DEFAULT NULL
)
RETURNS BOOLEAN AS $$
DECLARE
    v_current RECORD;
BEGIN
    SELECT * INTO v_current
    FROM sentence_reviews
    WHERE sample_id = p_sample_id AND sentence_idx = p_sentence_idx;
    
    IF v_current IS NULL THEN RETURN FALSE; END IF;
    
    UPDATE sentence_reviews SET
        previous_transcript = CASE 
            WHEN p_reviewed_transcript IS NOT NULL AND p_reviewed_transcript != COALESCE(v_current.reviewed_transcript, v_current.original_transcript)
            THEN COALESCE(v_current.reviewed_transcript, v_current.original_transcript)
            ELSE v_current.previous_transcript
        END,
        previous_translation = CASE 
            WHEN p_reviewed_translation IS NOT NULL AND p_reviewed_translation != COALESCE(v_current.reviewed_translation, v_current.original_translation)
            THEN COALESCE(v_current.reviewed_translation, v_current.original_translation)
            ELSE v_current.previous_translation
        END,
        reviewed_transcript = COALESCE(p_reviewed_transcript, v_current.reviewed_transcript),
        reviewed_translation = COALESCE(p_reviewed_translation, v_current.reviewed_translation),
        reviewed_start_ms = COALESCE(p_reviewed_start_ms, v_current.reviewed_start_ms),
        reviewed_end_ms = COALESCE(p_reviewed_end_ms, v_current.reviewed_end_ms),
        is_transcript_corrected = CASE 
            WHEN p_reviewed_transcript IS NOT NULL AND p_reviewed_transcript != v_current.original_transcript
            THEN TRUE ELSE v_current.is_transcript_corrected
        END,
        is_translation_corrected = CASE 
            WHEN p_reviewed_translation IS NOT NULL AND p_reviewed_translation != v_current.original_translation
            THEN TRUE ELSE v_current.is_translation_corrected
        END,
        is_boundary_adjusted = CASE
            WHEN (p_reviewed_start_ms IS NOT NULL AND p_reviewed_start_ms != v_current.original_start_ms)
                OR (p_reviewed_end_ms IS NOT NULL AND p_reviewed_end_ms != v_current.original_end_ms)
            THEN TRUE ELSE v_current.is_boundary_adjusted
        END,
        is_rejected = COALESCE(p_is_rejected, v_current.is_rejected),
        rejection_reason = COALESCE(p_rejection_reason, v_current.rejection_reason),
        reviewer_notes = COALESCE(p_reviewer_notes, v_current.reviewer_notes),
        revision_count = CASE 
            WHEN p_reviewed_transcript IS NOT NULL OR p_reviewed_translation IS NOT NULL 
                OR p_reviewed_start_ms IS NOT NULL OR p_reviewed_end_ms IS NOT NULL
            THEN v_current.revision_count + 1 ELSE v_current.revision_count
        END,
        last_revised_at = CASE 
            WHEN p_reviewed_transcript IS NOT NULL OR p_reviewed_translation IS NOT NULL
                OR p_reviewed_start_ms IS NOT NULL OR p_reviewed_end_ms IS NOT NULL
            THEN NOW() ELSE v_current.last_revised_at
        END,
        last_revised_by = COALESCE(p_reviewed_by, v_current.last_revised_by),
        review_status = 'completed',
        updated_at = NOW()
    WHERE sample_id = p_sample_id AND sentence_idx = p_sentence_idx;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION check_sample_review_complete(p_sample_id UUID)
RETURNS BOOLEAN AS $$
DECLARE v_incomplete_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_incomplete_count
    FROM sentence_reviews WHERE sample_id = p_sample_id AND review_status != 'completed';
    RETURN v_incomplete_count = 0;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_review_progress(p_sample_id UUID)
RETURNS TABLE(
    total_sentences INTEGER, completed_sentences INTEGER, pending_sentences INTEGER,
    transcript_corrected INTEGER, translation_corrected INTEGER,
    rejected_sentences INTEGER, total_revisions INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::INTEGER,
        COUNT(*) FILTER (WHERE review_status = 'completed')::INTEGER,
        COUNT(*) FILTER (WHERE review_status = 'pending')::INTEGER,
        COUNT(*) FILTER (WHERE is_transcript_corrected)::INTEGER,
        COUNT(*) FILTER (WHERE is_translation_corrected)::INTEGER,
        COUNT(*) FILTER (WHERE is_rejected)::INTEGER,
        COALESCE(SUM(revision_count), 0)::INTEGER
    FROM sentence_reviews WHERE sample_id = p_sample_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_samples_updated BEFORE UPDATE ON samples FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER tr_sources_updated BEFORE UPDATE ON sources FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER tr_api_keys_updated BEFORE UPDATE ON api_keys FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER tr_sentence_reviews_updated BEFORE UPDATE ON sentence_reviews FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- =============================================================================
-- SCHEMA VERSION
-- =============================================================================

INSERT INTO processing_logs (operation, success, output_summary, executor) VALUES (
    'schema_init_v5', TRUE,
    '{"version": "5.0", "features": ["sample-level review", "per-sentence inline editing", "revision history"]}'::JSONB,
    'init_script'
);


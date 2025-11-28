-- =============================================================================
-- init_scripts/02_schema_v2.sql
-- PostgreSQL Schema for Vietnamese-English CS Speech Translation Pipeline
-- 
-- Design Principles:
--   1. Separate concerns: sources, samples, segments, revisions, annotations
--   2. Immutable audit trail (append-only revisions)
--   3. JSONB for flexible metadata, typed columns for queryable fields
--   4. Optimized indexes for Label Studio workflow queries
--
-- Pipeline Support:
--   - Audio-First (YouTube with transcript): RAW -> ALIGNED -> SEGMENTED -> ENHANCED -> TRANSLATED -> REVIEWED
--   - Audio-First (YouTube without transcript): RAW -> VAD_SEGMENTED -> ALIGNED -> ENHANCED -> TRANSLATED -> REVIEWED
--   - Text-First (Substack): RAW -> NORMALIZED -> CS_CHUNKED -> TTS_GENERATED -> TRANSLATED -> REVIEWED
-- =============================================================================

-- Drop old schema (starting fresh)
DROP TABLE IF EXISTS dataset_ledger CASCADE;

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

-- Pipeline source types
DROP TYPE IF EXISTS source_type CASCADE;
CREATE TYPE source_type AS ENUM (
    'youtube_with_transcript',
    'youtube_without_transcript',
    'substack',
    'manual_upload'
);

-- Processing states covering all pipelines
-- Audio-First (with transcript): RAW -> ALIGNED -> SEGMENTED -> ENHANCED -> TRANSLATED -> REVIEWED
-- Audio-First (without transcript): RAW -> VAD_SEGMENTED -> ALIGNED -> ENHANCED -> TRANSLATED -> REVIEWED
-- Text-First: RAW -> NORMALIZED -> CS_CHUNKED -> TTS_GENERATED -> TRANSLATED -> REVIEWED
DROP TYPE IF EXISTS processing_state CASCADE;
CREATE TYPE processing_state AS ENUM (
    'RAW',
    'ALIGNED',
    'SEGMENTED',
    'VAD_SEGMENTED',
    'ENHANCED',
    'NORMALIZED',
    'CS_CHUNKED',
    'TTS_GENERATED',
    'TRANSLATED',
    'REVIEWED',
    'REJECTED'
);

-- Content type (audio vs text primary)
DROP TYPE IF EXISTS content_type CASCADE;
CREATE TYPE content_type AS ENUM (
    'audio_primary',
    'text_primary'
);

-- Annotation task types for Label Studio
DROP TYPE IF EXISTS annotation_task CASCADE;
CREATE TYPE annotation_task AS ENUM (
    'transcript_verification',
    'timestamp_alignment',
    'translation_review',
    'quality_assessment'
);

-- Annotation status
DROP TYPE IF EXISTS annotation_status CASCADE;
CREATE TYPE annotation_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'skipped',
    'disputed'
);

-- =============================================================================
-- TABLE: sources
-- Purpose: Track original content sources (YouTube channels, Substack blogs)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source identification
    source_type source_type NOT NULL,
    external_id VARCHAR(255),           -- YouTube channel ID, Substack URL slug
    name VARCHAR(500),                  -- Channel/blog name
    url TEXT,                           -- Base URL
    
    -- Metadata
    metadata JSONB DEFAULT '{}',        -- Flexible: subscriber count, language, etc.
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE (source_type, external_id)
);

-- Index for looking up sources by type
CREATE INDEX idx_sources_type ON sources(source_type);

-- =============================================================================
-- TABLE: samples
-- Purpose: Core data units (videos, articles, audio segments)
-- Supports parent-child relationships for segmentation
-- =============================================================================

CREATE TABLE IF NOT EXISTS samples (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    source_id UUID REFERENCES sources(source_id) ON DELETE SET NULL,
    parent_sample_id UUID REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Content identification
    external_id VARCHAR(255),           -- YouTube video ID, article slug
    content_type content_type NOT NULL,
    
    -- File references (relative to data/raw/ or data/processed/)
    audio_file_path TEXT,               -- Path to WAV file
    text_file_path TEXT,                -- Path to transcript/text file
    
    -- Processing pipeline
    pipeline_type source_type NOT NULL, -- Which pipeline this follows
    processing_state processing_state NOT NULL DEFAULT 'RAW',
    
    -- Segment metadata (for child samples)
    segment_index INTEGER,              -- Order within parent (0-based)
    start_time_ms INTEGER,              -- Start timestamp in milliseconds
    end_time_ms INTEGER,                -- End timestamp in milliseconds
    
    -- Current versions (denormalized for fast access)
    current_transcript_version INTEGER DEFAULT 0,
    current_translation_version INTEGER DEFAULT 0,
    
    -- Structured metadata (queryable)
    duration_seconds NUMERIC(10, 2),
    sample_rate INTEGER DEFAULT 16000,
    cs_ratio NUMERIC(5, 4),             -- Code-switching ratio (0.0 to 1.0)
    
    -- Flexible metadata
    source_metadata JSONB DEFAULT '{}', -- URL, upload date, channel info
    acoustic_metadata JSONB DEFAULT '{}', -- Audio properties, noise levels
    linguistic_metadata JSONB DEFAULT '{}', -- Language tags, speaker info
    processing_metadata JSONB DEFAULT '{}', -- Pipeline-specific data
    
    -- Quality & priority
    quality_score NUMERIC(3, 2),        -- 0.00 to 1.00
    priority INTEGER DEFAULT 0,         -- Higher = more urgent
    
    -- Label Studio integration
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    
    -- DVC version tracking (for conflict detection with crawlers)
    dvc_commit_hash VARCHAR(40),        -- Git-like hash from DVC
    audio_file_md5 VARCHAR(32),         -- MD5 checksum of audio file
    sync_version INTEGER DEFAULT 1,     -- Incremented on each update (optimistic locking)
    
    -- Annotation locking (prevent concurrent edits)
    locked_at TIMESTAMPTZ,              -- When sample was locked for annotation
    locked_by VARCHAR(255),             -- Who locked it (annotator ID/email)
    
    -- Gold standard for quality control
    is_gold_standard BOOLEAN DEFAULT FALSE,  -- Mark as QC sample
    gold_score NUMERIC(3, 2),           -- Expected score for gold samples
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,           -- When last state transition occurred
    
    -- Soft delete
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    -- Constraint: At least one file path must be provided
    CONSTRAINT chk_file_path CHECK (
        audio_file_path IS NOT NULL OR text_file_path IS NOT NULL
    )
);

-- =============================================================================
-- INDEXES FOR samples TABLE
-- =============================================================================

-- Primary workflow query: "What needs review next?"
CREATE INDEX idx_samples_review_queue ON samples(
    processing_state, 
    priority DESC, 
    created_at ASC
) WHERE is_deleted = FALSE;

-- Find all segments of a parent
CREATE INDEX idx_samples_parent ON samples(parent_sample_id, segment_index)
WHERE parent_sample_id IS NOT NULL;

-- Filter by pipeline type
CREATE INDEX idx_samples_pipeline ON samples(pipeline_type, processing_state);

-- Label Studio lookups
CREATE INDEX idx_samples_label_studio ON samples(label_studio_project_id, label_studio_task_id)
WHERE label_studio_task_id IS NOT NULL;

-- Source-based queries
CREATE INDEX idx_samples_source ON samples(source_id, created_at DESC);

-- CS ratio filtering (find high code-switching samples)
CREATE INDEX idx_samples_cs_ratio ON samples(cs_ratio DESC)
WHERE cs_ratio IS NOT NULL AND cs_ratio > 0;

-- External ID lookup
CREATE INDEX idx_samples_external_id ON samples(external_id);

-- Full-text search on metadata (GIN index for JSONB)
CREATE INDEX idx_samples_source_meta ON samples USING GIN (source_metadata);
CREATE INDEX idx_samples_linguistic_meta ON samples USING GIN (linguistic_metadata);

-- Gold standard samples lookup
CREATE INDEX idx_samples_gold_standard ON samples(is_gold_standard, processing_state)
WHERE is_gold_standard = TRUE;

-- Locked samples lookup
CREATE INDEX idx_samples_locked ON samples(locked_at)
WHERE locked_at IS NOT NULL;

-- DVC commit hash lookup (for sync operations)
CREATE INDEX idx_samples_dvc_commit ON samples(dvc_commit_hash)
WHERE dvc_commit_hash IS NOT NULL;

-- =============================================================================
-- TABLE: transcript_revisions
-- Purpose: Immutable audit trail for transcript changes
-- =============================================================================

CREATE TABLE IF NOT EXISTS transcript_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Version tracking
    version INTEGER NOT NULL,
    
    -- Content
    transcript_text TEXT NOT NULL,
    
    -- Revision metadata
    revision_type VARCHAR(50) NOT NULL, -- 'raw', 'asr_generated', 'human_corrected', 'mfa_aligned'
    revision_source VARCHAR(100),       -- 'youtube_api', 'whisper', 'annotator_123'
    
    -- Timestamps (for aligned transcripts)
    timestamps JSONB,                   -- [{start_ms, end_ms, text}, ...]
    
    -- Metadata
    metadata JSONB DEFAULT '{}',        -- Confidence scores, model versions, etc.
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),            -- User ID or 'system'
    
    -- Constraints
    UNIQUE (sample_id, version)
);

-- Get latest transcript for a sample
CREATE INDEX idx_transcript_rev_latest ON transcript_revisions(
    sample_id, 
    version DESC
);

-- Find revisions by type
CREATE INDEX idx_transcript_rev_type ON transcript_revisions(revision_type, created_at);

-- =============================================================================
-- TABLE: translation_revisions
-- Purpose: Immutable audit trail for translations
-- =============================================================================

CREATE TABLE IF NOT EXISTS translation_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Version tracking
    version INTEGER NOT NULL,
    
    -- Reference to source transcript
    source_transcript_revision_id UUID REFERENCES transcript_revisions(revision_id),
    
    -- Content
    translation_text TEXT NOT NULL,
    source_language VARCHAR(10) DEFAULT 'vi-en', -- Code-switched source
    target_language VARCHAR(10) NOT NULL,        -- 'vi' (translate to Vietnamese)
    
    -- Revision metadata
    revision_type VARCHAR(50) NOT NULL, -- 'llm_generated', 'human_corrected', 'final'
    revision_source VARCHAR(100),       -- 'gpt-4', 'annotator_456'
    
    -- Quality metrics
    confidence_score NUMERIC(5, 4),
    bleu_score NUMERIC(5, 4),
    
    -- Metadata
    metadata JSONB DEFAULT '{}',        -- Model params, prompt version, etc.
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Constraints
    UNIQUE (sample_id, version)
);

-- Get latest translation for a sample
CREATE INDEX idx_translation_rev_latest ON translation_revisions(
    sample_id, 
    version DESC
);

-- Find by revision type
CREATE INDEX idx_translation_rev_type ON translation_revisions(revision_type, created_at);

-- =============================================================================
-- TABLE: sample_lineage
-- Purpose: Track complex derivation relationships between samples
-- (e.g., enhanced audio derived from segmented audio derived from raw)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sample_lineage (
    lineage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationship
    ancestor_sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    descendant_sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Lineage metadata
    derivation_type VARCHAR(50) NOT NULL, -- 'segmentation', 'enhancement', 'tts_generation'
    derivation_step INTEGER NOT NULL,     -- Distance in derivation chain (1 = direct)
    
    -- Processing details
    processing_params JSONB DEFAULT '{}', -- Parameters used for derivation
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE (ancestor_sample_id, descendant_sample_id),
    CHECK (ancestor_sample_id != descendant_sample_id)
);

-- Find all descendants of a sample
CREATE INDEX idx_lineage_descendants ON sample_lineage(ancestor_sample_id, derivation_step);

-- Find all ancestors of a sample
CREATE INDEX idx_lineage_ancestors ON sample_lineage(descendant_sample_id, derivation_step);

-- =============================================================================
-- TABLE: annotations
-- Purpose: Track human annotation tasks and results (Label Studio integration)
-- =============================================================================

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Task definition
    task_type annotation_task NOT NULL,
    status annotation_status NOT NULL DEFAULT 'pending',
    
    -- Assignment
    assigned_to VARCHAR(255),           -- Annotator user ID
    assigned_at TIMESTAMPTZ,
    
    -- Label Studio integration
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    label_studio_annotation_id INTEGER,
    
    -- Results
    result JSONB,                       -- Annotation result data
    
    -- Quality
    time_spent_seconds INTEGER,
    confidence_score NUMERIC(3, 2),     -- Annotator confidence
    
    -- Review (for disputed annotations)
    reviewer_id VARCHAR(255),
    review_result JSONB,
    reviewed_at TIMESTAMPTZ,
    
    -- Conflict tracking (when sample modified during annotation)
    sample_sync_version_at_start INTEGER,  -- sync_version when annotation began
    conflict_detected BOOLEAN DEFAULT FALSE,
    conflict_resolution VARCHAR(50),        -- 'human_wins', 'crawler_wins', 'merged', 'pending_review'
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    -- Constraints
    UNIQUE (sample_id, task_type, label_studio_annotation_id)
);

-- Find pending annotations by type
CREATE INDEX idx_annotations_pending ON annotations(
    task_type, 
    status, 
    created_at ASC
) WHERE status = 'pending';

-- Find annotations by annotator
CREATE INDEX idx_annotations_assignee ON annotations(assigned_to, status);

-- Label Studio sync
CREATE INDEX idx_annotations_label_studio ON annotations(
    label_studio_project_id, 
    label_studio_task_id
);

-- =============================================================================
-- TABLE: processing_logs
-- Purpose: Audit trail for all processing operations
-- =============================================================================

CREATE TABLE IF NOT EXISTS processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id) ON DELETE SET NULL,
    
    -- Operation details
    operation VARCHAR(100) NOT NULL,    -- 'state_transition', 'enhancement', 'segmentation'
    previous_state processing_state,
    new_state processing_state,
    
    -- Execution context
    executor VARCHAR(255),              -- Script name, container ID, user
    execution_time_ms INTEGER,
    
    -- Details
    input_params JSONB,
    output_summary JSONB,
    error_message TEXT,
    
    -- Status
    success BOOLEAN NOT NULL,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Find logs for a sample
CREATE INDEX idx_logs_sample ON processing_logs(sample_id, created_at DESC);

-- Find failed operations
CREATE INDEX idx_logs_failures ON processing_logs(operation, created_at DESC)
WHERE success = FALSE;

-- =============================================================================
-- VIEWS
-- =============================================================================

-- View: Current state of all samples with latest transcript/translation
CREATE OR REPLACE VIEW v_sample_current_state AS
SELECT 
    s.sample_id,
    s.external_id,
    s.content_type,
    s.pipeline_type,
    s.processing_state,
    s.audio_file_path,
    s.text_file_path,
    s.duration_seconds,
    s.cs_ratio,
    s.priority,
    s.quality_score,
    s.created_at,
    s.updated_at,
    -- Latest transcript
    tr.transcript_text AS current_transcript,
    tr.revision_type AS transcript_revision_type,
    tr.timestamps AS transcript_timestamps,
    tr.created_at AS transcript_updated_at,
    -- Latest translation
    tl.translation_text AS current_translation,
    tl.target_language,
    tl.revision_type AS translation_revision_type,
    tl.created_at AS translation_updated_at,
    -- Parent info
    ps.external_id AS parent_external_id,
    s.segment_index,
    s.start_time_ms,
    s.end_time_ms,
    -- Source info
    src.name AS source_name,
    src.source_type
FROM samples s
LEFT JOIN LATERAL (
    SELECT * FROM transcript_revisions 
    WHERE sample_id = s.sample_id 
    ORDER BY version DESC LIMIT 1
) tr ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM translation_revisions 
    WHERE sample_id = s.sample_id 
    ORDER BY version DESC LIMIT 1
) tl ON TRUE
LEFT JOIN samples ps ON s.parent_sample_id = ps.sample_id
LEFT JOIN sources src ON s.source_id = src.source_id
WHERE s.is_deleted = FALSE;

-- View: Review queue for Label Studio
CREATE OR REPLACE VIEW v_review_queue AS
SELECT 
    s.sample_id,
    s.external_id,
    s.pipeline_type,
    s.processing_state,
    s.priority,
    s.quality_score,
    s.cs_ratio,
    s.duration_seconds,
    s.audio_file_path,
    s.text_file_path,
    s.created_at,
    -- Determine next task type based on state
    CASE 
        WHEN s.processing_state IN ('RAW', 'VAD_SEGMENTED') THEN 'transcript_verification'::annotation_task
        WHEN s.processing_state = 'ALIGNED' THEN 'timestamp_alignment'::annotation_task
        WHEN s.processing_state = 'TRANSLATED' THEN 'translation_review'::annotation_task
        ELSE 'quality_assessment'::annotation_task
    END AS suggested_task_type,
    -- Count existing annotations
    (SELECT COUNT(*) FROM annotations a WHERE a.sample_id = s.sample_id AND a.status = 'completed') AS completed_annotations
FROM samples s
WHERE s.is_deleted = FALSE
  AND s.processing_state NOT IN ('REVIEWED', 'REJECTED')
ORDER BY s.priority DESC, s.created_at ASC;

-- View: Pipeline statistics
CREATE OR REPLACE VIEW v_pipeline_stats AS
SELECT 
    pipeline_type,
    processing_state,
    COUNT(*) AS sample_count,
    AVG(duration_seconds) AS avg_duration,
    AVG(cs_ratio) AS avg_cs_ratio,
    MIN(created_at) AS oldest_sample,
    MAX(created_at) AS newest_sample
FROM samples
WHERE is_deleted = FALSE
GROUP BY pipeline_type, processing_state
ORDER BY pipeline_type, processing_state;

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
    -- Get current state
    SELECT processing_state INTO v_old_state
    FROM samples WHERE sample_id = p_sample_id;
    
    IF v_old_state IS NULL THEN
        RAISE EXCEPTION 'Sample not found: %', p_sample_id;
    END IF;
    
    -- Update state
    UPDATE samples 
    SET processing_state = p_new_state,
        processed_at = NOW(),
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    -- Log transition
    INSERT INTO processing_logs (
        sample_id, operation, previous_state, new_state, executor, success
    ) VALUES (
        p_sample_id, 'state_transition', v_old_state, p_new_state, p_executor, TRUE
    );
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function: Add transcript revision and update sample version
CREATE OR REPLACE FUNCTION add_transcript_revision(
    p_sample_id UUID,
    p_transcript_text TEXT,
    p_revision_type VARCHAR(50),
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_timestamps JSONB DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system'
)
RETURNS UUID AS $$
DECLARE
    v_new_version INTEGER;
    v_revision_id UUID;
BEGIN
    -- Get next version number
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_new_version
    FROM transcript_revisions WHERE sample_id = p_sample_id;
    
    -- Insert revision
    INSERT INTO transcript_revisions (
        sample_id, version, transcript_text, revision_type, 
        revision_source, timestamps, created_by
    ) VALUES (
        p_sample_id, v_new_version, p_transcript_text, p_revision_type,
        p_revision_source, p_timestamps, p_created_by
    ) RETURNING revision_id INTO v_revision_id;
    
    -- Update sample's current version
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
    p_target_language VARCHAR(10),
    p_revision_type VARCHAR(50),
    p_source_transcript_revision_id UUID DEFAULT NULL,
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_confidence_score NUMERIC(5,4) DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system'
)
RETURNS UUID AS $$
DECLARE
    v_new_version INTEGER;
    v_revision_id UUID;
BEGIN
    -- Get next version number
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_new_version
    FROM translation_revisions WHERE sample_id = p_sample_id;
    
    -- Insert revision
    INSERT INTO translation_revisions (
        sample_id, version, source_transcript_revision_id, translation_text,
        target_language, revision_type, revision_source, confidence_score, created_by
    ) VALUES (
        p_sample_id, v_new_version, p_source_transcript_revision_id, p_translation_text,
        p_target_language, p_revision_type, p_revision_source, p_confidence_score, p_created_by
    ) RETURNING revision_id INTO v_revision_id;
    
    -- Update sample's current version
    UPDATE samples 
    SET current_translation_version = v_new_version,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    RETURN v_revision_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Get full lineage chain for a sample
CREATE OR REPLACE FUNCTION get_sample_lineage(p_sample_id UUID)
RETURNS TABLE (
    sample_id UUID,
    external_id VARCHAR(255),
    processing_state processing_state,
    derivation_step INTEGER,
    derivation_type VARCHAR(50)
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE lineage AS (
        -- Base case: the sample itself
        SELECT 
            s.sample_id,
            s.external_id,
            s.processing_state,
            0 AS derivation_step,
            NULL::VARCHAR(50) AS derivation_type
        FROM samples s
        WHERE s.sample_id = p_sample_id
        
        UNION ALL
        
        -- Recursive: ancestors
        SELECT 
            s.sample_id,
            s.external_id,
            s.processing_state,
            l.derivation_step + 1,
            sl.derivation_type
        FROM lineage l
        JOIN sample_lineage sl ON sl.descendant_sample_id = l.sample_id
        JOIN samples s ON s.sample_id = sl.ancestor_sample_id
    )
    SELECT * FROM lineage ORDER BY derivation_step;
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
    -- Try to find existing source
    SELECT source_id INTO v_source_id
    FROM sources 
    WHERE source_type = p_source_type AND external_id = p_external_id;
    
    -- Create if not exists
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

-- Trigger: Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_samples_updated
    BEFORE UPDATE ON samples
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_sources_updated
    BEFORE UPDATE ON sources
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_annotations_updated
    BEFORE UPDATE ON annotations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =============================================================================
-- COMMENTS (Documentation)
-- =============================================================================

COMMENT ON TABLE sources IS 'Tracks original content sources (YouTube channels, Substack blogs)';
COMMENT ON TABLE samples IS 'Core data units: videos, articles, audio segments with parent-child relationships';
COMMENT ON TABLE transcript_revisions IS 'Immutable audit trail for transcript changes (append-only)';
COMMENT ON TABLE translation_revisions IS 'Immutable audit trail for translations (append-only)';
COMMENT ON TABLE sample_lineage IS 'Tracks derivation relationships between samples (raw -> segment -> enhanced)';
COMMENT ON TABLE annotations IS 'Human annotation tasks and results for Label Studio integration';
COMMENT ON TABLE processing_logs IS 'Audit trail for all processing operations';

COMMENT ON VIEW v_sample_current_state IS 'Current state of all samples with latest transcript/translation';
COMMENT ON VIEW v_review_queue IS 'Priority queue for Label Studio review tasks';
COMMENT ON VIEW v_pipeline_stats IS 'Pipeline statistics grouped by type and state';

COMMENT ON FUNCTION transition_sample_state IS 'Transition sample state with automatic logging';
COMMENT ON FUNCTION add_transcript_revision IS 'Add new transcript revision and update sample version';
COMMENT ON FUNCTION add_translation_revision IS 'Add new translation revision and update sample version';
COMMENT ON FUNCTION get_sample_lineage IS 'Get full derivation chain for a sample';
COMMENT ON FUNCTION get_or_create_source IS 'Get existing source or create new one';

-- =============================================================================
-- LABEL STUDIO INTEGRATION FUNCTIONS
-- =============================================================================

-- Function: Lock a sample for annotation (optimistic locking)
CREATE OR REPLACE FUNCTION lock_sample_for_annotation(
    p_sample_id UUID,
    p_locked_by VARCHAR(255)
) RETURNS TABLE(
    success BOOLEAN,
    current_sync_version INTEGER,
    message TEXT
) AS $$
DECLARE
    v_current_version INTEGER;
    v_locked_at TIMESTAMPTZ;
BEGIN
    SELECT s.sync_version, s.locked_at
    INTO v_current_version, v_locked_at
    FROM samples s
    WHERE s.sample_id = p_sample_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, 'Sample not found'::TEXT;
        RETURN;
    END IF;

    -- Check if already locked (lock expires after 30 minutes)
    IF v_locked_at IS NOT NULL AND v_locked_at > NOW() - INTERVAL '30 minutes' THEN
        RETURN QUERY SELECT FALSE, v_current_version, 'Sample is already locked'::TEXT;
        RETURN;
    END IF;

    UPDATE samples
    SET locked_at = NOW(),
        locked_by = p_locked_by,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;

    RETURN QUERY SELECT TRUE, v_current_version, 'Sample locked successfully'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- Function: Unlock a sample after annotation
CREATE OR REPLACE FUNCTION unlock_sample(
    p_sample_id UUID,
    p_increment_version BOOLEAN DEFAULT FALSE
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE samples
    SET locked_at = NULL,
        locked_by = NULL,
        sync_version = CASE WHEN p_increment_version THEN sync_version + 1 ELSE sync_version END,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;
    
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function: Check if sample was modified during annotation
CREATE OR REPLACE FUNCTION check_annotation_conflict(
    p_sample_id UUID,
    p_expected_sync_version INTEGER
) RETURNS TABLE(
    has_conflict BOOLEAN,
    current_version INTEGER,
    expected_version INTEGER
) AS $$
DECLARE
    v_current_version INTEGER;
BEGIN
    SELECT s.sync_version INTO v_current_version
    FROM samples s
    WHERE s.sample_id = p_sample_id;

    IF v_current_version IS NULL THEN
        RETURN QUERY SELECT TRUE, NULL::INTEGER, p_expected_sync_version;
        RETURN;
    END IF;

    RETURN QUERY SELECT 
        v_current_version > p_expected_sync_version,
        v_current_version,
        p_expected_sync_version;
END;
$$ LANGUAGE plpgsql;

-- Function: Create conflict sample when crawler updated during annotation
CREATE OR REPLACE FUNCTION create_conflict_sample(
    p_original_sample_id UUID,
    p_reason TEXT DEFAULT 'Crawler updated during annotation'
) RETURNS UUID AS $$
DECLARE
    v_new_sample_id UUID;
BEGIN
    INSERT INTO samples (
        source_id, parent_sample_id, external_id, content_type,
        audio_file_path, text_file_path, pipeline_type, processing_state,
        duration_seconds, sample_rate, cs_ratio,
        source_metadata, acoustic_metadata, linguistic_metadata, processing_metadata,
        priority, dvc_commit_hash, audio_file_md5
    )
    SELECT
        source_id,
        p_original_sample_id,
        external_id || '_reflow_' || TO_CHAR(NOW(), 'YYYYMMDD_HH24MISS'),
        content_type,
        audio_file_path, text_file_path, pipeline_type,
        'RAW',  -- Reset to RAW for re-review
        duration_seconds, sample_rate, cs_ratio,
        source_metadata, acoustic_metadata, linguistic_metadata,
        processing_metadata || jsonb_build_object(
            'conflict_reason', p_reason,
            'original_sample_id', p_original_sample_id::TEXT,
            'created_from_conflict', TRUE
        ),
        priority + 10,  -- Increase priority for re-review
        dvc_commit_hash, audio_file_md5
    FROM samples
    WHERE sample_id = p_original_sample_id
    RETURNING sample_id INTO v_new_sample_id;

    INSERT INTO processing_logs (
        sample_id, operation, previous_state, new_state, executor,
        input_params, output_summary, success
    ) VALUES (
        p_original_sample_id, 'conflict_resolution', NULL, 'RAW', 'system',
        jsonb_build_object('original_sample_id', p_original_sample_id),
        jsonb_build_object('new_sample_id', v_new_sample_id, 'reason', p_reason),
        TRUE
    );

    RETURN v_new_sample_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Mark sample as gold standard for QC
CREATE OR REPLACE FUNCTION set_gold_standard(
    p_sample_id UUID,
    p_gold_score NUMERIC(3, 2),
    p_executor VARCHAR(255) DEFAULT 'system'
) RETURNS BOOLEAN AS $$
BEGIN
    IF p_gold_score < 0 OR p_gold_score > 1 THEN
        RAISE EXCEPTION 'Gold score must be between 0.00 and 1.00';
    END IF;

    UPDATE samples
    SET is_gold_standard = TRUE,
        gold_score = p_gold_score,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;

    INSERT INTO processing_logs (
        sample_id, operation, executor, output_summary, success
    ) VALUES (
        p_sample_id, 'set_gold_standard', p_executor,
        jsonb_build_object('gold_score', p_gold_score), TRUE
    );

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- LABEL STUDIO VIEWS
-- =============================================================================

-- View: Annotator accuracy against gold standard samples
CREATE OR REPLACE VIEW v_annotator_accuracy AS
WITH gold_annotations AS (
    SELECT 
        a.annotation_id, a.sample_id, a.task_type,
        a.assigned_to AS annotator_id, a.result AS annotator_result,
        a.completed_at, s.gold_score AS expected_score
    FROM annotations a
    JOIN samples s ON a.sample_id = s.sample_id
    WHERE s.is_gold_standard = TRUE AND a.status = 'completed'
),
annotator_stats AS (
    SELECT
        annotator_id, task_type,
        COUNT(*) AS total_gold_annotations,
        AVG(expected_score) AS avg_expected_score,
        COUNT(*) FILTER (WHERE annotator_result IS NOT NULL) AS completed_count
    FROM gold_annotations
    GROUP BY annotator_id, task_type
)
SELECT
    annotator_id, task_type, total_gold_annotations,
    avg_expected_score, completed_count,
    CASE 
        WHEN total_gold_annotations > 0 
        THEN ROUND((completed_count::NUMERIC / total_gold_annotations) * 100, 2)
        ELSE 0 
    END AS completion_rate_pct,
    NOW() AS calculated_at
FROM annotator_stats
ORDER BY annotator_id, task_type;

-- View: Gold standard samples for QC
CREATE OR REPLACE VIEW v_gold_standard_samples AS
SELECT
    s.sample_id, s.external_id, s.content_type, s.pipeline_type,
    s.processing_state, s.gold_score, s.audio_file_path, s.created_at,
    COUNT(a.annotation_id) AS annotation_count,
    COUNT(a.annotation_id) FILTER (WHERE a.status = 'completed') AS completed_count
FROM samples s
LEFT JOIN annotations a ON s.sample_id = a.sample_id
WHERE s.is_gold_standard = TRUE AND s.is_deleted = FALSE
GROUP BY s.sample_id
ORDER BY s.created_at DESC;

-- View: DVC sync and lock status
CREATE OR REPLACE VIEW v_sync_status AS
SELECT
    s.sample_id, s.external_id, s.processing_state, s.sync_version,
    s.dvc_commit_hash, s.audio_file_md5, s.locked_at, s.locked_by,
    CASE 
        WHEN s.locked_at IS NULL THEN 'unlocked'
        WHEN s.locked_at > NOW() - INTERVAL '30 minutes' THEN 'locked'
        ELSE 'lock_expired'
    END AS lock_status,
    s.updated_at,
    EXISTS (
        SELECT 1 FROM annotations a 
        WHERE a.sample_id = s.sample_id AND a.status IN ('pending', 'in_progress')
    ) AS has_pending_annotation
FROM samples s
WHERE s.is_deleted = FALSE
ORDER BY s.updated_at DESC;

-- =============================================================================
-- SYNC VERSION TRIGGER
-- =============================================================================

-- Auto-increment sync_version when file paths change (crawler update)
CREATE OR REPLACE FUNCTION trigger_increment_sync_version()
RETURNS TRIGGER AS $$
BEGIN
    IF (OLD.audio_file_path IS DISTINCT FROM NEW.audio_file_path) OR
       (OLD.text_file_path IS DISTINCT FROM NEW.text_file_path) OR
       (OLD.audio_file_md5 IS DISTINCT FROM NEW.audio_file_md5) OR
       (OLD.dvc_commit_hash IS DISTINCT FROM NEW.dvc_commit_hash) THEN
        NEW.sync_version := COALESCE(OLD.sync_version, 0) + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_increment_sync_version
    BEFORE UPDATE ON samples
    FOR EACH ROW
    EXECUTE FUNCTION trigger_increment_sync_version();

-- Add comments for new functions
COMMENT ON FUNCTION lock_sample_for_annotation IS 'Lock sample for annotation with 30-minute expiry';
COMMENT ON FUNCTION unlock_sample IS 'Unlock sample after annotation, optionally increment version';
COMMENT ON FUNCTION check_annotation_conflict IS 'Check if sample modified during annotation';
COMMENT ON FUNCTION create_conflict_sample IS 'Create new sample when conflict detected';
COMMENT ON FUNCTION set_gold_standard IS 'Mark sample as gold standard for QC';
COMMENT ON VIEW v_annotator_accuracy IS 'Annotator accuracy against gold standard samples';
COMMENT ON VIEW v_gold_standard_samples IS 'List of gold standard samples';
COMMENT ON VIEW v_sync_status IS 'DVC sync and lock status for all samples';

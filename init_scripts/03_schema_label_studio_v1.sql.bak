-- =============================================================================
-- init_scripts/03_schema_label_studio_v1.sql
-- Schema additions for Label Studio integration with DVC versioning
-- 
-- New Features:
--   1. DVC version tracking (dvc_commit_hash, audio_file_md5)
--   2. Conflict resolution support (sync_version, locked_at, locked_by)
--   3. Gold standard quality control (is_gold_standard, gold_score)
--   4. Annotator accuracy tracking view
-- =============================================================================

-- =============================================================================
-- ADD NEW COLUMNS TO samples TABLE
-- =============================================================================

-- DVC version tracking
ALTER TABLE samples
ADD COLUMN IF NOT EXISTS dvc_commit_hash VARCHAR(40);

ALTER TABLE samples
ADD COLUMN IF NOT EXISTS audio_file_md5 VARCHAR(32);

-- Sync version for optimistic locking (conflict detection)
ALTER TABLE samples
ADD COLUMN IF NOT EXISTS sync_version INTEGER DEFAULT 1;

-- Locking for annotation in progress
ALTER TABLE samples
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;

ALTER TABLE samples
ADD COLUMN IF NOT EXISTS locked_by VARCHAR(255);

-- Gold standard for quality control
ALTER TABLE samples
ADD COLUMN IF NOT EXISTS is_gold_standard BOOLEAN DEFAULT FALSE;

ALTER TABLE samples
ADD COLUMN IF NOT EXISTS gold_score NUMERIC(3, 2);

-- Index for gold standard samples
CREATE INDEX IF NOT EXISTS idx_samples_gold_standard 
ON samples(is_gold_standard, processing_state)
WHERE is_gold_standard = TRUE;

-- Index for locked samples
CREATE INDEX IF NOT EXISTS idx_samples_locked 
ON samples(locked_at)
WHERE locked_at IS NOT NULL;

-- Index for DVC commit hash lookup
CREATE INDEX IF NOT EXISTS idx_samples_dvc_commit 
ON samples(dvc_commit_hash)
WHERE dvc_commit_hash IS NOT NULL;

-- =============================================================================
-- ADD CONFLICT TRACKING TO annotations TABLE
-- =============================================================================

-- Track if sample was modified during annotation (conflict)
ALTER TABLE annotations
ADD COLUMN IF NOT EXISTS sample_sync_version_at_start INTEGER;

ALTER TABLE annotations
ADD COLUMN IF NOT EXISTS conflict_detected BOOLEAN DEFAULT FALSE;

ALTER TABLE annotations
ADD COLUMN IF NOT EXISTS conflict_resolution VARCHAR(50);
-- Values: 'human_wins', 'crawler_wins', 'merged', 'pending_reflow'

-- =============================================================================
-- NEW ENUM FOR CONFLICT RESOLUTION
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'conflict_resolution_type') THEN
        CREATE TYPE conflict_resolution_type AS ENUM (
            'human_wins',
            'crawler_wins', 
            'merged',
            'pending_reflow',
            'none'
        );
    END IF;
END $$;

-- =============================================================================
-- FUNCTION: lock_sample_for_annotation
-- Purpose: Lock a sample when sending to Label Studio
-- =============================================================================

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
    -- Check if sample exists and is not already locked
    SELECT s.sync_version, s.locked_at
    INTO v_current_version, v_locked_at
    FROM samples s
    WHERE s.sample_id = p_sample_id
    FOR UPDATE;  -- Lock row for update

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, 'Sample not found'::TEXT;
        RETURN;
    END IF;

    -- Check if already locked by someone else (lock expires after 30 minutes)
    IF v_locked_at IS NOT NULL AND v_locked_at > NOW() - INTERVAL '30 minutes' THEN
        RETURN QUERY SELECT FALSE, v_current_version, 'Sample is already locked'::TEXT;
        RETURN;
    END IF;

    -- Lock the sample
    UPDATE samples
    SET locked_at = NOW(),
        locked_by = p_locked_by,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;

    RETURN QUERY SELECT TRUE, v_current_version, 'Sample locked successfully'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- FUNCTION: unlock_sample
-- Purpose: Unlock a sample after annotation is complete or cancelled
-- =============================================================================

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

-- =============================================================================
-- FUNCTION: check_annotation_conflict
-- Purpose: Check if sample was modified during annotation
-- =============================================================================

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

-- =============================================================================
-- FUNCTION: create_conflict_sample
-- Purpose: Create a new sample when conflict detected (crawler updated during annotation)
-- =============================================================================

CREATE OR REPLACE FUNCTION create_conflict_sample(
    p_original_sample_id UUID,
    p_reason TEXT DEFAULT 'Crawler updated during annotation'
) RETURNS UUID AS $$
DECLARE
    v_new_sample_id UUID;
BEGIN
    -- Create new sample as child of original with PENDING_REFLOW state indicator
    INSERT INTO samples (
        source_id,
        parent_sample_id,
        external_id,
        content_type,
        audio_file_path,
        text_file_path,
        pipeline_type,
        processing_state,
        duration_seconds,
        sample_rate,
        cs_ratio,
        source_metadata,
        acoustic_metadata,
        linguistic_metadata,
        processing_metadata,
        priority,
        dvc_commit_hash,
        audio_file_md5
    )
    SELECT
        source_id,
        p_original_sample_id,  -- Set parent to original
        external_id || '_reflow_' || TO_CHAR(NOW(), 'YYYYMMDD_HH24MISS'),
        content_type,
        audio_file_path,
        text_file_path,
        pipeline_type,
        'RAW',  -- Reset to RAW for re-review
        duration_seconds,
        sample_rate,
        cs_ratio,
        source_metadata,
        acoustic_metadata,
        linguistic_metadata,
        processing_metadata || jsonb_build_object(
            'conflict_reason', p_reason,
            'original_sample_id', p_original_sample_id::TEXT,
            'created_from_conflict', TRUE
        ),
        priority + 10,  -- Increase priority for re-review
        dvc_commit_hash,
        audio_file_md5
    FROM samples
    WHERE sample_id = p_original_sample_id
    RETURNING sample_id INTO v_new_sample_id;

    -- Log the conflict
    INSERT INTO processing_logs (
        sample_id,
        operation,
        previous_state,
        new_state,
        executor,
        input_params,
        output_summary,
        success
    ) VALUES (
        p_original_sample_id,
        'conflict_resolution',
        NULL,
        'RAW',
        'system',
        jsonb_build_object('original_sample_id', p_original_sample_id),
        jsonb_build_object('new_sample_id', v_new_sample_id, 'reason', p_reason),
        TRUE
    );

    RETURN v_new_sample_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VIEW: v_annotator_accuracy
-- Purpose: Compare annotator submissions against gold standard samples
-- =============================================================================

CREATE OR REPLACE VIEW v_annotator_accuracy AS
WITH gold_annotations AS (
    -- Get annotations for gold standard samples
    SELECT 
        a.annotation_id,
        a.sample_id,
        a.task_type,
        a.assigned_to AS annotator_id,
        a.result AS annotator_result,
        a.completed_at,
        s.gold_score AS expected_score,
        s.is_gold_standard
    FROM annotations a
    JOIN samples s ON a.sample_id = s.sample_id
    WHERE s.is_gold_standard = TRUE
      AND a.status = 'completed'
),
annotator_stats AS (
    -- Calculate accuracy per annotator
    SELECT
        annotator_id,
        task_type,
        COUNT(*) AS total_gold_annotations,
        AVG(expected_score) AS avg_expected_score,
        -- Calculate agreement rate (simplified - would need custom comparison logic)
        COUNT(*) FILTER (WHERE annotator_result IS NOT NULL) AS completed_count
    FROM gold_annotations
    GROUP BY annotator_id, task_type
)
SELECT
    annotator_id,
    task_type,
    total_gold_annotations,
    avg_expected_score,
    completed_count,
    CASE 
        WHEN total_gold_annotations > 0 
        THEN ROUND((completed_count::NUMERIC / total_gold_annotations) * 100, 2)
        ELSE 0 
    END AS completion_rate_pct,
    -- Add timestamp for freshness
    NOW() AS calculated_at
FROM annotator_stats
ORDER BY annotator_id, task_type;

-- =============================================================================
-- VIEW: v_gold_standard_samples
-- Purpose: List all gold standard samples for quality control
-- =============================================================================

CREATE OR REPLACE VIEW v_gold_standard_samples AS
SELECT
    s.sample_id,
    s.external_id,
    s.content_type,
    s.pipeline_type,
    s.processing_state,
    s.gold_score,
    s.audio_file_path,
    s.created_at,
    -- Count annotations against this gold sample
    COUNT(a.annotation_id) AS annotation_count,
    COUNT(a.annotation_id) FILTER (WHERE a.status = 'completed') AS completed_count
FROM samples s
LEFT JOIN annotations a ON s.sample_id = a.sample_id
WHERE s.is_gold_standard = TRUE
  AND s.is_deleted = FALSE
GROUP BY s.sample_id
ORDER BY s.created_at DESC;

-- =============================================================================
-- VIEW: v_sync_status
-- Purpose: Overview of DVC sync and lock status for all samples
-- =============================================================================

CREATE OR REPLACE VIEW v_sync_status AS
SELECT
    s.sample_id,
    s.external_id,
    s.processing_state,
    s.sync_version,
    s.dvc_commit_hash,
    s.audio_file_md5,
    s.locked_at,
    s.locked_by,
    CASE 
        WHEN s.locked_at IS NULL THEN 'unlocked'
        WHEN s.locked_at > NOW() - INTERVAL '30 minutes' THEN 'locked'
        ELSE 'lock_expired'
    END AS lock_status,
    s.updated_at,
    -- Check for pending annotations
    EXISTS (
        SELECT 1 FROM annotations a 
        WHERE a.sample_id = s.sample_id 
          AND a.status IN ('pending', 'in_progress')
    ) AS has_pending_annotation
FROM samples s
WHERE s.is_deleted = FALSE
ORDER BY s.updated_at DESC;

-- =============================================================================
-- FUNCTION: set_gold_standard
-- Purpose: Mark a sample as gold standard with expected score
-- =============================================================================

CREATE OR REPLACE FUNCTION set_gold_standard(
    p_sample_id UUID,
    p_gold_score NUMERIC(3, 2),
    p_executor VARCHAR(255) DEFAULT 'system'
) RETURNS BOOLEAN AS $$
BEGIN
    -- Validate score range
    IF p_gold_score < 0 OR p_gold_score > 1 THEN
        RAISE EXCEPTION 'Gold score must be between 0.00 and 1.00';
    END IF;

    UPDATE samples
    SET is_gold_standard = TRUE,
        gold_score = p_gold_score,
        updated_at = NOW()
    WHERE sample_id = p_sample_id;

    -- Log the operation
    INSERT INTO processing_logs (
        sample_id,
        operation,
        executor,
        output_summary,
        success
    ) VALUES (
        p_sample_id,
        'set_gold_standard',
        p_executor,
        jsonb_build_object('gold_score', p_gold_score),
        TRUE
    );

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGER: auto_increment_sync_version
-- Purpose: Auto-increment sync_version when sample is modified by crawler
-- =============================================================================

CREATE OR REPLACE FUNCTION trigger_increment_sync_version()
RETURNS TRIGGER AS $$
BEGIN
    -- Only increment if audio/text file changed (crawler update)
    IF (OLD.audio_file_path IS DISTINCT FROM NEW.audio_file_path) OR
       (OLD.text_file_path IS DISTINCT FROM NEW.text_file_path) OR
       (OLD.audio_file_md5 IS DISTINCT FROM NEW.audio_file_md5) OR
       (OLD.dvc_commit_hash IS DISTINCT FROM NEW.dvc_commit_hash) THEN
        NEW.sync_version := COALESCE(OLD.sync_version, 0) + 1;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_increment_sync_version ON samples;
CREATE TRIGGER trg_increment_sync_version
    BEFORE UPDATE ON samples
    FOR EACH ROW
    EXECUTE FUNCTION trigger_increment_sync_version();

-- =============================================================================
-- GRANT PERMISSIONS (if using roles)
-- =============================================================================

-- Uncomment and modify if using role-based access:
-- GRANT SELECT ON v_annotator_accuracy TO readonly_role;
-- GRANT SELECT ON v_gold_standard_samples TO readonly_role;
-- GRANT SELECT ON v_sync_status TO readonly_role;
-- GRANT EXECUTE ON FUNCTION lock_sample_for_annotation TO app_role;
-- GRANT EXECUTE ON FUNCTION unlock_sample TO app_role;

-- =============================================================================
-- init_scripts/02_review_system_migration.sql
-- Migration: Unified Review System for Label Studio
--
-- This migration adds support for chunked review workflow:
--   TRANSLATED → REVIEW_PREPARED → (review) → VERIFIED → FINAL
--
-- Key additions:
--   1. REVIEW_PREPARED and VERIFIED processing states
--   2. review_chunks table for 15-sentence review batches
--   3. sentence_reviews table for per-sentence corrections
--   4. unified_review annotation task type
-- =============================================================================

-- =============================================================================
-- STEP 1: Add new processing states
-- =============================================================================

-- Add REVIEW_PREPARED and VERIFIED states to the enum
-- Note: PostgreSQL requires recreating the enum or using ALTER TYPE ADD VALUE

-- Check if REVIEW_PREPARED already exists before adding
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum 
        WHERE enumlabel = 'REVIEW_PREPARED' 
        AND enumtypid = 'processing_state'::regtype
    ) THEN
        ALTER TYPE processing_state ADD VALUE 'REVIEW_PREPARED' AFTER 'TRANSLATED';
    END IF;
END $$;

-- Check if VERIFIED already exists before adding
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum 
        WHERE enumlabel = 'VERIFIED' 
        AND enumtypid = 'processing_state'::regtype
    ) THEN
        ALTER TYPE processing_state ADD VALUE 'VERIFIED' AFTER 'REVIEW_PREPARED';
    END IF;
END $$;

-- =============================================================================
-- STEP 2: Add unified_review to annotation_task enum
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum 
        WHERE enumlabel = 'unified_review' 
        AND enumtypid = 'annotation_task'::regtype
    ) THEN
        ALTER TYPE annotation_task ADD VALUE 'unified_review';
    END IF;
END $$;

-- =============================================================================
-- STEP 3: Create review_chunks table
-- Purpose: Track 15-sentence chunks for Label Studio review tasks
-- =============================================================================

CREATE TABLE IF NOT EXISTS review_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Parent relationship
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Chunk ordering
    chunk_index INTEGER NOT NULL,           -- 0-based index within sample
    
    -- Sentence range (inclusive)
    start_sentence_idx INTEGER NOT NULL,    -- First sentence index in this chunk
    end_sentence_idx INTEGER NOT NULL,      -- Last sentence index in this chunk
    sentence_count INTEGER GENERATED ALWAYS AS (end_sentence_idx - start_sentence_idx + 1) STORED,
    
    -- Audio timing (for the chunk's audio span)
    start_time_ms INTEGER NOT NULL,         -- Start time of first sentence
    end_time_ms INTEGER NOT NULL,           -- End time of last sentence
    
    -- Review status
    status annotation_status NOT NULL DEFAULT 'pending',
    
    -- Label Studio integration
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    
    -- Review metadata
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMPTZ,
    review_time_seconds INTEGER,            -- Time spent reviewing
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (sample_id, chunk_index)
);

-- Indexes for review_chunks
CREATE INDEX IF NOT EXISTS idx_review_chunks_sample ON review_chunks(sample_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_review_chunks_status ON review_chunks(status) WHERE status != 'completed';
CREATE INDEX IF NOT EXISTS idx_review_chunks_ls_task ON review_chunks(label_studio_task_id) WHERE label_studio_task_id IS NOT NULL;

-- =============================================================================
-- STEP 4: Create sentence_reviews table
-- Purpose: Store per-sentence corrections from unified review
-- =============================================================================

CREATE TABLE IF NOT EXISTS sentence_reviews (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    chunk_id UUID NOT NULL REFERENCES review_chunks(chunk_id) ON DELETE CASCADE,
    sample_id UUID NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    
    -- Sentence identification
    sentence_idx INTEGER NOT NULL,          -- Global sentence index within sample
    
    -- Original values (from Gemini processing)
    original_start_ms INTEGER NOT NULL,
    original_end_ms INTEGER NOT NULL,
    original_transcript TEXT NOT NULL,
    original_translation TEXT NOT NULL,
    
    -- Reviewed/corrected values (NULL if unchanged)
    reviewed_start_ms INTEGER,              -- Adjusted start time
    reviewed_end_ms INTEGER,                -- Adjusted end time
    reviewed_transcript TEXT,               -- Corrected transcript
    reviewed_translation TEXT,              -- Corrected translation
    
    -- Review flags
    is_boundary_adjusted BOOLEAN DEFAULT FALSE,
    is_transcript_corrected BOOLEAN DEFAULT FALSE,
    is_translation_corrected BOOLEAN DEFAULT FALSE,
    is_rejected BOOLEAN DEFAULT FALSE,      -- Mark sentence for exclusion
    rejection_reason TEXT,
    
    -- Quality notes
    reviewer_notes TEXT,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (sample_id, sentence_idx)
);

-- Indexes for sentence_reviews
CREATE INDEX IF NOT EXISTS idx_sentence_reviews_chunk ON sentence_reviews(chunk_id);
CREATE INDEX IF NOT EXISTS idx_sentence_reviews_sample ON sentence_reviews(sample_id, sentence_idx);
CREATE INDEX IF NOT EXISTS idx_sentence_reviews_adjusted ON sentence_reviews(is_boundary_adjusted) 
    WHERE is_boundary_adjusted = TRUE;
CREATE INDEX IF NOT EXISTS idx_sentence_reviews_rejected ON sentence_reviews(is_rejected) 
    WHERE is_rejected = TRUE;

-- =============================================================================
-- STEP 5: Add trigger for updated_at
-- =============================================================================

CREATE TRIGGER tr_review_chunks_updated BEFORE UPDATE ON review_chunks
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_sentence_reviews_updated BEFORE UPDATE ON sentence_reviews
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- =============================================================================
-- STEP 6: Helper functions for review workflow
-- =============================================================================

-- Function: Create review chunks for a sample
-- Splits sentences into chunks of specified size (default 15)
CREATE OR REPLACE FUNCTION create_review_chunks(
    p_sample_id UUID,
    p_chunk_size INTEGER DEFAULT 15
)
RETURNS INTEGER AS $$
DECLARE
    v_transcript_rev RECORD;
    v_sentences JSONB;
    v_sentence_count INTEGER;
    v_chunk_count INTEGER;
    v_chunk_idx INTEGER := 0;
    v_start_idx INTEGER;
    v_end_idx INTEGER;
    v_start_ms INTEGER;
    v_end_ms INTEGER;
BEGIN
    -- Get latest transcript revision with sentence timestamps
    SELECT * INTO v_transcript_rev
    FROM transcript_revisions
    WHERE sample_id = p_sample_id
      AND sentence_timestamps IS NOT NULL
    ORDER BY version DESC
    LIMIT 1;
    
    IF v_transcript_rev IS NULL THEN
        RAISE EXCEPTION 'No transcript revision with sentence timestamps found for sample %', p_sample_id;
    END IF;
    
    v_sentences := v_transcript_rev.sentence_timestamps;
    v_sentence_count := jsonb_array_length(v_sentences);
    
    IF v_sentence_count = 0 THEN
        RAISE EXCEPTION 'No sentences found in transcript for sample %', p_sample_id;
    END IF;
    
    -- Delete existing chunks for this sample (in case of re-preparation)
    DELETE FROM review_chunks WHERE sample_id = p_sample_id;
    
    -- Create chunks
    v_start_idx := 0;
    WHILE v_start_idx < v_sentence_count LOOP
        v_end_idx := LEAST(v_start_idx + p_chunk_size - 1, v_sentence_count - 1);
        
        -- Get timing from sentences
        v_start_ms := ((v_sentences->v_start_idx)->>'start')::NUMERIC * 1000;
        v_end_ms := ((v_sentences->v_end_idx)->>'end')::NUMERIC * 1000;
        
        INSERT INTO review_chunks (
            sample_id, chunk_index, 
            start_sentence_idx, end_sentence_idx,
            start_time_ms, end_time_ms
        ) VALUES (
            p_sample_id, v_chunk_idx,
            v_start_idx, v_end_idx,
            v_start_ms, v_end_ms
        );
        
        v_chunk_idx := v_chunk_idx + 1;
        v_start_idx := v_end_idx + 1;
    END LOOP;
    
    RETURN v_chunk_idx;  -- Number of chunks created
END;
$$ LANGUAGE plpgsql;

-- Function: Initialize sentence reviews for a chunk
-- Creates sentence_reviews records from transcript revision
CREATE OR REPLACE FUNCTION init_sentence_reviews_for_chunk(
    p_chunk_id UUID
)
RETURNS INTEGER AS $$
DECLARE
    v_chunk RECORD;
    v_transcript_rev RECORD;
    v_sentences JSONB;
    v_sentence JSONB;
    v_idx INTEGER;
    v_count INTEGER := 0;
BEGIN
    -- Get chunk info
    SELECT * INTO v_chunk
    FROM review_chunks
    WHERE chunk_id = p_chunk_id;
    
    IF v_chunk IS NULL THEN
        RAISE EXCEPTION 'Chunk not found: %', p_chunk_id;
    END IF;
    
    -- Get latest transcript revision
    SELECT * INTO v_transcript_rev
    FROM transcript_revisions
    WHERE sample_id = v_chunk.sample_id
      AND sentence_timestamps IS NOT NULL
    ORDER BY version DESC
    LIMIT 1;
    
    v_sentences := v_transcript_rev.sentence_timestamps;
    
    -- Create sentence reviews for sentences in this chunk
    FOR v_idx IN v_chunk.start_sentence_idx..v_chunk.end_sentence_idx LOOP
        v_sentence := v_sentences->v_idx;
        
        INSERT INTO sentence_reviews (
            chunk_id, sample_id, sentence_idx,
            original_start_ms, original_end_ms,
            original_transcript, original_translation
        ) VALUES (
            p_chunk_id, v_chunk.sample_id, v_idx,
            (v_sentence->>'start')::NUMERIC * 1000,
            (v_sentence->>'end')::NUMERIC * 1000,
            v_sentence->>'text',
            COALESCE(v_sentence->>'translation', '')
        )
        ON CONFLICT (sample_id, sentence_idx) DO UPDATE SET
            chunk_id = EXCLUDED.chunk_id,
            original_start_ms = EXCLUDED.original_start_ms,
            original_end_ms = EXCLUDED.original_end_ms,
            original_transcript = EXCLUDED.original_transcript,
            original_translation = EXCLUDED.original_translation,
            updated_at = NOW();
        
        v_count := v_count + 1;
    END LOOP;
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Check if all chunks for a sample are completed
CREATE OR REPLACE FUNCTION check_sample_review_complete(
    p_sample_id UUID
)
RETURNS BOOLEAN AS $$
DECLARE
    v_incomplete_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_incomplete_count
    FROM review_chunks
    WHERE sample_id = p_sample_id
      AND status != 'completed';
    
    RETURN v_incomplete_count = 0;
END;
$$ LANGUAGE plpgsql;

-- Function: Get review progress for a sample
CREATE OR REPLACE FUNCTION get_review_progress(
    p_sample_id UUID
)
RETURNS TABLE(
    total_chunks INTEGER,
    completed_chunks INTEGER,
    pending_chunks INTEGER,
    in_progress_chunks INTEGER,
    total_sentences INTEGER,
    reviewed_sentences INTEGER,
    rejected_sentences INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (SELECT COUNT(*)::INTEGER FROM review_chunks WHERE sample_id = p_sample_id) AS total_chunks,
        (SELECT COUNT(*)::INTEGER FROM review_chunks WHERE sample_id = p_sample_id AND status = 'completed') AS completed_chunks,
        (SELECT COUNT(*)::INTEGER FROM review_chunks WHERE sample_id = p_sample_id AND status = 'pending') AS pending_chunks,
        (SELECT COUNT(*)::INTEGER FROM review_chunks WHERE sample_id = p_sample_id AND status = 'in_progress') AS in_progress_chunks,
        (SELECT COUNT(*)::INTEGER FROM sentence_reviews WHERE sample_id = p_sample_id) AS total_sentences,
        (SELECT COUNT(*)::INTEGER FROM sentence_reviews WHERE sample_id = p_sample_id 
            AND (reviewed_transcript IS NOT NULL OR reviewed_translation IS NOT NULL OR is_boundary_adjusted)) AS reviewed_sentences,
        (SELECT COUNT(*)::INTEGER FROM sentence_reviews WHERE sample_id = p_sample_id AND is_rejected = TRUE) AS rejected_sentences;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- STEP 7: Update views for new workflow
-- =============================================================================

-- View: Review queue overview
CREATE OR REPLACE VIEW v_review_queue AS
SELECT 
    s.sample_id,
    s.external_id,
    s.source_metadata->>'title' AS video_title,
    s.duration_seconds,
    s.processing_state,
    COUNT(rc.chunk_id) AS total_chunks,
    COUNT(rc.chunk_id) FILTER (WHERE rc.status = 'completed') AS completed_chunks,
    COUNT(rc.chunk_id) FILTER (WHERE rc.status = 'pending') AS pending_chunks,
    COUNT(rc.chunk_id) FILTER (WHERE rc.status = 'in_progress') AS in_progress_chunks,
    s.created_at,
    s.updated_at
FROM samples s
LEFT JOIN review_chunks rc ON s.sample_id = rc.sample_id
WHERE s.processing_state IN ('REVIEW_PREPARED', 'VERIFIED')
  AND s.is_deleted = FALSE
GROUP BY s.sample_id
ORDER BY s.priority DESC, s.created_at ASC;

-- View: Sentence review statistics
CREATE OR REPLACE VIEW v_sentence_review_stats AS
SELECT 
    sr.sample_id,
    s.external_id,
    COUNT(*) AS total_sentences,
    COUNT(*) FILTER (WHERE sr.is_boundary_adjusted) AS boundary_adjusted,
    COUNT(*) FILTER (WHERE sr.is_transcript_corrected) AS transcript_corrected,
    COUNT(*) FILTER (WHERE sr.is_translation_corrected) AS translation_corrected,
    COUNT(*) FILTER (WHERE sr.is_rejected) AS rejected,
    ROUND(
        COUNT(*) FILTER (WHERE sr.is_boundary_adjusted OR sr.is_transcript_corrected OR sr.is_translation_corrected)::NUMERIC 
        / NULLIF(COUNT(*), 0) * 100, 
        1
    ) AS correction_rate_pct
FROM sentence_reviews sr
JOIN samples s ON sr.sample_id = s.sample_id
GROUP BY sr.sample_id, s.external_id;

-- =============================================================================
-- STEP 8: Comments
-- =============================================================================

COMMENT ON TABLE review_chunks IS 'Review chunks containing ~15 sentences for Label Studio unified review';
COMMENT ON TABLE sentence_reviews IS 'Per-sentence review corrections from unified review workflow';

COMMENT ON FUNCTION create_review_chunks IS 'Create review chunks for a sample (splits sentences into batches)';
COMMENT ON FUNCTION init_sentence_reviews_for_chunk IS 'Initialize sentence_reviews records for a chunk';
COMMENT ON FUNCTION check_sample_review_complete IS 'Check if all chunks for a sample have been reviewed';
COMMENT ON FUNCTION get_review_progress IS 'Get review progress statistics for a sample';

COMMENT ON VIEW v_review_queue IS 'Overview of samples in review pipeline with chunk progress';
COMMENT ON VIEW v_sentence_review_stats IS 'Statistics on sentence-level corrections';

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Log migration
INSERT INTO processing_logs (
    operation, success, output_summary, executor
) VALUES (
    'schema_migration_review_system',
    TRUE,
    '{"version": "02_review_system", "tables_added": ["review_chunks", "sentence_reviews"], "states_added": ["REVIEW_PREPARED", "VERIFIED"], "task_types_added": ["unified_review"]}'::JSONB,
    'migration_script'
);

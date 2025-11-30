-- =============================================================================
-- Migration: Add columns for Gemini unified processing pipeline
-- Run this on existing databases to add new columns for gemini_process.py
-- =============================================================================

-- Add new columns to transcript_revisions
ALTER TABLE transcript_revisions ADD COLUMN IF NOT EXISTS has_translation_issues BOOLEAN DEFAULT FALSE;
ALTER TABLE transcript_revisions ADD COLUMN IF NOT EXISTS translation_issue_indices INTEGER[];

-- Add new column to samples
ALTER TABLE samples ADD COLUMN IF NOT EXISTS needs_translation_review BOOLEAN DEFAULT FALSE;

-- Update the add_transcript_revision function to accept new parameters
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

-- Add comment for documentation
COMMENT ON COLUMN transcript_revisions.has_translation_issues IS 'Set to TRUE when some sentences have missing/failed translations';
COMMENT ON COLUMN transcript_revisions.translation_issue_indices IS 'Array of sentence indices (0-based) that need re-translation';
COMMENT ON COLUMN samples.needs_translation_review IS 'Set to TRUE when sample needs human translation review (from gemini_process)';

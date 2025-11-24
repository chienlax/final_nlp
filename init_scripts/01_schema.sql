-- init_scripts/01_schema.sql
CREATE TABLE IF NOT EXISTS dataset_ledger (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path TEXT NOT NULL,
    source_metadata JSONB,
    acoustic_meta JSONB,
    linguistic_meta JSONB,
    transcript_raw TEXT,
    transcript_corrected TEXT,
    translation TEXT,
    processing_state VARCHAR(20) CHECK (processing_state IN ('RAW', 'DENOISED', 'SEGMENTED', 'REVIEWED')),
    split_assignment VARCHAR(10)
);

-- Create an index for faster searching by state
CREATE INDEX idx_processing_state ON dataset_ledger(processing_state);
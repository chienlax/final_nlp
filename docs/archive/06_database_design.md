# 06. Database Design

This document explains the database schema for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## 1. Design Principles

1. **Separation of Concerns** - Samples, segments, revisions are separate entities
2. **Immutable Revisions** - Never update text content; create new versions
3. **Segment-Centric** - Training data organized by segments, not full videos
4. **Human Review Tracking** - Built-in support for 3-stage review workflow
5. **API Key Management** - Track Gemini API key rotation

---

## 2. Schema Overview

```
┌─────────────┐
│   sources   │
└──────┬──────┘
       │ 1:N
       ▼
┌─────────────────────────────────────────────────────────────┐
│                          samples                             │
│  (Full videos with processing_state tracking)               │
└──────────────────────────┬──────────────────────────────────┘
                           │ 1:N
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   segments   │    │ transcript_  │    │ translation_ │
│ (10-30s      │    │ revisions    │    │ revisions    │
│  chunks)     │    │              │    │              │
└──────┬───────┘    └──────────────┘    └──────────────┘
       │ 1:N
       ▼
┌──────────────────┐
│ segment_         │
│ translations     │
│ (Per-segment     │
│  translations)   │
└──────────────────┘

┌──────────────┐    ┌──────────────┐
│   api_keys   │    │ processing_  │
│ (Gemini key  │    │ logs         │
│  rotation)   │    │ (Audit)      │
└──────────────┘    └──────────────┘
```

---

## 3. ENUM Types

### processing_state

```sql
CREATE TYPE processing_state AS ENUM (
    'RAW',                  -- Just ingested
    'TRANSCRIPT_REVIEW',    -- In Label Studio (Round 1)
    'TRANSCRIPT_VERIFIED',  -- Human approved transcript
    'ALIGNED',              -- WhisperX alignment complete
    'SEGMENTED',            -- Audio segmented into chunks
    'SEGMENT_REVIEW',       -- In Label Studio (Round 2)
    'SEGMENT_VERIFIED',     -- Human approved segments
    'TRANSLATED',           -- Gemini translation complete
    'TRANSLATION_REVIEW',   -- In Label Studio (Round 3)
    'DENOISED',             -- DeepFilterNet complete
    'FINAL',                -- Ready for training
    'REJECTED'              -- Failed QC
);
```

### subtitle_type

```sql
CREATE TYPE subtitle_type AS ENUM (
    'manual',           -- Human-created subtitles
    'auto_generated'    -- YouTube auto-generated
);
```

### source_type

```sql
CREATE TYPE source_type AS ENUM (
    'youtube_channel'
);
```

---

## 4. Table Definitions

### sources

Track YouTube channels as data sources.

```sql
CREATE TABLE sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type source_type NOT NULL,
    external_id VARCHAR(255),        -- YouTube channel ID
    name VARCHAR(500),               -- Channel name
    url TEXT,                        -- Channel URL
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_type, external_id)
);
```

### samples

Main table for full videos with processing state tracking.

```sql
CREATE TABLE samples (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(source_id),
    
    -- Content identification
    external_id VARCHAR(255) UNIQUE,  -- Video ID
    audio_file_path TEXT NOT NULL,
    
    -- Subtitle tracking
    subtitle_type subtitle_type,
    
    -- Processing state
    processing_state processing_state NOT NULL DEFAULT 'RAW',
    
    -- Metadata
    duration_seconds NUMERIC(10, 2),
    cs_ratio NUMERIC(5, 4),
    source_metadata JSONB DEFAULT '{}',
    
    -- Version tracking
    current_transcript_version INTEGER DEFAULT 0,
    current_translation_version INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### segments

Audio segments (10-30s chunks) derived from full videos.

```sql
CREATE TABLE segments (
    segment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    segment_index INTEGER NOT NULL,
    audio_file_path TEXT NOT NULL,
    
    -- Timing
    start_time NUMERIC(10, 3) NOT NULL,
    end_time NUMERIC(10, 3) NOT NULL,
    duration NUMERIC(10, 3) NOT NULL,
    
    -- Transcript
    transcript_text TEXT NOT NULL,
    word_timestamps JSONB,
    alignment_score NUMERIC(5, 4),
    
    -- Review status
    is_verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    verified_by VARCHAR(255),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (sample_id, segment_index)
);
```

### transcript_revisions

Versioned transcripts (append-only).

```sql
CREATE TABLE transcript_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    version INTEGER NOT NULL,
    transcript_text TEXT NOT NULL,
    revision_type VARCHAR(50) NOT NULL,  -- 'raw', 'human_corrected', 'aligned'
    
    -- Alignment data
    word_timestamps JSONB,
    sentence_timestamps JSONB,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);
```

### translation_revisions

Versioned full-video translations.

```sql
CREATE TABLE translation_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    version INTEGER NOT NULL,
    translation_text TEXT NOT NULL,
    target_language VARCHAR(10) DEFAULT 'vi',
    revision_type VARCHAR(50) NOT NULL,  -- 'llm_generated', 'human_corrected'
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);
```

### segment_translations

Per-segment translations for training export.

```sql
CREATE TABLE segment_translations (
    translation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES segments(segment_id),
    
    translation_text TEXT NOT NULL,
    translation_version INTEGER NOT NULL,
    
    -- Review status
    is_verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    verified_by VARCHAR(255),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (segment_id, translation_version)
);
```

### api_keys

Gemini API key rotation tracking.

```sql
CREATE TABLE api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_name VARCHAR(100) NOT NULL UNIQUE,
    key_hash VARCHAR(64),               -- SHA-256 hash for verification
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    is_exhausted_today BOOLEAN DEFAULT FALSE,
    exhausted_at TIMESTAMPTZ,
    
    -- Usage tracking
    requests_today INTEGER DEFAULT 0,
    last_reset_date DATE DEFAULT CURRENT_DATE,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### processing_logs

Audit trail for all processing operations.

```sql
CREATE TABLE processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id),
    
    step_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    
    input_state processing_state,
    output_state processing_state,
    
    metadata JSONB DEFAULT '{}',
    error_message TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. Views

### v_pipeline_stats

Processing statistics by state.

```sql
CREATE VIEW v_pipeline_stats AS
SELECT 
    processing_state,
    COUNT(*) AS sample_count,
    AVG(duration_seconds) AS avg_duration,
    AVG(cs_ratio) AS avg_cs_ratio
FROM samples
GROUP BY processing_state
ORDER BY 
    CASE processing_state
        WHEN 'RAW' THEN 1
        WHEN 'TRANSCRIPT_REVIEW' THEN 2
        WHEN 'TRANSCRIPT_VERIFIED' THEN 3
        WHEN 'ALIGNED' THEN 4
        WHEN 'SEGMENTED' THEN 5
        WHEN 'SEGMENT_REVIEW' THEN 6
        WHEN 'SEGMENT_VERIFIED' THEN 7
        WHEN 'TRANSLATED' THEN 8
        WHEN 'TRANSLATION_REVIEW' THEN 9
        WHEN 'DENOISED' THEN 10
        WHEN 'FINAL' THEN 11
        WHEN 'REJECTED' THEN 12
    END;
```

### v_sample_overview

Sample details with latest transcript info.

```sql
CREATE VIEW v_sample_overview AS
SELECT 
    s.sample_id,
    s.external_id,
    s.processing_state,
    s.subtitle_type,
    s.duration_seconds,
    s.cs_ratio,
    s.current_transcript_version,
    s.current_translation_version,
    (SELECT COUNT(*) FROM segments WHERE sample_id = s.sample_id) AS segment_count,
    src.name AS source_name
FROM samples s
LEFT JOIN sources src ON s.source_id = src.source_id;
```

### v_api_key_status

Gemini API key rotation status.

```sql
CREATE VIEW v_api_key_status AS
SELECT 
    key_name,
    is_active,
    is_exhausted_today,
    requests_today,
    exhausted_at,
    last_reset_date
FROM api_keys
ORDER BY key_name;
```

### v_export_ready_segments

Segments ready for training export.

```sql
CREATE VIEW v_export_ready_segments AS
SELECT 
    seg.segment_id,
    seg.audio_file_path,
    seg.transcript_text,
    st.translation_text,
    seg.duration,
    seg.alignment_score,
    s.external_id AS video_id
FROM segments seg
JOIN samples s ON seg.sample_id = s.sample_id
JOIN segment_translations st ON seg.segment_id = st.segment_id
WHERE s.processing_state = 'FINAL'
  AND seg.is_verified = TRUE
  AND st.is_verified = TRUE;
```

---

## 6. Indexes

```sql
-- Fast lookup by processing state
CREATE INDEX idx_samples_state ON samples(processing_state);

-- Segment lookup by sample
CREATE INDEX idx_segments_sample ON segments(sample_id, segment_index);

-- Latest transcript revision
CREATE INDEX idx_transcript_rev ON transcript_revisions(sample_id, version DESC);

-- Translation by segment
CREATE INDEX idx_segment_trans ON segment_translations(segment_id);

-- API key lookup
CREATE INDEX idx_api_keys_active ON api_keys(is_active, is_exhausted_today);
```

---

## 7. Common Queries

### Get samples ready for alignment

```sql
SELECT sample_id, external_id, audio_file_path
FROM samples
WHERE processing_state = 'TRANSCRIPT_VERIFIED'
LIMIT 10;
```

### Get segments for a sample

```sql
SELECT 
    segment_index,
    audio_file_path,
    transcript_text,
    duration
FROM segments
WHERE sample_id = 'uuid-here'
ORDER BY segment_index;
```

### Get next available API key

```sql
SELECT key_name
FROM api_keys
WHERE is_active = TRUE
  AND is_exhausted_today = FALSE
ORDER BY requests_today ASC
LIMIT 1;
```

### Export training data

```sql
SELECT 
    seg.audio_file_path,
    seg.transcript_text AS source_text,
    st.translation_text AS target_text
FROM v_export_ready_segments
ORDER BY seg.segment_id;
```

---

## 8. State Transitions

```
RAW
 │
 ├──► TRANSCRIPT_REVIEW ──► TRANSCRIPT_VERIFIED
 │                                   │
 │                                   ▼
 │                               ALIGNED
 │                                   │
 │                                   ▼
 │                               SEGMENTED
 │                                   │
 │                                   ▼
 │                          SEGMENT_REVIEW ──► SEGMENT_VERIFIED
 │                                                    │
 │                                                    ▼
 │                                               TRANSLATED
 │                                                    │
 │                                                    ▼
 │                                          TRANSLATION_REVIEW
 │                                                    │
 │                                                    ▼
 │                                               DENOISED
 │                                                    │
 │                                                    ▼
 │                                                 FINAL
 │
 └──► REJECTED (at any stage)
```

---

## 9. Schema File

The complete schema is in `init_scripts/01_schema.sql`.

To apply manually:

```powershell
Get-Content init_scripts\01_schema.sql | docker exec -i postgres_nlp psql -U admin -d data_factory
```

---

## Related Documentation

- [04_workflow.md](04_workflow.md) - Pipeline workflow
- [05_scripts_details.md](05_scripts_details.md) - Script reference

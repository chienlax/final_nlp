# 06. Database Design

This document explains the database design rationale and schema structure for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Schema Evolution](#2-schema-evolution)
3. [Entity-Relationship Diagram](#3-entity-relationship-diagram)
4. [Table Definitions](#4-table-definitions)
5. [ENUM Types](#5-enum-types)
6. [Indexes Strategy](#6-indexes-strategy)
7. [Views](#7-views)
8. [Functions](#8-functions)
9. [Query Patterns](#9-query-patterns)

---

## 1. Design Philosophy

### Core Principles

1. **Separation of Concerns**
   - Sources, samples, revisions, and annotations are separate entities
   - Each table has a single responsibility
   - Clear relationships via foreign keys

2. **Immutable Audit Trail**
   - Transcript and translation changes are append-only revisions
   - Never update text content; always create new versions
   - Full history preserved for quality tracking

3. **Flexible Metadata**
   - JSONB columns for evolving requirements
   - Typed columns for frequently queried fields
   - Best of both: schema + flexibility

4. **Label Studio Optimized**
   - Indexes designed for annotation workflow queries
   - Review queue views for efficient task assignment
   - Annotation tracking integrated at the schema level

5. **Dual-Pipeline Support**
   - Audio-First (YouTube): RAW → ALIGNED → SEGMENTED → ENHANCED → TRANSLATED → REVIEWED
   - Text-First (Substack): RAW → NORMALIZED → CS_CHUNKED → TTS_GENERATED → TRANSLATED → REVIEWED

---

## 2. Schema Evolution

### V1 → V2 Migration

**V1 (Single Table)**
```sql
-- Old: Everything in one table
CREATE TABLE dataset_ledger (
    id SERIAL PRIMARY KEY,
    file_path TEXT,
    transcript TEXT,
    translation TEXT,
    status VARCHAR(50),
    metadata JSONB
);
```

**V2 (Multi-Table Design)**
```sql
-- New: Normalized structure
sources → samples → transcript_revisions
                  → translation_revisions
                  → annotations
                  → sample_lineage
                  → processing_logs
```

### Why Multi-Table?

| Problem (V1) | Solution (V2) |
|--------------|---------------|
| No revision history | `transcript_revisions` table |
| No source tracking | `sources` table |
| No annotation integration | `annotations` table |
| No segment relationships | `sample_lineage` table |
| No audit trail | `processing_logs` table |

---

## 3. Entity-Relationship Diagram

```
┌─────────────┐
│   sources   │
├─────────────┤
│ source_id   │────┐
│ source_type │    │
│ external_id │    │
│ name        │    │
│ url         │    │
│ metadata    │    │
└─────────────┘    │
                   │ 1:N
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                          samples                             │
├─────────────────────────────────────────────────────────────┤
│ sample_id (PK)                                               │
│ source_id (FK) ─────────────────────────────────────────────┘
│ parent_sample_id (FK, self-ref) ←───────────────────────────┐
│ external_id                                                  │
│ content_type (audio_primary | text_primary)                 │
│ pipeline_type                                                │
│ processing_state (RAW → ... → REVIEWED)                     │
│ audio_file_path                                              │
│ text_file_path                                               │
│ segment_index, start_time_ms, end_time_ms                   │
│ duration_seconds, cs_ratio, quality_score                   │
│ source_metadata, acoustic_metadata, linguistic_metadata     │
│ label_studio_project_id, label_studio_task_id               │
└────┬────────────────────┬────────────────────┬──────────────┘
     │ 1:N                │ 1:N                │ 1:N
     ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌─────────────┐
│ transcript_   │  │ translation_     │  │ annotations │
│ revisions     │  │ revisions        │  ├─────────────┤
├───────────────┤  ├──────────────────┤  │ task_type   │
│ revision_id   │  │ revision_id      │  │ status      │
│ sample_id(FK) │  │ sample_id(FK)    │  │ assigned_to │
│ version       │  │ version          │  │ result      │
│ transcript_   │  │ translation_     │  │ label_studio│
│   text        │  │   text           │  │   _ids      │
│ revision_type │  │ target_language  │  └─────────────┘
│ timestamps    │  │ revision_type    │
│ created_by    │  │ confidence_score │
└───────────────┘  │ source_transcript│
                   │   _revision_id   │
                   └──────────────────┘

                   Additional Tables
┌─────────────────┐     ┌──────────────────┐
│ sample_lineage  │     │ processing_logs  │
├─────────────────┤     ├──────────────────┤
│ ancestor_id(FK) │     │ sample_id(FK)    │
│ descendant_id   │     │ operation        │
│ derivation_type │     │ previous_state   │
│ derivation_step │     │ new_state        │
└─────────────────┘     │ executor         │
                        │ success          │
                        └──────────────────┘
```

---

## 4. Table Definitions

### 4.1 sources

**Purpose:** Track original content sources (YouTube channels, Substack blogs)

```sql
CREATE TABLE sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type source_type NOT NULL,    -- youtube_with_transcript, substack, etc.
    external_id VARCHAR(255),            -- YouTube channel ID, Substack slug
    name VARCHAR(500),                   -- Human-readable name
    url TEXT,                            -- Base URL
    metadata JSONB DEFAULT '{}',         -- Flexible: subscriber count, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_type, external_id)
);
```

**Key Design Decisions:**
- UUID primary key for distributed systems compatibility
- `source_type` + `external_id` uniqueness prevents duplicates
- JSONB for evolving metadata requirements

### 4.2 samples

**Purpose:** Core data units with processing state tracking

```sql
CREATE TABLE samples (
    sample_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    source_id UUID REFERENCES sources(source_id),
    parent_sample_id UUID REFERENCES samples(sample_id),  -- Self-referential
    
    -- Content identification
    external_id VARCHAR(255),            -- Video ID, article slug
    content_type content_type NOT NULL,  -- audio_primary, text_primary
    
    -- File references
    audio_file_path TEXT,
    text_file_path TEXT,
    
    -- Processing pipeline
    pipeline_type source_type NOT NULL,
    processing_state processing_state NOT NULL DEFAULT 'RAW',
    
    -- Segment metadata (for child samples)
    segment_index INTEGER,
    start_time_ms INTEGER,
    end_time_ms INTEGER,
    
    -- Version tracking (denormalized for fast access)
    current_transcript_version INTEGER DEFAULT 0,
    current_translation_version INTEGER DEFAULT 0,
    
    -- Queryable metadata
    duration_seconds NUMERIC(10, 2),
    sample_rate INTEGER DEFAULT 16000,
    cs_ratio NUMERIC(5, 4),              -- Code-switching ratio
    quality_score NUMERIC(3, 2),
    priority INTEGER DEFAULT 0,
    
    -- Flexible metadata (JSONB)
    source_metadata JSONB DEFAULT '{}',
    acoustic_metadata JSONB DEFAULT '{}',
    linguistic_metadata JSONB DEFAULT '{}',
    processing_metadata JSONB DEFAULT '{}',
    
    -- Label Studio integration
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    
    -- Soft delete
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    CONSTRAINT chk_file_path CHECK (
        audio_file_path IS NOT NULL OR text_file_path IS NOT NULL
    )
);
```

**Key Design Decisions:**
- Self-referential `parent_sample_id` for segment hierarchies
- `processing_state` enum for state machine tracking
- Denormalized version counters for O(1) "latest" queries
- Soft delete instead of hard delete for audit compliance

### 4.3 transcript_revisions

**Purpose:** Immutable transcript history (append-only)

```sql
CREATE TABLE transcript_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    version INTEGER NOT NULL,            -- Auto-incrementing per sample
    transcript_text TEXT NOT NULL,
    
    revision_type VARCHAR(50) NOT NULL,  -- raw, asr_generated, human_corrected, mfa_aligned
    revision_source VARCHAR(100),        -- youtube_api, whisper, annotator_123
    
    timestamps JSONB,                    -- [{start_ms, end_ms, text}, ...]
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);
```

**Key Design Decisions:**
- Never UPDATE, only INSERT new versions
- `timestamps` JSONB for word-level alignment data
- `revision_type` categorizes the source of changes

### 4.4 translation_revisions

**Purpose:** Immutable translation history with provenance

```sql
CREATE TABLE translation_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    version INTEGER NOT NULL,
    source_transcript_revision_id UUID REFERENCES transcript_revisions(revision_id),
    
    translation_text TEXT NOT NULL,
    source_language VARCHAR(10) DEFAULT 'vi-en',  -- Code-switched source
    target_language VARCHAR(10) NOT NULL,         -- 'vi' (translate to Vietnamese)
    
    revision_type VARCHAR(50) NOT NULL,  -- llm_generated, human_corrected, final
    revision_source VARCHAR(100),        -- gpt-4, annotator_456
    
    confidence_score NUMERIC(5, 4),
    bleu_score NUMERIC(5, 4),
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    
    UNIQUE (sample_id, version)
);
```

**Key Design Decisions:**
- Links back to specific transcript revision for reproducibility
- Quality metrics stored for model comparison

### 4.5 annotations

**Purpose:** Label Studio task and result tracking

```sql
CREATE TABLE annotations (
    annotation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    task_type annotation_task NOT NULL,  -- transcript_verification, translation_review, etc.
    status annotation_status NOT NULL DEFAULT 'pending',
    
    assigned_to VARCHAR(255),
    assigned_at TIMESTAMPTZ,
    
    label_studio_project_id INTEGER,
    label_studio_task_id INTEGER,
    label_studio_annotation_id INTEGER,
    
    result JSONB,                        -- Annotation result data
    time_spent_seconds INTEGER,
    confidence_score NUMERIC(3, 2),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    UNIQUE (sample_id, task_type, label_studio_annotation_id)
);
```

### 4.6 sample_lineage

**Purpose:** Track complex derivation relationships

```sql
CREATE TABLE sample_lineage (
    lineage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    ancestor_sample_id UUID NOT NULL REFERENCES samples(sample_id),
    descendant_sample_id UUID NOT NULL REFERENCES samples(sample_id),
    
    derivation_type VARCHAR(50) NOT NULL,  -- segmentation, enhancement, tts_generation
    derivation_step INTEGER NOT NULL,       -- Distance in chain (1 = direct)
    processing_params JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (ancestor_sample_id, descendant_sample_id),
    CHECK (ancestor_sample_id != descendant_sample_id)
);
```

**Use Case:** When a 10-minute video is segmented into 20 clips, each clip has a lineage record pointing to the parent video.

### 4.7 processing_logs

**Purpose:** Audit trail for all processing operations

```sql
CREATE TABLE processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id UUID REFERENCES samples(sample_id),
    
    operation VARCHAR(100) NOT NULL,     -- state_transition, enhancement, segmentation
    previous_state processing_state,
    new_state processing_state,
    
    executor VARCHAR(255),               -- Script name, container ID, user
    execution_time_ms INTEGER,
    
    input_params JSONB,
    output_summary JSONB,
    error_message TEXT,
    success BOOLEAN NOT NULL,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. ENUM Types

### 5.1 source_type

```sql
CREATE TYPE source_type AS ENUM (
    'youtube_with_transcript',
    'youtube_without_transcript',
    'substack',
    'manual_upload'
);
```

**Rationale:** Different sources require different processing pipelines.

### 5.2 processing_state

```sql
CREATE TYPE processing_state AS ENUM (
    'RAW',              -- Initial state after ingestion
    'ALIGNED',          -- MFA forced alignment complete
    'SEGMENTED',        -- Split into clips (transcript-based)
    'VAD_SEGMENTED',    -- Split into clips (VAD-based)
    'ENHANCED',         -- Audio enhancement (DeepFilterNet)
    'NORMALIZED',       -- Text normalization complete (text-first)
    'CS_CHUNKED',       -- CS chunks extracted (text-first)
    'TTS_GENERATED',    -- TTS audio generated (text-first)
    'TRANSLATED',       -- LLM translation complete
    'REVIEWED',         -- Human review passed
    'REJECTED'          -- Failed quality check
);
```

**State Transitions:**

```
Audio-First (with transcript):
RAW → ALIGNED → SEGMENTED → ENHANCED → TRANSLATED → REVIEWED

Audio-First (without transcript):
RAW → VAD_SEGMENTED → ALIGNED → ENHANCED → TRANSLATED → REVIEWED

Text-First:
RAW → NORMALIZED → CS_CHUNKED → TTS_GENERATED → TRANSLATED → REVIEWED
```

### 5.3 content_type

```sql
CREATE TYPE content_type AS ENUM (
    'audio_primary',    -- Audio file with optional transcript
    'text_primary'      -- Text file with optional synthesized audio
);
```

### 5.4 annotation_task

```sql
CREATE TYPE annotation_task AS ENUM (
    'transcript_verification',  -- Verify/correct ASR output
    'timestamp_alignment',      -- Verify word-level timestamps
    'translation_review',       -- Review LLM translations
    'quality_assessment'        -- Final quality check
);
```

### 5.5 annotation_status

```sql
CREATE TYPE annotation_status AS ENUM (
    'pending',      -- Awaiting assignment
    'in_progress',  -- Being worked on
    'completed',    -- Successfully finished
    'skipped',      -- Skipped (too hard, bad quality)
    'disputed'      -- Requires senior review
);
```

---

## 6. Indexes Strategy

### 6.1 Review Queue Index (Primary Workflow)

```sql
CREATE INDEX idx_samples_review_queue ON samples(
    processing_state, 
    priority DESC, 
    created_at ASC
) WHERE is_deleted = FALSE;
```

**Query Pattern:** "What needs review next?"
```sql
SELECT * FROM samples 
WHERE processing_state = 'ALIGNED' 
  AND is_deleted = FALSE
ORDER BY priority DESC, created_at ASC
LIMIT 100;
```

### 6.2 Segment Lookup

```sql
CREATE INDEX idx_samples_parent ON samples(parent_sample_id, segment_index)
WHERE parent_sample_id IS NOT NULL;
```

**Query Pattern:** "Get all segments of a video"
```sql
SELECT * FROM samples
WHERE parent_sample_id = 'uuid'
ORDER BY segment_index;
```

### 6.3 Latest Revision

```sql
CREATE INDEX idx_transcript_rev_latest ON transcript_revisions(
    sample_id, 
    version DESC
);
```

**Query Pattern:** "Get latest transcript"
```sql
SELECT * FROM transcript_revisions
WHERE sample_id = 'uuid'
ORDER BY version DESC
LIMIT 1;
```

### 6.4 CS Ratio Filtering

```sql
CREATE INDEX idx_samples_cs_ratio ON samples(cs_ratio DESC)
WHERE cs_ratio IS NOT NULL AND cs_ratio > 0;
```

**Query Pattern:** "Find high code-switching samples"
```sql
SELECT * FROM samples
WHERE cs_ratio > 0.3
ORDER BY cs_ratio DESC;
```

### 6.5 JSONB Metadata Search

```sql
CREATE INDEX idx_samples_source_meta ON samples USING GIN (source_metadata);
CREATE INDEX idx_samples_linguistic_meta ON samples USING GIN (linguistic_metadata);
```

**Query Pattern:** "Find samples from a specific channel"
```sql
SELECT * FROM samples
WHERE source_metadata @> '{"channel_id": "UCxxx"}'::jsonb;
```

---

## 7. Views

### 7.1 v_sample_current_state

**Purpose:** Consolidated view of samples with latest revisions

```sql
CREATE VIEW v_sample_current_state AS
SELECT 
    s.*,
    tr.transcript_text AS current_transcript,
    tr.timestamps AS transcript_timestamps,
    tl.translation_text AS current_translation,
    src.name AS source_name
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
LEFT JOIN sources src ON s.source_id = src.source_id
WHERE s.is_deleted = FALSE;
```

### 7.2 v_review_queue

**Purpose:** Label Studio task assignment queue

```sql
CREATE VIEW v_review_queue AS
SELECT 
    s.sample_id,
    s.processing_state,
    s.priority,
    CASE 
        WHEN s.processing_state IN ('RAW', 'VAD_SEGMENTED') THEN 'transcript_verification'
        WHEN s.processing_state = 'ALIGNED' THEN 'timestamp_alignment'
        WHEN s.processing_state = 'TRANSLATED' THEN 'translation_review'
        ELSE 'quality_assessment'
    END AS suggested_task_type,
    (SELECT COUNT(*) FROM annotations a 
     WHERE a.sample_id = s.sample_id AND a.status = 'completed') AS completed_annotations
FROM samples s
WHERE s.processing_state NOT IN ('REVIEWED', 'REJECTED')
ORDER BY s.priority DESC, s.created_at ASC;
```

### 7.3 v_pipeline_stats

**Purpose:** Processing statistics dashboard

```sql
CREATE VIEW v_pipeline_stats AS
SELECT 
    pipeline_type,
    processing_state,
    COUNT(*) AS sample_count,
    AVG(duration_seconds) AS avg_duration,
    AVG(cs_ratio) AS avg_cs_ratio
FROM samples
WHERE is_deleted = FALSE
GROUP BY pipeline_type, processing_state;
```

---

## 8. Functions

### 8.1 transition_sample_state

**Purpose:** State machine with automatic logging

```sql
CREATE FUNCTION transition_sample_state(
    p_sample_id UUID,
    p_new_state processing_state,
    p_executor VARCHAR(255) DEFAULT 'system'
) RETURNS BOOLEAN
```

**Usage:**
```sql
SELECT transition_sample_state(
    'uuid-here',
    'ALIGNED',
    'mfa_alignment_script'
);
```

### 8.2 add_transcript_revision

**Purpose:** Add revision with automatic version increment

```sql
CREATE FUNCTION add_transcript_revision(
    p_sample_id UUID,
    p_transcript_text TEXT,
    p_revision_type VARCHAR(50),
    p_revision_source VARCHAR(100) DEFAULT NULL,
    p_timestamps JSONB DEFAULT NULL,
    p_created_by VARCHAR(255) DEFAULT 'system'
) RETURNS UUID
```

**Usage:**
```sql
SELECT add_transcript_revision(
    'sample-uuid',
    'Corrected transcript text',
    'human_corrected',
    'annotator_123',
    NULL,
    'john_doe'
);
```

### 8.3 get_or_create_source

**Purpose:** Idempotent source creation

```sql
CREATE FUNCTION get_or_create_source(
    p_source_type source_type,
    p_external_id VARCHAR(255),
    p_name VARCHAR(500) DEFAULT NULL,
    p_url TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS UUID
```

---

## 9. Query Patterns

### 9.1 Ingestion Query

```sql
-- Insert sample with source lookup
WITH src AS (
    SELECT get_or_create_source(
        'youtube_with_transcript',
        'UCxxx',
        'Channel Name',
        'https://youtube.com/@channel',
        '{"subscriber_count": 100000}'::jsonb
    ) AS source_id
)
INSERT INTO samples (
    source_id, external_id, content_type, pipeline_type,
    audio_file_path, text_file_path, duration_seconds, cs_ratio
)
SELECT 
    src.source_id, 'video123', 'audio_primary', 'youtube_with_transcript',
    'data/raw/audio/video123.wav', 'data/raw/text/video123_transcript.json',
    300.5, 0.35
FROM src
RETURNING sample_id;
```

### 9.2 Get Processing Queue

```sql
SELECT 
    sample_id,
    external_id,
    processing_state,
    priority,
    audio_file_path,
    text_file_path
FROM samples
WHERE processing_state = 'RAW'
  AND pipeline_type = 'youtube_with_transcript'
  AND is_deleted = FALSE
ORDER BY priority DESC, created_at ASC
LIMIT 10;
```

### 9.3 Get Sample with History

```sql
SELECT 
    s.sample_id,
    s.external_id,
    s.processing_state,
    json_agg(DISTINCT jsonb_build_object(
        'version', tr.version,
        'type', tr.revision_type,
        'created_at', tr.created_at
    )) AS transcript_history,
    json_agg(DISTINCT jsonb_build_object(
        'version', tl.version,
        'type', tl.revision_type,
        'created_at', tl.created_at
    )) AS translation_history
FROM samples s
LEFT JOIN transcript_revisions tr ON s.sample_id = tr.sample_id
LEFT JOIN translation_revisions tl ON s.sample_id = tl.sample_id
WHERE s.sample_id = 'uuid-here'
GROUP BY s.sample_id;
```

---

## 10. Schema File Location

The complete schema is defined in:

```
init_scripts/02_schema_v2.sql
```

To initialize the database:

```bash
# Via Docker Compose (recommended)
docker-compose up -d postgres

# Or manually
psql -h localhost -U admin -d data_factory -f init_scripts/02_schema_v2.sql
```

# 03. Data Requirements

## Overview

This document defines the data specifications for the Vietnamese-English Code-Switching Speech Translation pipeline.

---

## 1. Audio Requirements

### Technical Format

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Container | `.wav` | Lossless, universal support |
| Sample Rate | `16000 Hz` | Standard for speech recognition |
| Channels | `1` (Mono) | Single speaker focus |
| Bit Depth | 16-bit PCM | Standard quality |

### Duration Limits

| Type | Min | Max | Rationale |
|------|-----|-----|-----------|
| Full Video | 2 min | 60 min | Processing efficiency |
| Segment | 10 sec | 30 sec | Training optimization |

### Quality Criteria

- Clear speech (minimal background noise)
- Single primary speaker (no overlapping voices)
- Code-switching content (Vietnamese + English mix)

---

## 2. Source Requirements

### YouTube Videos

**Required:**
- Video must have transcript (manual or auto-generated)
- Manual transcripts preferred over auto-generated
- Videos without transcripts are **rejected**

**Subtitle Type Detection:**

| Type | Priority | Quality |
|------|----------|---------|
| Manual | High | Usually accurate |
| Auto-generated | Low | May need correction |
| None | Rejected | Cannot process |

### Content Criteria

Look for videos with:
- `"EngSub"`, `"Vietnamese/English"` in title
- `"Reaction"`, `"Vlog"` content types
- Mixed language conversations

---

## 3. Transcript Requirements

### Format

Transcripts are stored as JSON with timestamps:

```json
{
  "video_id": "OXPQQIREOzk",
  "language": "en",
  "subtitle_type": "Manual",
  "segments": [
    {
      "text": "Xin chào everyone",
      "start": 0.47,
      "end": 1.42
    }
  ],
  "full_text": "Xin chào everyone..."
}
```

### Code-Switching Detection

The "Intersection Rule" for CS content:
- Must contain ≥1 Vietnamese particle (e.g., `và`, `là`, `của`)
- **AND** ≥1 English stop word (e.g., `the`, `and`, `is`)

---

## 4. Segment Requirements

### Target Duration

| Metric | Value |
|--------|-------|
| Target | 10-30 seconds |
| Minimum | 5 seconds |
| Maximum | 45 seconds |

### Boundary Rules

1. **Prefer sentence boundaries** - Clean cuts at sentence ends
2. **No cut words** - Never split in the middle of a word
3. **Context preservation** - Keep semantic units together

### Segment Output

Each segment produces:
- Audio file: `data/segments/{sample_id}/0000.wav`
- Database record with:
  - `transcript_text` - Segment transcript
  - `word_timestamps` - Word-level timing
  - `alignment_score` - Average confidence

---

## 5. Translation Requirements

### Target Language

- Source: Vietnamese-English code-switched text
- Target: Pure Vietnamese translation

### Translation Quality

Translations must:
- Preserve meaning accurately
- Use natural Vietnamese phrasing
- Translate English portions appropriately
- Maintain proper Vietnamese diacritics

### Storage

- Full translation stored in `translation_revisions`
- Per-segment translations in `segment_translations`

---

## 6. File Organization

### Directory Structure

```
data/
├── raw/
│   ├── audio/              # Full video audio
│   │   └── {video_id}.wav
│   ├── text/               # Raw transcripts
│   │   └── {video_id}_transcript.json
│   └── metadata.jsonl      # Ingestion metadata
├── segments/               # Segmented audio
│   └── {sample_id}/
│       ├── 0000.wav
│       ├── 0001.wav
│       └── ...
└── exports/                # Training exports
    └── {export_name}/
```

### Metadata Schema

`metadata.jsonl` format:

```json
{
  "id": "video_123",
  "type": "youtube",
  "url": "https://...",
  "duration": 340,
  "subtitle_type": "Manual",
  "cs_ratio": 0.35,
  "captured_at": "2024-11-24"
}
```

---

## 7. Quality Checklist

### Ingestion

- [ ] Audio is 16kHz mono WAV
- [ ] Duration between 2-60 minutes
- [ ] Transcript available (manual or auto-generated)
- [ ] Code-switching content detected

### Segmentation

- [ ] Segments are 10-30 seconds
- [ ] No words cut at boundaries
- [ ] Word-level timestamps present
- [ ] Alignment score > 0.7

### Translation

- [ ] Full transcript translated
- [ ] Per-segment translations aligned
- [ ] Vietnamese diacritics correct
- [ ] No untranslated English (unless proper nouns)

---

## Related Documentation

- [04_workflow.md](04_workflow.md) - Processing workflow
- [06_database_design.md](06_database_design.md) - Data schema

# 03. Data Requirements & Handover Specifications

## 1. Audio-First Requirements (YouTube/Vlogs)

*Target: Capturing real-world acoustic code-switching.*

**A. Technical Format (Crucial)**
The pipeline expects standardized audio to avoid expensive re-processing later.

  * **Container:** `.wav`
  * **Sample Rate:** `16000 Hz` (16kHz)
  * **Channels:** `1` (Mono)
  * **Duration Limit:** Keep clips between **2 and 1 hour**. (Files > 1 hour may crash the segmentation memory; files <2 min lack context).

**B. Metadata to Collect**
For every audio file, they must provide a JSON entry containing:

  * **Source URL:** (To trace lineage)
  * **Channel ID:** (To detect speaker overlap across splits)
  * **Upload Date:** (For versioning)
  * **Subtitle Track:** They **must** verify if subtitles are "Auto-generated" (ASR) or "Manual" (Human). *Warning: Do not download "Auto-translated" tracks.*

**C. Filtering Heuristic**
Do not blindly download everything. They should check video titles/descriptions for keywords like: `"EngSub"`, `"Vietnamese/English"`, `"Reaction"`, or `"Vlog"`.

-----

## 2. Text-First Requirements (Blogs/Forums)

*Target: High-quality text to generate synthetic audio later.*

**A. Content Structure**
They cannot just dump paragraphs. The data must be structured as **Sentence Trios** or a **Sliding Window**:

  * **The Core CS Sentence:** The sentence containing the code-switching.
  * **The Context:** The sentence immediately *before* and *after* it. (Translation often depends on the previous sentence).

**B. Quality Gate (The "Intersection" Rule)**
To filter out pure Vietnamese or pure English text, they should apply this check before saving:

  * Does the sentence contain at least **one Vietnamese particle** (e.g., *và, là, của, những*)?
  * **AND** at least **one English stop word** (e.g., *the, and, so, is*)?
  * *If yes -> Save it.*

-----

## 3. Delivery Format (The Handover)

To feed directly into your `ingestion` container, they should organize files like this:

**Directory Structure:**

```text
delivery_batch_01/
├── metadata.jsonl         # One JSON object per video/article
├── audio/
│   ├── {video_id}.wav     # 16kHz mono audio
│   └── ...
└── text/
    ├── {article_id}.txt   # Raw text content
    └── ...
```

**Metadata Schema (`metadata.jsonl`):**
This matches your PostgreSQL `source_metadata` JSONB column:

```json
{
  "id": "video_123",
  "type": "youtube",
  "url": "https://...",
  "duration": 340,
  "language_tags": ["vi", "en"],
  "captured_at": "2025-11-24"
}
```

### Summary Checklist for Your Friend

1.  [ ] **Audio:** 16kHz Mono `.wav`.
2.  [ ] **Length:** 2-60 minutes per file.
3.  [ ] **Text:** Must mix VN and EN words (don't scrape pure VN news).
4.  [ ] **Manifest:** Every batch of files comes with a `metadata.jsonl` file.

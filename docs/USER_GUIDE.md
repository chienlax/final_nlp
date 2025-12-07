# NLP Pipeline - User Guide

Complete user manual for the Vietnamese-English Code-Switching Speech Translation pipeline.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Web Interface Overview](#web-interface-overview)
3. [Dashboard Tab](#dashboard-tab)
4. [Review Tab](#review-tab)
5. [Upload Tab](#upload-tab)
6. [Refinement Tab](#refinement-tab)
7. [Download Tab](#download-tab)
8. [Keyboard Shortcuts](#keyboard-shortcuts)
9. [Workflow Guide](#workflow-guide)

---

## Quick Start

### Prerequisites

- Python 3.10+
- Virtual environment activated (`.venv`)
- Database initialized (`lab_data.db`)

### Launch Application

```powershell
.venv\Scripts\Activate.ps1
python src/gui_app.py
```

Access at: **http://localhost:8501**

---

## Web Interface Overview

The application uses a **tab-based single-page interface** with 5 main sections:

- **📊 Dashboard**: View statistics and overall progress
- **📝 Review**: Review and edit transcriptions
- **⬆️ Upload**: Import audio/metadata
- **🎛️ Refinement**: Audio processing tools
- **📥 Download**: Export final datasets

### Navigation

- **Left Sidebar**: Quick stats and navigation shortcuts
- **Top Tabs**: Switch between main sections
- **Bulk Edit Mode**: Toggle with switch in Review tab

---

## Dashboard Tab

**Purpose**: High-level overview of dataset progress.

### Metrics Displayed

1. **Total Videos**: Number of YouTube videos ingested
2. **Total Segments**: Audio chunks processed
3. **Total Chunks**: Individual transcription units
4. **Reviewed Segments**: Segments with approved/rejected status
5. **Long Segments**: Segments >30s requiring splitting
6. **Progress**: Percentage of reviewed segments

### Action Cards

- **🎥 Videos**: Click to view video list
- **📝 Segments**: Click to jump to review tab
- **⚠️ Long Segments**: Filter to segments needing attention

### Refresh Stats

Click **🔄 Refresh** button to update metrics (stats cached for 60s by default).

---

## Review Tab

**Purpose**: Main workspace for reviewing/editing transcriptions.

### Interface Layout

#### Video Selection

1. **Video Dropdown**: Select video by title/ID
2. **Auto-load**: First video selected by default
3. **Video Info**: Displays duration, channel, segment count

#### Chunk Selection

1. **Chunk Dropdown**: Select chunk within selected video
2. **Chunk Info**: Shows start/end timestamps, duration
3. **Segment Count**: Number of segments in chunk

### Segment Editor

Each segment displays in **compact data-grid layout**:

```
┌──────────────────────────────────────────────────────────────────┐
│ [✓] Timestamps      │ Transcript      │ Translation     │ [🔊]  │
│ 00:00-00:05        │ "Hello world"   │ "Xin chào"      │ [💾]  │
│ [Edit] [Edit]      │ [Edit mode]     │ [Edit mode]     │ [✓][✗]│
└──────────────────────────────────────────────────────────────────┘
```

#### Column Breakdown (Bulk Edit OFF)

1. **Timestamps** (12%): Start/End time display
2. **Transcript** (40%): Vietnamese/English code-switched text
3. **Translation** (40%): English translation
4. **Actions** (8%): Audio player, Save, Approve, Reject

#### Column Breakdown (Bulk Edit ON)

1. **Checkbox** (5%): Select for bulk actions
2. **Timestamps** (15%): Start/End time display
3. **Transcript** (35%): Editable text
4. **Translation** (35%): Editable text
5. **Actions** (10%): Controls

### Editing Segments

#### Individual Edit Mode

1. **Click "Edit" button** on timestamp/transcript/translation
2. **Inline editor appears**:
   - Timestamps: Time-picker widgets (HH:MM:SS)
   - Text fields: Multiline text areas
3. **Save**: Click 💾 button
4. **Cancel**: Click elsewhere or press Esc

#### Bulk Edit Mode

1. **Enable**: Toggle "Bulk Edit Mode" switch at top
2. **Select Segments**: Check boxes in first column
3. **Bulk Actions**:
   - **Approve Selected**: Mark all selected as ✅ Approved
   - **Reject Selected**: Mark all selected as ❌ Rejected
   - **Export JSON**: Download selected segments as JSON

### Review States

| Icon | State | Meaning |
|------|-------|---------|
| ⏳ | Pending | Not yet reviewed |
| ✅ | Approved | Transcription verified correct |
| ❌ | Rejected | Segment flagged for re-processing |

**State Transitions**:
- Pending → Approved: Click ✓ button
- Pending → Rejected: Click ✗ button
- Any state → Pending: Clear via database edit

### Audio Player

- **Play Button** (🔊): Plays segment audio
- **Volume Control**: Adjust in browser
- **Styled Player**: Gradient border when playing

**Audio Requirements**:
- Format: WAV, 16kHz, Mono
- Location: `data/segments/{video_id}/{chunk_id}/seg_{idx}.wav`

### Pagination

- **Page Size**: 20 segments per page (adjustable in code)
- **Navigation**: << First | < Prev | Next > | Last >>
- **Page Indicator**: Shows current page / total pages

---

## Upload Tab

**Purpose**: Import audio files and metadata JSON.

### Upload Workflow

#### Option 1: Audio Files

1. **Click "Upload Audio Files"**
2. **Select .wav files** (multiple selection supported)
3. **System processes**:
   - Validates 16kHz, Mono, WAV
   - Generates metadata
   - Creates database entries
4. **Success**: Shows uploaded count

#### Option 2: Metadata JSON

1. **Click "Upload Metadata JSON"**
2. **Select `.jsonl` or `.json` file**
3. **Format expected**:

```json
{
  "video_id": "abc123",
  "chunk_id": "chunk_0",
  "segments": [
    {
      "idx": 0,
      "start": 0.0,
      "end": 5.2,
      "transcript": "Xin chào everyone",
      "translation": "Hello everyone"
    }
  ]
}
```

4. **System imports**:
   - Creates/updates segments
   - Links to existing videos/chunks
   - Sets initial review state to Pending

### Empty State

If no chunks exist for selected video, shows:

```
┌─────────────────────────────────────────┐
│         No chunks found                  │
│                                          │
│   [Upload JSON for this Video/Chunk]    │
└─────────────────────────────────────────┘
```

---

## Refinement Tab

**Purpose**: Audio preprocessing tools.

### Available Tools

#### 1. Audio Denoising

**Function**: Remove background noise using spectral gating.

**Usage**:
1. Select video from dropdown
2. Click "Denoise Audio"
3. Output: `data/denoised/{video_id}/`

**Parameters** (configured in code):
- Noise profile: First 1s of audio
- Threshold: -20dB
- Smoothing: 0.5s

#### 2. Chunk Splitting

**Function**: Split long audio files into manageable chunks.

**Usage**:
1. Select video
2. Set chunk duration (default: 300s = 5min)
3. Click "Chunk Audio"
4. Output: `data/raw/chunks/{video_id}/chunk_{idx}.wav`

**Auto-generated**:
- `chunk_jobs.jsonl`: Processing queue
- Metadata entries in database

#### 3. Segment Extraction

**Function**: Extract individual segments from chunks.

**Usage**:
1. Select video and chunk
2. Click "Extract Segments"
3. System uses timestamps from database
4. Output: `data/segments/{video_id}/{chunk_id}/seg_{idx}.wav`

**Requirements**:
- Chunk must have transcribed segments in DB
- Timestamps must be valid (start < end < chunk_duration)

---

## Download Tab

**Purpose**: Export finalized datasets.

### Export Options

#### 1. Download All Approved Segments

**Output**: ZIP file containing:
```
approved_segments_YYYYMMDD_HHMMSS.zip
├── audio/
│   ├── seg_0000.wav
│   ├── seg_0001.wav
│   └── ...
├── metadata.json
└── manifest.csv
```

**Metadata Schema**:
```json
[
  {
    "segment_id": 1,
    "video_id": "abc123",
    "chunk_id": "chunk_0",
    "start": 0.0,
    "end": 5.2,
    "transcript": "...",
    "translation": "...",
    "duration": 5.2,
    "audio_path": "audio/seg_0000.wav"
  }
]
```

**Filters Applied**:
- review_state = 'Approved'
- Audio files exist on disk

#### 2. Download Selected Segments (JSON)

**Triggered from**: Bulk Edit Mode in Review Tab

**Output**: JSON file with selected segments:
```json
{
  "export_date": "2025-01-15T10:30:00",
  "total_segments": 5,
  "segments": [...]
}
```

---

## Keyboard Shortcuts

### Global Shortcuts

| Shortcut | Action | Context |
|----------|--------|---------|
| `Ctrl+S` | Save current segment | Review tab, editing |
| `Ctrl+Enter` | Approve segment | Review tab, segment focused |
| `Ctrl+R` | Reject segment | Review tab, segment focused |
| `Ctrl+Space` | Play audio | Review tab, segment focused |

### Navigation Shortcuts

| Shortcut | Action |
|----------|--------|
| `Tab` | Next field |
| `Shift+Tab` | Previous field |
| `Esc` | Cancel inline edit |

**Note**: Shortcuts only work when focus is on segment input fields.

---

## Workflow Guide

### End-to-End Pipeline

```mermaid
graph LR
    A[YouTube URL] --> B[Download Audio]
    B --> C[Denoise]
    C --> D[Chunk into 5min segments]
    D --> E[Transcribe with Gemini]
    E --> F[Review in GUI]
    F --> G[Export Approved]
    G --> H[Train ST Model]
```

### Step-by-Step Process

#### Phase 1: Data Collection

1. **Add YouTube URLs** to `ingest_youtube.py`
2. **Download audio**: 
   ```powershell
   python src/ingest_youtube.py --download
   ```
3. **Verify**: Check `data/raw/audio/{video_id}/`

#### Phase 2: Preprocessing

1. **Denoise** (Refinement Tab):
   - Select video
   - Click "Denoise Audio"
   - Wait for processing (~1min per 10min audio)

2. **Chunk** (Refinement Tab):
   - Select video
   - Set duration (300s recommended)
   - Click "Chunk Audio"
   - Creates chunks in `data/raw/chunks/`

3. **Transcribe** (Terminal):
   ```powershell
   python src/preprocessing/gemini_process.py --video_id abc123
   ```
   - Generates transcript + translation
   - Saves to database

#### Phase 3: Review & QA

1. **Open Review Tab**
2. **Select video and chunk**
3. **For each segment**:
   - Play audio (🔊)
   - Verify transcript matches audio
   - Check translation accuracy
   - Edit if needed (click "Edit")
   - Approve (✓) or Reject (✗)

4. **Bulk Review** (optional):
   - Enable Bulk Edit Mode
   - Select multiple segments
   - Approve/Reject in batch

#### Phase 4: Export

1. **Go to Download Tab**
2. **Click "Download All Approved Segments"**
3. **Extract ZIP file**
4. **Use in training**:
   ```python
   import json
   with open('metadata.json') as f:
       data = json.load(f)
   # Feed to model...
   ```

### Quality Control Tips

**Common Issues**:

| Issue | Solution |
|-------|----------|
| Transcript mismatched | Re-run Gemini with better prompt |
| Audio cut off | Adjust chunk boundaries |
| Translation inaccurate | Manual edit in Review tab |
| Long segment (>30s) | Split using Refinement tools |

**Review Workflow Best Practices**:
1. Review in chronological order (chunk 0 → N)
2. Listen to audio at least once per segment
3. Check code-switching points carefully
4. Verify timestamps align with audio
5. Use Reject for segments needing re-processing

---

## Troubleshooting

### Application Won't Start

**Error**: `ModuleNotFoundError: No module named 'nicegui'`

**Solution**:
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Audio Not Playing

**Causes**:
1. File doesn't exist at expected path
2. Wrong audio format (must be WAV)
3. Browser codec support issue

**Check**:
```powershell
ls data/segments/{video_id}/{chunk_id}/
```

### Database Locked

**Error**: `sqlite3.OperationalError: database is locked`

**Solution**:
1. Close all other connections to `lab_data.db`
2. Restart the application
3. If persists, check for zombie processes

### Slow Performance

**Causes**:
- Large database (>10k segments)
- Cached stats not refreshing

**Solutions**:
1. Increase pagination page size (code edit)
2. Clear browser cache
3. Restart application to clear Python cache

---

## Advanced Features

### Custom Filtering

Edit `src/gui_app.py` to add custom filters:

```python
# Example: Filter by duration
segments = [s for s in segments if s['duration'] < 10.0]
```

### Batch Processing

Use terminal for bulk operations:

```powershell
# Approve all segments for video
python -c "from src.db import approve_all_segments; approve_all_segments('video_id')"
```

### Export Custom Format

Modify `download_content()` in `gui_app.py` to change export schema.

---

## Support

For technical issues, check:
- `DEVELOPER_GUIDE.md` - Architecture & code reference
- `WORKFLOW.md` - Detailed pipeline documentation
- GitHub Issues - Report bugs

---

**Version**: 2.0  
**Last Updated**: 2025-01-15  
**Framework**: NiceGUI v1.x  
**Database**: SQLite 3

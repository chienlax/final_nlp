# NiceGUI Review Application - User Interface Guide

**Version:** 2.0 (Data-Grid Layout)  
**Last Updated:** December 7, 2025

This guide covers the revamped NiceGUI web interface for reviewing and correcting Vietnamese-English code-switched transcriptions and translations.

---

## Table of Contents

1. [Overview](#overview)
2. [Navigation](#navigation)
3. [Dashboard](#dashboard)
4. [Review Page](#review-page)
5. [Data-Grid Layout](#data-grid-layout)
6. [Bulk Edit Mode](#bulk-edit-mode)
7. [Keyboard Shortcuts](#keyboard-shortcuts)
8. [Deep Linking](#deep-linking)
9. [Upload Features](#upload-features)
10. [Advanced Features](#advanced-features)

---

## Overview

### What's New in v2.0

**✨ Major UI/UX Improvements:**

- **Data-Grid Layout**: Compact, table-like segment display (40% more segments visible per screen)
- **Persistent Left Sidebar**: Dark-mode navigation drawer with quick stats
- **Bulk Edit Mode**: Multi-select segments for batch approve/reject operations
- **Deep Linking**: Shareable URLs with video/chunk/page parameters
- **Time-Picker Inputs**: Inline timestamp editing with real-time validation
- **Enhanced Audio Player**: Dedicated player bar with gradient styling
- **Empty State Upload**: Direct JSON upload for unchunked segments
- **Multi-Page Routing**: Browser back/forward buttons now work correctly

**🔄 Migration from v1.x:**

- Tab-based SPA → Multi-page routing with URL persistence
- Card-based segments → Compact row-based grid
- Manual bulk operations → Checkbox-based multi-select
- Global header stats → Sidebar footer stats

---

## Navigation

### Left Sidebar

**Always visible** on all pages with:

- **📊 Dashboard**: Overview statistics and channel progress
- **📝 Annotations**: Video review interface (main workflow)
- **⬆️ Upload**: Manual audio + JSON upload
- **🎛️ Refinement**: Audio denoising with DeepFilterNet
- **📥 Download**: YouTube video ingestion

**Quick Stats Footer:**
- Total videos
- Total segments
- Total hours of audio

**Styling:**
- Dark slate background (`bg-slate-900`)
- Active page highlighted in blue
- Hover effects on all navigation items

---

## Dashboard

### Overview Cards

**Four gradient cards displaying:**

1. **Total Videos** (Purple → Indigo)
2. **Total Hours** (Blue → Cyan)
3. **Review Progress** (Green → Emerald)
   - Percentage and fraction (e.g., "75% - 150/200 segments")
4. **Rejected Segments** (Red → Pink)

### Videos by State

Table showing video counts grouped by processing state:
- `raw` - Downloaded, not chunked
- `chunked` - Split into 6-minute segments
- `denoised` - Noise-reduced (optional)
- `transcribed` - Processed by Gemini
- `reviewed` - Manual review complete

### Segments Needing Attention

Lists segments exceeding 25-second duration limit (up to 5 shown):
- Video title
- Actual duration
- Requires splitting via Review page

---

## Review Page

### Page Structure

1. **Keyboard Shortcuts Expansion** (collapsible)
2. **Channel Filter** + **Video Selector** (side-by-side)
3. **Video Metadata Row** (channel, reviewer, progress, state)
4. **Chunk Tabs** (one per 6-minute segment)
5. **Audio Player Bar** (enhanced styling)
6. **Filter Controls** + **Bulk Edit Mode Toggle**
7. **Data-Grid Segment List** (paginated, 25 per page)
8. **Bulk Actions Expansion** (always available)

### URL Parameters

**Deep linking support:**

```
/review?video=gBhbKX0pT_0&chunk=42&page=2
```

- `video`: Auto-select video by ID
- `chunk`: Auto-select chunk tab
- `page`: Jump to specific page

**Shareable links** allow direct access to specific segments for collaboration.

---

## Data-Grid Layout

### Grid Structure

**Header Row:**

| Column | Width | Content |
|--------|-------|---------|
| Checkbox (Bulk Mode) | 8% | Select/deselect segment |
| Timestamp | 12% | Start/end time inputs + duration + play button |
| Original | 40% | Code-switched transcript textarea |
| Translation | 40% | Vietnamese translation textarea |
| Actions | 8% | Save/Approve/Reject/Split icon buttons |

### Segment Row Features

**Visual State Indicators:**

- **Pending**: White background, transparent left border
- **Reviewed/Approved**: Light green background, green left border
- **Rejected**: Light red background, red left border
- **Hover**: Gray tint on mouse-over

**Compact Design:**

- Borderless textareas with auto-grow
- Icon-only action buttons (tooltips on hover)
- Inline timestamp editing (no modals)
- 2px margin between rows for density

**Real-Time Validation:**

- Duration label updates as timestamps change
- Red text if >25s (warning)
- Green text if ≤25s (valid)
- Invalid format shows "Invalid"

---

## Bulk Edit Mode

### Activation

Toggle **"Bulk Edit Mode"** switch in filter controls (top of segment list).

### Features When Active

1. **Checkbox Column Appears**: Left-most column in grid
2. **Select All Checkbox**: Header row checkbox toggles all visible segments
3. **Selection Counter**: Blue banner shows "🎯 X segments selected"
4. **Bulk Action Buttons**:
   - ✅ Approve Selected (green)
   - ❌ Reject Selected (red outline)
   - Clear Selection (flat)

### Workflow

```
1. Enable Bulk Edit Mode
2. Check segments to modify
3. Click bulk action button
4. Confirm in notification
5. Cache clears and UI refreshes
```

**Use Cases:**

- Approve all segments in a chunk after manual verification
- Reject multiple low-quality segments at once
- Faster than clicking approve 25 times individually

---

## Keyboard Shortcuts

### Segment-Level Shortcuts

**Works when focus is in any input field (transcript, translation, timestamp):**

| Shortcut | Action | Result |
|----------|--------|--------|
| `Ctrl+S` | Save | Save current edits without changing review state |
| `Ctrl+Enter` | Approve | Save edits + mark as approved |
| `Ctrl+R` | Reject | Mark segment as rejected (no save) |
| `Ctrl+Space` | Play Audio | Play segment in audio player with auto-pause |

### Best Practices

- **Review workflow**: Edit → `Ctrl+S` → Listen (`Ctrl+Space`) → `Ctrl+Enter` to approve
- **Fast rejection**: `Ctrl+R` for segments with bad audio/incorrect timestamps
- **Quick save**: `Ctrl+S` to save progress without committing to approval

---

## Deep Linking

### URL Structure

```
http://localhost:8501/review?video=VIDEO_ID&chunk=CHUNK_ID&page=PAGE_NUM
```

### Use Cases

**Team Collaboration:**

```powershell
# Share link to specific problematic segment
https://your-server/review?video=gBhbKX0pT_0&chunk=42&page=3

# Teammate opens directly to chunk 42, page 3
```

**Resume Work:**

```powershell
# Bookmark current position
# Browser remembers exactly where you left off
```

**Bug Reports:**

```powershell
# Include link in issue tracker
# "Segment has incorrect timestamp: http://..."
```

### Implementation

- URL updates automatically when navigating chunks/pages
- Browser back/forward buttons work correctly
- Refresh preserves current state (no data loss)

---

## Upload Features

### Chunk-Level JSON Upload

**New in v2.0**: Upload transcripts directly to specific chunks.

**When Displayed:**

- Chunk has no segments (new chunk, or segments deleted)
- Shows empty state card with inbox icon

**Format:**

```json
[
  {
    "text": "Xin chào các bạn đã quay lại với Vietcetera",
    "start": "0:00.00",
    "end": "0:03.45",
    "translation": "Xin chào các bạn đã quay lại với Vietcetera"
  },
  {
    "text": "Khách mời hôm nay là singer, songwriter Ariana Grande.",
    "start": "0:03.45",
    "end": "0:10.67",
    "translation": "Khách mời hôm nay là ca sĩ kiêm sáng tác Ariana Grande."
  }
]
```

**Validation:**

- Checks required fields: `text`, `start`, `end`, `translation`
- Validates timestamp format (`M:SS.ss` or `MM:SS.ss`)
- Ensures `end > start` for all segments
- Auto-inserts into database linked to video + chunk

**Workflow:**

```
1. Navigate to empty chunk
2. Click "📤 Upload JSON Transcript"
3. Select .json file
4. Auto-validates and uploads
5. Page refreshes with new segments
```

---

## Advanced Features

### Segment Splitting

**Purpose**: Divide long segments (>25s) into smaller chunks.

**How to Access**:

1. Click ✂️ (split) icon in segment actions
2. Opens modal dialog

**Dialog Fields**:

- **Split Time**: Timestamp to divide segment (default: midpoint)
- **First Segment**: Transcript + translation for before split
- **Second Segment**: Transcript + translation for after split

**Validation**:

- Split time must be between start and end
- Creates two new segments, deletes original
- Preserves segment_index order

**Example**:

```
Original: 0:00.00 - 0:30.00 (30s - too long!)
Split at: 0:15.00

Result:
  Segment 1: 0:00.00 - 0:15.00 (15s)
  Segment 2: 0:15.00 - 0:30.00 (15s)
```

### Bulk Actions (Standard)

**Always Available** (even without Bulk Edit Mode):

Located in expansion panel at bottom of segment list.

**Options:**

1. **✅ Approve All** (green)
   - Sets all segments in chunk to `review_state = 'approved'`
   - Use after verifying entire chunk

2. **📋 Mark Chunk Reviewed** (blue)
   - Updates chunk-level state to `reviewed`
   - Signals chunk is ready for export

3. **🔄 Reset All to Pending** (orange outline)
   - Reverts all segments to `review_state = 'pending'`
   - Use if you need to re-review

**Warning**: These affect **all** segments in the chunk, not just filtered/visible ones.

### Filter Controls

**Three checkboxes:**

- **Pending**: Show segments with no review state
- **Reviewed**: Show approved/reviewed segments
- **Rejected**: Show rejected segments (hidden by default)

**Dynamic Filtering:**

- Changes apply instantly (no "Apply" button)
- Pagination resets to page 1
- Segment count updates: "X / Y segments (Chunk Z)"

**Use Cases:**

- Hide approved segments to focus on pending
- Show only rejected segments for quality audit
- Review all states together for final check

### Audio Player Integration

**Enhanced Player Bar:**

- Gradient background (blue → indigo)
- Left border accent (blue, 4px)
- Shadow effect for prominence
- Icon + label + shortcut hint

**Features:**

- **Chunk-Relative Playback**: Calculates offsets for multi-chunk videos
- **Auto-Pause**: Stops at segment end time automatically
- **JavaScript Control**: Direct DOM manipulation for precise timing
- **Static File Serving**: `/data` route serves audio files

**Playback Workflow:**

```
1. Click play button in segment row
   OR
2. Press Ctrl+Space with focus in segment
   ↓
3. Audio jumps to segment start
4. Plays until segment end
5. Auto-pauses (removes event listener)
```

---

## Tips & Best Practices

### Efficient Review Workflow

1. **Filter smart**: Hide approved segments to reduce clutter
2. **Use bulk mode**: Select multiple similar segments for batch approval
3. **Keyboard-first**: Learn shortcuts to avoid mouse clicks
4. **Split proactively**: Don't wait for warnings - split as you encounter long pauses
5. **Save frequently**: `Ctrl+S` prevents data loss on crashes

### Quality Assurance

**Before approving:**

- ✅ Listen to full segment audio (`Ctrl+Space`)
- ✅ Verify code-switching is preserved (don't translate English words)
- ✅ Check timestamps align with speech (no gaps/overlaps)
- ✅ Ensure translation is natural Vietnamese
- ✅ Duration ≤25s (split if needed)

**Common Issues:**

| Problem | Solution |
|---------|----------|
| Gemini hallucinated text | Reject segment, re-run gemini_process.py |
| Timestamp overlap | Adjust end time of previous segment |
| Wrong language detection | Manually correct transcript |
| Translation too literal | Edit translation to be more natural |
| Music/silence transcribed | Reject segment |

### Performance Optimization

**Large datasets (>500 segments):**

- Use filters to reduce visible segments
- Pagination keeps UI responsive (25 per page)
- TTL cache prevents redundant DB queries (10-60s)
- Clear cache after edits to see updates

**Slow loading:**

- Check database file size (should be <100MB)
- Run `VACUUM` command to compact SQLite
- Verify audio files are on fast storage (SSD)

---

## Troubleshooting

### Common Issues

**1. "No segments match current filters"**

- **Cause**: All segments are in a different state than selected filters
- **Fix**: Enable "Rejected" checkbox, or toggle all filters on

**2. Audio player shows "File not found"**

- **Cause**: Audio path in database doesn't match filesystem
- **Fix**: Re-run chunk_audio.py to regenerate chunks with correct paths

**3. Keyboard shortcuts not working**

- **Cause**: Focus is outside segment input fields
- **Fix**: Click inside transcript/translation textarea, then try shortcut

**4. Bulk edit checkbox missing**

- **Cause**: Bulk Edit Mode switch is off
- **Fix**: Toggle "Bulk Edit Mode" switch in filter controls

**5. URL parameters ignored**

- **Cause**: Using old SPA version (v1.x)
- **Fix**: Update to v2.0 with multi-page routing

**6. Changes not saving**

- **Cause**: Invalid timestamp format
- **Fix**: Ensure format is `M:SS.ss` (e.g., `1:23.45`, not `1:23`)

**7. Page freezes with many segments**

- **Cause**: TTL cache not clearing properly
- **Fix**: Refresh page (`F5`) to reset cache

---

## API Reference

### URL Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `video` | string | Video ID to auto-select | `gBhbKX0pT_0` |
| `chunk` | int | Chunk ID to auto-select | `42` |
| `page` | int | Page number for pagination | `2` |

### State Management

**Global AppState:**

```python
@dataclass
class AppState:
    current_page_num: Dict[int, int]  # chunk_id -> page_num
    bulk_selected: Dict[int, bool]    # segment_id -> is_selected
    bulk_edit_mode: bool              # Bulk mode toggle state
```

**TTL Cache Functions:**

- `cached_get_videos_by_state(state)` - 30s TTL
- `cached_get_database_stats()` - 60s TTL
- `cached_get_segments(video_id, chunk_id, include_rejected)` - 10s TTL
- `cached_get_chunks_by_video(video_id)` - 30s TTL

**Cache Invalidation:**

```python
state.clear_cache()  # Clears all TTL caches
state.clear_bulk_selection()  # Resets bulk edit state
```

---

## Glossary

| Term | Definition |
|------|------------|
| **Segment** | 5-20 second audio clip with transcript and translation |
| **Chunk** | 6-minute audio segment (container for multiple segments) |
| **Code-Switching** | Mixing Vietnamese and English in same sentence |
| **Review State** | pending / approved / reviewed / rejected |
| **TTL Cache** | Time-To-Live cache (auto-expires after N seconds) |
| **Deep Linking** | URLs with parameters to navigate to specific content |
| **Bulk Edit Mode** | UI mode enabling multi-select for batch operations |
| **Data-Grid Layout** | Compact table-like row-based segment display |

---

## Changelog

### v2.0 (December 2025)

**Major Changes:**

- ✅ Migrated from tab-based SPA to multi-page routing
- ✅ Replaced card-based segments with data-grid rows
- ✅ Added bulk edit mode with multi-select checkboxes
- ✅ Implemented deep linking with URL parameters
- ✅ Enhanced audio player with gradient styling
- ✅ Added chunk-level JSON upload for empty states
- ✅ Improved timestamp inputs with inline editing
- ✅ Optimized layout density (40% more segments visible)

**Breaking Changes:**

- `create_header()` removed (replaced by navigation drawer)
- `build_spa_ui()` removed (replaced by `@ui.page` decorators)
- `render_segment_card()` deprecated (use `render_segment_row()`)

**Migration Guide:**

1. Update bookmarks: `/` → `/review`
2. Learn new keyboard shortcuts (unchanged)
3. Enable Bulk Edit Mode for batch operations
4. Use deep links for team collaboration

---

## Support

**For issues or questions:**

- Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) first
- Review [WORKFLOW.md](./WORKFLOW.md) for full pipeline guide
- Check [DEVELOPER.md](./DEVELOPER.md) for technical details

**Version:** 2.0.0  
**Updated:** 2025-12-07  
**Maintainer:** MLOps Engineering Team

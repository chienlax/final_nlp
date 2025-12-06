"""
Streamlit Review Application.

Web-based interface for reviewing and correcting transcriptions and translations.
Features:
    - Audio waveform player with segment highlighting
    - Editable segment grid (transcript, translation, timestamps)
    - Duration warning badges (>25s highlighted in red)
    - Split segment functionality
    - Approve/Reject buttons
    - File upload tab for raw audio + JSON import
    - Progress tracking per video

Usage:
    streamlit run src/review_app.py

Access:
    http://localhost:8501 (or via Tailscale tunnel)
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from db import (
    get_video,
    get_videos_by_state,
    get_segments,
    get_chunks_by_video,
    aggregate_chunk_state,
    update_chunk_state,
    update_video_channel,
    update_segment_review,
    reject_segment,
    split_segment,
    get_video_progress,
    get_long_segments,
    get_database_stats,
    insert_video,
    insert_segments,
    update_video_state,
    update_video_reviewer,
    validate_transcript_json,
    parse_transcript_json,
    init_database,
    ensure_schema_upgrades,
    DEFAULT_DB_PATH,
    get_db,
)

from ingest_youtube import run_pipeline
from utils.video_downloading_utils import fetch_playlist_metadata, ensure_js_runtime, CHUNK_QUEUE_FILE

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# DATA_ROOT = PROJECT_ROOT / "data"
DATA_ROOT = PROJECT_ROOT
AUDIO_ROOT = DATA_ROOT / "raw" / "audio"

# Segment duration thresholds (milliseconds)
WARNING_DURATION_MS = 25000  # 25 seconds - show warning
MAX_DURATION_MS = 30000  # 30 seconds - hard limit suggestion

# Page configuration
st.set_page_config(
    page_title="NLP Review Tool",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =============================================================================
# CUSTOM CSS
# =============================================================================

def apply_custom_css() -> None:
    """Apply custom CSS styling."""
    st.markdown("""
    <style>
    :root {
        --nav-bg: #0f172a;
        --nav-accent: #22c55e;
        --card-bg: #0b1221;
        --border-soft: #1f2937;
    }

    /* Navigation rail */
    .nav-rail {
        background: var(--nav-bg);
        padding: 18px 14px;
        border-radius: 14px;
        color: #e5e7eb;
        border: 1px solid #1e293b;
        height: 100%;
    }
    .nav-rail h3 { margin-top: 0; margin-bottom: 12px; }
    .nav-rail .stRadio > div { gap: 10px; }
    .nav-rail label { color: #e5e7eb !important; font-weight: 600; }
    .nav-rail .stRadio [data-baseweb="radio"] { background: #111827; border-radius: 10px; padding: 6px 8px; }
    .nav-rail .stRadio [data-baseweb="radio"]:hover { border-color: var(--nav-accent); }

    /* Cards */
    .surface-card {
        background: #0b1221;
        border: 1px solid var(--border-soft);
        border-radius: 12px;
        padding: 16px;
    }

    /* Duration badges */
    .duration-warning {
        background-color: #ff6b6b;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .duration-ok {
        background-color: #51cf66;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
    }
    
    /* Segment cards */
    .segment-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
        background-color: #fafafa;
    }
    .segment-card.rejected {
        background-color: #ffe3e3;
        border-color: #ff6b6b;
    }
    .segment-card.reviewed {
        background-color: #e6fcf5;
        border-color: #51cf66;
    }
    
    /* Stats cards */
    .stat-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    
    /* Audio player styling */
    audio {
        width: 100%;
        margin: 10px 0;
    }
    
    /* Text area styling */
    .stTextArea textarea {
        font-size: 14px;
    }
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_duration(ms: int) -> str:
    """Format milliseconds as MM:SS.sss."""
    seconds = ms / 1000
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def format_timestamp(ms: int) -> str:
    """Format milliseconds as HH:MM:SS."""
    seconds = ms // 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_audio_path(video: Dict[str, Any]) -> Optional[Path]:
    """Resolve audio file path for a video."""
    audio_path_str = video.get('denoised_audio_path') or video.get('audio_path', '')
    
    # If path starts with 'data/', it's already relative to project root
    if audio_path_str.startswith('data'):
        audio_path = PROJECT_ROOT / audio_path_str
    else:
        # Otherwise, it's relative to DATA_ROOT
        audio_path = DATA_ROOT / audio_path_str
    
    if audio_path.exists():
        return audio_path
    
    # Try absolute path
    audio_path = Path(audio_path_str)
    if audio_path.exists():
        return audio_path
    
    return None


def js_runtime_status() -> str:
    """Return JS runtime health string."""
    try:
        ensure_js_runtime()
        return "ok"
    except RuntimeError as err:
        st.warning(str(err))
        return "missing"


def request_playback(start_ms: int, end_ms: Optional[int]) -> None:
    """Store playback request with optional stop time."""
    st.session_state["play_request"] = (start_ms, end_ms)


def render_audio_player_with_jump(audio_path: Path) -> None:
    """Render audio player and honor pending jump requests with auto-pause."""
    st.audio(str(audio_path))
    play_request = st.session_state.pop("play_request", None)
    if play_request is not None:
        start_ms, end_ms = play_request
        stop_time = end_ms / 1000 if end_ms is not None else None
        components.html(
            f"""
            <script>
            const audioEl = window.parent.document.querySelector('audio');
            if (audioEl) {{
                audioEl.currentTime = {start_ms/1000:.3f};
                audioEl.play();
                {'const stopAt = ' + str(stop_time) + '; audioEl.ontimeupdate = () => { if (audioEl.currentTime >= stopAt) { audioEl.pause(); audioEl.ontimeupdate = null; } };' if stop_time else ''}
            }}
            </script>
            """,
            height=0,
        )


def inject_keyboard_shortcuts() -> None:
    """Add simple keyboard shortcuts for review flow."""
    components.html(
        """
        <script>
        document.addEventListener('keydown', (event) => {
            if (event.altKey && event.key.toLowerCase() === 'a') {
                const approve = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Approve'));
                if (approve) { approve.click(); }
            }
            if (event.altKey && event.key.toLowerCase() === 's') {
                const save = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Save'));
                if (save) { save.click(); }
            }
            if (event.altKey && event.key.toLowerCase() === 'r') {
                const reject = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Reject'));
                if (reject) { reject.click(); }
            }
        });
        </script>
        """,
        height=0,
    )


NAV_ITEMS = [
    "📊 Dashboard",
    "📝 Review Audio Transcript",
    "⬆️ Upload Data",
    "🎛️ Audio Refinement",
    "📥 Download Audios",
]


def render_navigation_column() -> str:
    """Render navigation rail with quick stats."""
    st.markdown("<div class='nav-rail'>", unsafe_allow_html=True)
    st.markdown("### 🎧 NLP Review Tool")
    page = st.radio(
        "Navigation",
        NAV_ITEMS,
        index=NAV_ITEMS.index(st.session_state.get("nav_page", NAV_ITEMS[0]))
        if st.session_state.get("nav_page") in NAV_ITEMS
        else 0,
        label_visibility="collapsed"
    )
    st.session_state["nav_page"] = page

    st.markdown("---")
    try:
        stats = get_database_stats()
        st.markdown("#### 📈 Quick Stats")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Videos", stats.get('total_videos', 0))
        with col2:
            st.metric("Hours", stats.get('total_hours', 0))

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Segments", stats.get('total_segments', 0))
        with col2:
            reviewed = stats.get('reviewed_segments', 0)
            total = stats.get('total_segments', 1)
            pct = int(100 * reviewed / total) if total > 0 else 0
            st.metric("Reviewed", f"{pct}%")

        long_count = stats.get('long_segments', 0)
        if long_count > 0:
            st.warning(f"⚠️ {long_count} segments exceed 25s")
    except Exception as e:
        st.error(f"Database error: {e}")
        st.info("Click 'Initialize Database' on Dashboard to set up.")

    st.markdown("---")
    st.caption("v2.0 - SQLite + Streamlit")
    st.markdown("</div>", unsafe_allow_html=True)
    return str(page)


# =============================================================================
# DASHBOARD PAGE
# =============================================================================

def render_dashboard() -> None:
    """Render dashboard with overview statistics."""
    st.title("📊 Dashboard")
    
    try:
        stats = get_database_stats()
    except Exception as e:
        st.error(f"Failed to load stats: {e}")
        if st.button("🔧 Initialize Database"):
            init_database()
            st.success("Database initialized!")
            st.rerun()
        return
    
    # Summary cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Videos",
            stats.get('total_videos', 0),
            help="All videos in database"
        )
    
    with col2:
        st.metric(
            "Total Hours",
            f"{stats.get('total_hours', 0):.1f}",
            help="Total audio duration"
        )
    
    with col3:
        reviewed = stats.get('reviewed_segments', 0)
        total = stats.get('total_segments', 1)
        pct = int(100 * reviewed / total) if total > 0 else 0
        st.metric(
            "Review Progress",
            f"{pct}%",
            delta=f"{reviewed}/{total} segments"
        )
    
    with col4:
        rejected = stats.get('rejected_segments', 0)
        st.metric(
            "Rejected",
            rejected,
            delta_color="inverse" if rejected > 0 else "off"
        )
    
    st.markdown("---")

    # Operational warnings
    status = js_runtime_status()
    if status == "missing":
        st.error("Install Node/Deno/Bun to avoid yt-dlp player client failures.")
    if CHUNK_QUEUE_FILE.exists():
        queued = sum(1 for _ in CHUNK_QUEUE_FILE.open("r", encoding="utf-8"))
        st.info(f"Chunking jobs queued: {queued} ({CHUNK_QUEUE_FILE}")
    
    # Videos by state
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📁 Videos by State")
        videos_by_state = stats.get('videos_by_state', {})
        
        if videos_by_state:
            for state, count in videos_by_state.items():
                icon = {
                    'pending': '⏳',
                    'transcribed': '📝',
                    'reviewed': '✅',
                    'exported': '📦',
                    'rejected': '❌'
                }.get(state, '📄')
                st.write(f"{icon} **{state}**: {count}")
        else:
            st.info("No videos yet. Upload some data!")
    
    with col2:
        st.subheader("⚠️ Segments Needing Attention")
        
        long_segments = get_long_segments()
        if long_segments:
            st.warning(f"{len(long_segments)} segments exceed 25 seconds")
            
            for seg in long_segments[:5]:
                with st.expander(
                    f"{seg['video_title'][:30]}... - Segment {seg['segment_index']}"
                ):
                    st.write(f"**Duration**: {seg['duration_seconds']:.1f}s")
                    st.write(f"**Text**: {seg['transcript'][:100]}...")
        else:
            st.success("✅ No segments exceeding 25 seconds!")


# =============================================================================
# REVIEW PAGE
# =============================================================================

def render_review_page() -> None:
    """Render chunk-focused video review page with inline editing."""
    st.title("📝 Review Videos")
    inject_keyboard_shortcuts()

    # Get all videos
    transcribed = get_videos_by_state('transcribed')
    pending = get_videos_by_state('pending')
    reviewed = get_videos_by_state('reviewed')
    all_videos = transcribed + reviewed + pending

    if not all_videos:
        st.info("No videos to review. Upload some data first!")
        return

    # Channel filter
    channel_names = sorted({v.get('channel_name') or "Unknown" for v in all_videos})
    col_sel, col_refresh = st.columns([3, 1])
    
    with col_sel:
        selected_channel = st.selectbox(
            "Filter by channel",
            options=["All channels"] + channel_names,
            key="channel_filter"
        )
    
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh"):
            st.rerun()

    # Filter videos by channel
    filtered_videos = all_videos if selected_channel == "All channels" else [
        v for v in all_videos if (v.get('channel_name') or "Unknown") == selected_channel
    ]

    # Video selector
    video_options = {
        f"[{v.get('channel_name') or 'Unknown'}] {v['title'][:50]} ({v['processing_state']})": v['video_id']
        for v in filtered_videos
    }

    selected_label = st.selectbox(
        "Select Video",
        options=list(video_options.keys()),
        key="video_selector"
    )

    selected_video_id = video_options.get(selected_label)
    if not selected_video_id:
        return

    video = get_video(selected_video_id)
    if not video:
        st.error("Video not found")
        return

    # Video header
    st.markdown("---")
    col_title, col_channel, col_progress, col_state = st.columns([3, 2, 1, 1])
    
    with col_title:
        st.subheader(video['title'])
        if video.get('url'):
            st.caption(f"🔗 {video['url']}")
    
    with col_channel:
        st.caption("Channel:")
        # Editable channel name with save button
        current_channel = video.get('channel_name') or 'Unknown'
        
        # Use form to handle inline editing
        with st.form(key=f"channel_form_{selected_video_id}"):
            new_channel_name = st.text_input(
                "Channel name",
                value=current_channel,
                label_visibility="collapsed",
                key=f"channel_input_{selected_video_id}"
            )
            
            submitted = st.form_submit_button("💾 Save", use_container_width=True)
            
            if submitted and new_channel_name != current_channel:
                try:
                    success = update_video_channel(selected_video_id, new_channel_name)
                    if success:
                        st.success(f"Updated channel to: {new_channel_name}")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("Failed to update channel name")
                except Exception as e:
                    st.error(f"Error: {e}")
    
    with col_progress:
        progress = get_video_progress(selected_video_id)
        reviewed_pct = progress.get('review_percent', 0) or 0
        st.metric("Progress", f"{reviewed_pct:.0f}%")
    
    with col_state:
        agg_state = aggregate_chunk_state(selected_video_id)
        state_display = agg_state if agg_state else video['processing_state']
        st.metric("State", state_display)

    st.markdown("---")

    # Get chunks for this video
    chunks = get_chunks_by_video(selected_video_id)
    
    if not chunks:
        st.info("No chunks found. Process this video with chunk_audio.py first.")
        return

    # Create tabs for each chunk
    tab_labels = [
        f"Chunk {c['chunk_index']} ({format_timestamp(c['start_ms'])}-{format_timestamp(c['end_ms'])}) - {c['processing_state']}"
        for c in chunks
    ]
    
    tabs = st.tabs(tab_labels)
    
    for idx, tab in enumerate(tabs):
        with tab:
            chunk = chunks[idx]
            chunk_id = chunk['chunk_id']
            chunk_index = chunk['chunk_index']
            
            # Render chunk review interface
            render_chunk_review(selected_video_id, chunk, video)


def render_chunk_review(video_id: str, chunk: Dict[str, Any], video: Dict[str, Any]) -> None:
    """
    Render chunk review interface with spacious card-based layout (mockup-inspired).
    
    Features:
    - Waveform audio player at top
    - Spacious segment cards with inline text areas
    - Millisecond-precision timestamp editors
    - Bulk actions at bottom
    
    Args:
        video_id: Video identifier.
        chunk: Chunk dictionary with chunk_id, chunk_index, audio_path, etc.
        video: Video dictionary for context.
    """
    chunk_id = chunk['chunk_id']
    chunk_index = chunk['chunk_index']
    
    # Audio player for this chunk
    audio_path_str = chunk['audio_path']
    
    # Resolve audio path (handle 'data' prefix like in get_audio_path)
    if audio_path_str.startswith('data'):
        audio_path = PROJECT_ROOT / audio_path_str
    else:
        audio_path = DATA_ROOT / audio_path_str
    
    if audio_path.exists():
        st.markdown("### 🎵 Audio Player")
        render_audio_player_with_jump(audio_path)
        st.markdown("---")
    else:
        st.warning(f"⚠️ Audio file not found: {audio_path_str}")
    
    # Get segments for this chunk
    segments = get_segments(video_id, chunk_id=chunk_id, include_rejected=True)
    
    if not segments:
        st.info(f"No segments for Chunk {chunk_index}. Process with gemini_process.py first.")
        return
    
    # Filter controls (compact row)
    st.markdown("### 📝 Review Segments")
    col_filter1, col_filter2, col_filter3, col_count = st.columns([2, 2, 2, 3])
    
    with col_filter1:
        show_pending = st.checkbox(
            "Pending", 
            value=True, 
            key=f"show_pending_chunk_{chunk_id}"
        )
    
    with col_filter2:
        show_reviewed = st.checkbox(
            "Reviewed", 
            value=True, 
            key=f"show_reviewed_chunk_{chunk_id}"
        )
    
    with col_filter3:
        show_rejected = st.checkbox(
            "Rejected", 
            value=False, 
            key=f"show_rejected_chunk_{chunk_id}"
        )
    
    # Filter segments based on checkboxes
    filtered_segments = [
        s for s in segments
        if (
            (show_pending and (s.get('review_state') is None or s.get('review_state') == 'pending')) or
            (show_reviewed and s.get('review_state') in ('reviewed', 'approved')) or
            (show_rejected and s.get('review_state') == 'rejected')
        )
    ]
    
    with col_count:
        st.markdown(f"**{len(filtered_segments)} / {len(segments)} segments** (Chunk {chunk_index})")
    
    if not filtered_segments:
        st.info("No segments match current filters.")
        return
    
    st.markdown("---")
    
    # Render each segment as a spacious card
    for seg_idx, seg in enumerate(filtered_segments):
        segment_id = seg['segment_id']
        start_ms = seg['start_ms']
        end_ms = seg['end_ms']
        transcript = seg['transcript']
        translation = seg['translation']
        review_state = seg.get('review_state', 'pending') or 'pending'
        duration_sec = (end_ms - start_ms) / 1000.0
        
        # Segment card container
        with st.container():
            # Header row: timestamp, play button, state badge
            col_header1, col_header2, col_header3 = st.columns([3, 2, 2])
            
            with col_header1:
                st.markdown(f"#### Segment {seg_idx + 1}")
            
            with col_header2:
                # Play button
                if st.button(
                    f"▶️ Play ({format_timestamp(start_ms)} - {format_timestamp(end_ms)})",
                    key=f"play_seg_{segment_id}",
                    use_container_width=True
                ):
                    request_playback(start_ms, end_ms)
            
            with col_header3:
                # State badge
                state_colors = {
                    'pending': '🟡',
                    'reviewed': '🟢',
                    'approved': '✅',
                    'rejected': '🔴'
                }
                st.markdown(
                    f"<div style='text-align: center; padding: 8px; background-color: #2d2d2d; border-radius: 6px;'>"
                    f"{state_colors.get(review_state, '⚪')} <b>{review_state.upper()}</b></div>",
                    unsafe_allow_html=True
                )
            
            # Timestamp editors (millisecond precision with step controls)
            st.markdown("**⏱️ Timestamps** (millisecond precision)")
            col_time1, col_time2, col_time3 = st.columns([3, 3, 3])
            
            with col_time1:
                new_start_ms = st.number_input(
                    "Start (ms)",
                    value=start_ms,
                    min_value=0,
                    step=1,
                    key=f"start_ms_{segment_id}",
                    help="Use arrow keys or click up/down to adjust by 1ms"
                )
            
            with col_time2:
                new_end_ms = st.number_input(
                    "End (ms)",
                    value=end_ms,
                    min_value=new_start_ms + 10,
                    step=1,
                    key=f"end_ms_{segment_id}",
                    help="Use arrow keys or click up/down to adjust by 1ms"
                )
            
            with col_time3:
                new_duration_sec = (new_end_ms - new_start_ms) / 1000.0
                if new_duration_sec > 25.0:
                    st.markdown(
                        f"<div style='padding: 12px; background-color: #4d1f1f; border-radius: 6px; text-align: center;'>"
                        f"⚠️ <b>Duration: {new_duration_sec:.2f}s</b> (Too long!)</div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<div style='padding: 12px; background-color: #1f4d1f; border-radius: 6px; text-align: center;'>"
                        f"✓ <b>Duration: {new_duration_sec:.2f}s</b></div>",
                        unsafe_allow_html=True
                    )
            
            # Transcript and Translation (large inline text areas)
            st.markdown("**📝 Transcript** (code-switched)")
            new_transcript = st.text_area(
                "Transcript",
                value=transcript,
                height=100,
                key=f"transcript_{segment_id}",
                label_visibility="collapsed"
            )
            
            st.markdown("**🌏 Translation** (Vietnamese)")
            new_translation = st.text_area(
                "Translation",
                value=translation,
                height=100,
                key=f"translation_{segment_id}",
                label_visibility="collapsed"
            )
            
            # Action buttons row
            col_action1, col_action2, col_action3, col_action4 = st.columns(4)
            
            with col_action1:
                if st.button(
                    "💾 Save Changes",
                    key=f"save_{segment_id}",
                    use_container_width=True,
                    type="secondary"
                ):
                    try:
                        with get_db() as db:
                            db.execute(
                                """
                                UPDATE segments 
                                SET transcript = ?, translation = ?, start_ms = ?, end_ms = ?
                                WHERE segment_id = ?
                                """,
                                (new_transcript, new_translation, new_start_ms, new_end_ms, segment_id)
                            )
                        st.success("✅ Saved!")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            
            with col_action2:
                if st.button(
                    "✅ Approve",
                    key=f"approve_{segment_id}",
                    use_container_width=True,
                    type="primary"
                ):
                    try:
                        with get_db() as db:
                            db.execute(
                                """
                                UPDATE segments 
                                SET transcript = ?, translation = ?, start_ms = ?, end_ms = ?, review_state = 'approved'
                                WHERE segment_id = ?
                                """,
                                (new_transcript, new_translation, new_start_ms, new_end_ms, segment_id)
                            )
                        st.success("✅ Approved!")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            
            with col_action3:
                if st.button(
                    "📝 Mark Reviewed",
                    key=f"mark_reviewed_{segment_id}",
                    use_container_width=True
                ):
                    try:
                        with get_db() as db:
                            db.execute(
                                """
                                UPDATE segments 
                                SET transcript = ?, translation = ?, start_ms = ?, end_ms = ?, review_state = 'reviewed'
                                WHERE segment_id = ?
                                """,
                                (new_transcript, new_translation, new_start_ms, new_end_ms, segment_id)
                            )
                        st.success("📝 Marked as reviewed!")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            
            with col_action4:
                if st.button(
                    "❌ Reject",
                    key=f"reject_{segment_id}",
                    use_container_width=True
                ):
                    try:
                        with get_db() as db:
                            db.execute(
                                "UPDATE segments SET review_state = 'rejected' WHERE segment_id = ?",
                                (segment_id,)
                            )
                        st.warning("❌ Rejected!")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
            
            # Separator between segments
            st.markdown("<div style='margin: 30px 0; border-top: 1px solid #333;'></div>", unsafe_allow_html=True)
    
    # Bulk actions at bottom
    st.markdown("---")
    st.markdown("### 🔧 Bulk Actions")
    st.caption(f"Apply actions to all {len(filtered_segments)} visible segments in Chunk {chunk_index}")
    
    col_bulk1, col_bulk2, col_bulk3, col_bulk4 = st.columns(4)
    
    with col_bulk1:
        if st.button(
            f"✅ Approve All ({len(filtered_segments)})",
            key=f"approve_all_chunk_{chunk_id}",
            use_container_width=True,
            type="primary"
        ):
            try:
                with get_db() as db:
                    db.execute(
                        "UPDATE segments SET review_state = 'approved' WHERE chunk_id = ?",
                        (chunk_id,)
                    )
                st.success(f"✅ Approved all segments in Chunk {chunk_index}")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
    
    with col_bulk2:
        if st.button(
            f"📝 Mark All Reviewed ({len(filtered_segments)})",
            key=f"review_all_chunk_{chunk_id}",
            use_container_width=True
        ):
            try:
                with get_db() as db:
                    db.execute(
                        "UPDATE segments SET review_state = 'reviewed' WHERE chunk_id = ?",
                        (chunk_id,)
                    )
                
                # Update chunk state
                update_chunk_state(chunk_id, 'reviewed')
                
                # Check if all chunks are reviewed to update video state
                agg_state = aggregate_chunk_state(video_id)
                update_video_state(video_id, agg_state)
                
                st.success(f"📝 Marked Chunk {chunk_index} as reviewed")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
    
    with col_bulk3:
        if st.button(
            f"⏸️ Mark All Pending ({len(filtered_segments)})",
            key=f"pending_all_chunk_{chunk_id}",
            use_container_width=True
        ):
            try:
                with get_db() as db:
                    db.execute(
                        "UPDATE segments SET review_state = 'pending' WHERE chunk_id = ?",
                        (chunk_id,)
                    )
                st.info(f"⏸️ Marked all segments as pending in Chunk {chunk_index}")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
    
    with col_bulk4:
        if st.button(
            f"❌ Reject All ({len(filtered_segments)})",
            key=f"reject_all_chunk_{chunk_id}",
            use_container_width=True
        ):
            try:
                with get_db() as db:
                    db.execute(
                        "UPDATE segments SET review_state = 'rejected' WHERE chunk_id = ?",
                        (chunk_id,)
                    )
                st.warning(f"❌ Rejected all segments in Chunk {chunk_index}")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")


def render_segment_editor(
    seg: Dict[str, Any],
    video: Dict[str, Any],
    audio_path: Optional[Path]
) -> None:
    """Render an editable segment card."""
    segment_id = seg['segment_id']
    
    # Get effective values (reviewed or original)
    start_ms = seg.get('reviewed_start_ms') or seg['start_ms']
    end_ms = seg.get('reviewed_end_ms') or seg['end_ms']
    transcript = seg.get('reviewed_transcript') or seg['transcript']
    translation = seg.get('reviewed_translation') or seg['translation']
    duration_ms = end_ms - start_ms
    
    # Segment header
    status_icon = '🔴 REJECTED' if seg['is_rejected'] else '✅ Reviewed' if seg['is_reviewed'] else '⏳ Pending'
    
    with st.expander(
        f"**#{seg['segment_index']}** | {format_timestamp(start_ms)} - {format_timestamp(end_ms)} | {status_icon}",
        expanded=not seg['is_reviewed']
    ):
        # Duration warning
        if duration_ms > WARNING_DURATION_MS:
            st.warning(f"⚠️ Segment is {duration_ms/1000:.1f}s (exceeds 25s limit). Consider splitting.")

        if audio_path:
            if st.button("▶️ Play segment", key=f"play_{segment_id}", width="stretch"):
                request_playback(start_ms, end_ms)
        
        # Timestamps
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            new_start_ms = st.number_input(
                "Start (ms)",
                value=start_ms,
                min_value=0,
                step=100,
                key=f"start_{segment_id}"
            )
        
        with col2:
            new_end_ms = st.number_input(
                "End (ms)",
                value=end_ms,
                min_value=new_start_ms + 100,
                step=100,
                key=f"end_{segment_id}"
            )
        
        with col3:
            new_duration = new_end_ms - new_start_ms
            if new_duration > WARNING_DURATION_MS:
                st.markdown(
                    f"**Duration**: <span style='color: red; font-weight: bold;'>"
                    f"{new_duration/1000:.2f}s ⚠️</span>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(f"**Duration**: {new_duration/1000:.2f}s ✓")
        
        # Transcript
        new_transcript = st.text_area(
            "Transcript (code-switched)",
            value=transcript,
            height=80,
            key=f"transcript_{segment_id}"
        )
        
        # Translation
        new_translation = st.text_area(
            "Translation (Vietnamese)",
            value=translation,
            height=80,
            key=f"translation_{segment_id}"
        )
        
        # Notes
        notes = st.text_input(
            "Notes (optional)",
            value=seg.get('reviewer_notes', '') or '',
            key=f"notes_{segment_id}"
        )
        
        # Action buttons
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("💾 Save", key=f"save_{segment_id}", width="stretch"):
                update_segment_review(
                    segment_id=segment_id,
                    reviewed_transcript=new_transcript,
                    reviewed_translation=new_translation,
                    reviewed_start_ms=new_start_ms,
                    reviewed_end_ms=new_end_ms,
                    reviewer_notes=notes if notes else None
                )
                st.success("Saved!")
                st.rerun()
        
        with col2:
            if st.button("✅ Approve", key=f"approve_{segment_id}", width="stretch"):
                update_segment_review(
                    segment_id=segment_id,
                    reviewed_transcript=new_transcript,
                    reviewed_translation=new_translation,
                    reviewed_start_ms=new_start_ms,
                    reviewed_end_ms=new_end_ms,
                    is_rejected=False,
                    reviewer_notes=notes if notes else None
                )
                st.success("Approved!")
                st.rerun()
        
        with col3:
            if st.button("❌ Reject", key=f"reject_{segment_id}", width="stretch"):
                reject_segment(segment_id, notes if notes else "Rejected by reviewer")
                st.warning("Rejected")
                st.rerun()
        
        with col4:
            # Split segment button (only if duration > 5s)
            if new_duration > 5000:
                if st.button("✂️ Split", key=f"split_{segment_id}", width="stretch"):
                    st.session_state[f'splitting_{segment_id}'] = True
        
        # Split segment form
        if st.session_state.get(f'splitting_{segment_id}', False):
            st.markdown("---")
            st.subheader("✂️ Split Segment")
            
            split_time = st.slider(
                "Split at (ms)",
                min_value=new_start_ms + 1000,
                max_value=new_end_ms - 1000,
                value=(new_start_ms + new_end_ms) // 2,
                step=100,
                key=f"split_time_{segment_id}"
            )
            
            st.caption(f"First half: {format_timestamp(new_start_ms)} - {format_timestamp(split_time)}")
            st.caption(f"Second half: {format_timestamp(split_time)} - {format_timestamp(new_end_ms)}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                transcript_first = st.text_area(
                    "First half transcript",
                    value=new_transcript[:len(new_transcript)//2],
                    key=f"split_t1_{segment_id}"
                )
                translation_first = st.text_area(
                    "First half translation",
                    value=new_translation[:len(new_translation)//2],
                    key=f"split_tr1_{segment_id}"
                )
            
            with col2:
                transcript_second = st.text_area(
                    "Second half transcript",
                    value=new_transcript[len(new_transcript)//2:],
                    key=f"split_t2_{segment_id}"
                )
                translation_second = st.text_area(
                    "Second half translation",
                    value=new_translation[len(new_translation)//2:],
                    key=f"split_tr2_{segment_id}"
                )
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("✂️ Confirm Split", key=f"confirm_split_{segment_id}"):
                    try:
                        split_segment(
                            segment_id=segment_id,
                            split_time_ms=split_time,
                            transcript_first=transcript_first,
                            transcript_second=transcript_second,
                            translation_first=translation_first,
                            translation_second=translation_second
                        )
                        st.success("Segment split successfully!")
                        del st.session_state[f'splitting_{segment_id}']
                        st.rerun()
                    except Exception as e:
                        st.error(f"Split failed: {e}")
            
            with col2:
                if st.button("Cancel", key=f"cancel_split_{segment_id}"):
                    del st.session_state[f'splitting_{segment_id}']
                    st.rerun()


# =============================================================================
# UPLOAD PAGE
# =============================================================================

def render_upload_page() -> None:
    """Render data upload page."""
    st.title("⬆️ Upload Data")
    
    tab1, tab2 = st.tabs(["📁 Upload Audio + JSON", "🔗 Import from JSON"])
    
    with tab1:
        render_audio_upload()
    
    with tab2:
        render_json_import()


def render_audio_upload() -> None:
    """Render audio file upload section."""
    st.subheader("Upload Audio File with Transcript")
    
    st.markdown("""
    Upload a raw audio file along with its transcript/translation JSON.
    The JSON should match the expected format (no duration field needed).
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        audio_file = st.file_uploader(
            "Audio File",
            type=['wav', 'mp3', 'flac', 'ogg'],
            key="upload_audio"
        )
    
    with col2:
        json_file = st.file_uploader(
            "Transcript JSON",
            type=['json'],
            key="upload_json"
        )
    
    # Metadata
    title = st.text_input("Title", placeholder="Enter video/audio title")
    
    # Validate and preview
    if json_file:
        try:
            json_content = json.loads(json_file.read().decode('utf-8'))
            json_file.seek(0)  # Reset for later use
            
            is_valid, errors = validate_transcript_json(json_content)
            
            if is_valid:
                st.success("✅ JSON is valid!")
                sentences = parse_transcript_json(json_content)
                st.write(f"Found {len(sentences)} sentences")
                
                # Preview first 3
                with st.expander("Preview sentences"):
                    for i, sent in enumerate(sentences[:3]):
                        st.write(f"**{i+1}**. [{sent['start']:.1f}s - {sent['end']:.1f}s]")
                        st.write(f"  Text: {sent['text'][:80]}...")
                        st.write(f"  Translation: {sent['translation'][:80]}...")
            else:
                st.error("❌ JSON validation failed:")
                for err in errors[:5]:
                    st.write(f"  - {err}")
                
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
    
    # Upload button
    if audio_file and json_file and title:
        if st.button("📤 Upload", width="stretch"):
            try:
                # Generate video ID
                video_id = str(uuid.uuid4())[:8]
                
                # Save audio file
                audio_dir = DATA_ROOT / "raw" / "audio"
                audio_dir.mkdir(parents=True, exist_ok=True)
                audio_path = audio_dir / f"{video_id}_{audio_file.name}"
                
                with open(audio_path, 'wb') as f:
                    f.write(audio_file.getbuffer())
                
                # Get audio duration
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(str(audio_path))
                    duration_seconds = len(audio) / 1000.0
                except Exception:
                    duration_seconds = 0.0
                
                # Parse JSON
                json_content = json.loads(json_file.read().decode('utf-8'))
                sentences = parse_transcript_json(json_content)
                
                # Insert into database
                insert_video(
                    video_id=video_id,
                    title=title,
                    duration_seconds=duration_seconds,
                    audio_path=str(audio_path.relative_to(DATA_ROOT)),
                    source_type='upload',
                    upload_metadata={
                        'original_filename': audio_file.name,
                        'uploaded_at': datetime.now().isoformat()
                    }
                )
                
                insert_segments(video_id, sentences)
                update_video_state(video_id, 'transcribed')
                
                st.success(f"✅ Uploaded successfully! Video ID: {video_id}")
                st.balloons()
                
            except Exception as e:
                st.error(f"Upload failed: {e}")
    else:
        if not audio_file:
            st.info("👆 Please upload an audio file")
        if not json_file:
            st.info("👆 Please upload a JSON transcript file")
        if not title:
            st.info("👆 Please enter a title")


def render_json_import() -> None:
    """Render JSON-only import section."""
    st.subheader("Import from JSON (Audio Already Exists)")
    
    st.markdown("""
    Import transcript data for an audio file that's already in the data folder.
    """)
    
    # List existing audio files
    audio_options: List[str] = ["-- Select audio file --"]
    if AUDIO_ROOT.exists():
        audio_files = list(AUDIO_ROOT.glob("*.wav")) + list(AUDIO_ROOT.glob("*.mp3"))
        audio_options.extend([f.name for f in audio_files])
    
    selected_audio = st.selectbox("Select existing audio file", audio_options)
    
    json_content_str = st.text_area(
        "Paste JSON content",
        height=300,
        placeholder='''[
  {"text": "...", "start": 0.0, "end": 4.2, "translation": "..."},
  {"text": "...", "start": 4.2, "end": 8.0, "translation": "..."}
]'''
    )
    
    title = st.text_input("Title", key="import_title")
    
    # Validate
    if json_content_str.strip():
        try:
            data = json.loads(json_content_str)
            is_valid, errors = validate_transcript_json(data)
            
            if is_valid:
                sentences = parse_transcript_json(data)
                st.success(f"✅ Valid JSON with {len(sentences)} sentences")
            else:
                st.error("❌ Validation errors:")
                for err in errors[:5]:
                    st.write(f"  - {err}")
                    
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
    
    if st.button("📥 Import", width="stretch"):
        if selected_audio == "-- Select audio file --" or not json_content_str.strip() or not title:
            st.warning("Please fill in all fields")
        else:
            try:
                data = json.loads(json_content_str)
                sentences = parse_transcript_json(data)
                
                video_id = str(uuid.uuid4())[:8]
                audio_path = AUDIO_ROOT / selected_audio
                
                # Get duration
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(str(audio_path))
                    duration_seconds = len(audio) / 1000.0
                except Exception:
                    duration_seconds = 0.0
                
                insert_video(
                    video_id=video_id,
                    title=title,
                    duration_seconds=duration_seconds,
                    audio_path=str(audio_path.relative_to(DATA_ROOT)),
                    source_type='upload'
                )
                
                insert_segments(video_id, sentences)
                update_video_state(video_id, 'transcribed')
                
                st.success(f"✅ Imported successfully! Video ID: {video_id}")
                
            except Exception as e:
                st.error(f"Import failed: {e}")


# =============================================================================
# AUDIO REFINEMENT PAGE (DENOISING)
# =============================================================================

def render_audio_refinement() -> None:
    """Render DeepFilterNet refinement tab."""
    st.title("🎛️ Audio Refinement")
    st.markdown("Run DeepFilterNet on ingested audio and track outputs.")

    ingested = get_videos_by_state('ingested')
    if not ingested:
        st.info("No ingested audio pending denoise.")
        return

    options = {f"{v['title'][:60]} ({v['video_id']})": v['video_id'] for v in ingested}
    selection = st.multiselect("Select audio to denoise", list(options.keys()))
    st.caption("This triggers DeepFilterNet via the denoise script; ensure the environment has deepfilternet installed.")

    if st.button("🚀 Run DeepFilterNet", type="primary", disabled=not selection, key="run_denoise"):
        st.warning("Please run `python src/preprocessing/denoise_audio.py --video-id <id>` for each selected item in a terminal. Automation hook not wired here to avoid blocking the UI.")
        st.write("Selected IDs:")
        for label in selection:
            st.code(options[label])


def render_ingest_page() -> None:
    """Render the YouTube ingestion page."""
    st.title("📥 Download Audios")
    st.markdown("Fetch and download audio from YouTube videos, playlists, or channels.")

    with st.expander("Runtime Health", expanded=False):
        status = js_runtime_status()
        if status == "ok":
            st.success("JS runtime detected ✔️")
        else:
            st.warning("Downloads will rely on extractor_args fallback; some formats may be skipped.")

    # Input section
    with st.expander("ℹ️ Instructions", expanded=False):
        st.markdown("""
        1. Paste YouTube URLs (Video, Playlist, or Channel) below.
        2. Click **Fetch Metadata** to see available videos.
        3. Filter by date or manually select videos.
        4. Click **Start Ingestion** to download audio and transcripts.
        """)

    url_input = st.text_area("YouTube URLs (one per line)", height=100, placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=...")
    
    col1, col2 = st.columns(2)
    with col1:
        fetch_btn = st.button("🔍 Fetch Metadata", width="stretch")
    
    # Session state for fetched videos
    if 'ingest_videos' not in st.session_state:
        st.session_state.ingest_videos = []
    if 'playlist_cache' not in st.session_state:
        st.session_state.playlist_cache = {}
    
    if fetch_btn and url_input:
        urls = [u.strip() for u in url_input.split('\n') if u.strip()]
        all_videos = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, url in enumerate(urls):
            status_text.text(f"Fetching metadata for: {url}...")
            if url in st.session_state.playlist_cache:
                videos = st.session_state.playlist_cache[url]
            else:
                videos = fetch_playlist_metadata(url)
                st.session_state.playlist_cache[url] = videos
            all_videos.extend(videos)
            progress_bar.progress((i + 1) / len(urls))
            
        st.session_state.ingest_videos = all_videos
        status_text.empty()
        progress_bar.empty()
        
        if not all_videos:
            st.warning("No videos found.")
        else:
            st.success(f"Found {len(all_videos)} videos.")

    # Display and Filter section
    if st.session_state.ingest_videos:
        st.divider()
        st.subheader("Select Videos to Download")
        
        # Date Filter
        min_date = datetime(2000, 1, 1).date()
        max_date = datetime.now().date()
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            start_date = st.date_input("From Date", value=None)
        with col_f2:
            end_date = st.date_input("To Date", value=None)
            
        # Filter logic
        filtered_videos = []
        for v in st.session_state.ingest_videos:
            upload_date_str = v.get('upload_date') # YYYYMMDD
            if not upload_date_str:
                filtered_videos.append(v) # Keep if no date
                continue
                
            try:
                v_date = datetime.strptime(upload_date_str, "%Y%m%d").date()
                if start_date and v_date < start_date:
                    continue
                if end_date and v_date > end_date:
                    continue
                filtered_videos.append(v)
            except ValueError:
                filtered_videos.append(v) # Keep if date parse fails

        st.write(f"Showing {len(filtered_videos)} / {len(st.session_state.ingest_videos)} videos")

        # Selection Dataframe
        import pandas as pd
        
        df_data = []
        for v in filtered_videos:
            df_data.append({
                "Select": True,
                "Title": v.get('title'),
                "Date": v.get('upload_date'),
                "Duration (s)": v.get('duration'),
                "ID": v.get('id'),
                "URL": v.get('webpage_url') or v.get('url') or f"https://youtu.be/{v.get('id')}"
            })
            
        if not df_data:
            st.warning("No videos match the filter.")
        else:
            df = pd.DataFrame(df_data)
            
            edited_df = st.data_editor(
                df,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Download?",
                        help="Select videos to download",
                        default=True,
                    ),
                    "URL": st.column_config.LinkColumn("Link"),
                },
                disabled=["Title", "Date", "Duration (s)", "ID", "URL"],
                hide_index=True,
                width="stretch"
            )
            
            selected_videos = edited_df[edited_df["Select"] == True]
            
            st.divider()
            st.subheader("Download Options")
            
            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                download_transcript = st.checkbox("Download Manual Vietnamese Transcripts", value=True, help="Only downloads if manual Vietnamese captions exist. Ignores auto-generated.")
            with col_opt2:
                dry_run = st.checkbox("Dry Run (Simulate only)", value=False)
                
            if st.button(f"🚀 Start Ingestion ({len(selected_videos)} videos)", type="primary", disabled=len(selected_videos)==0):
                
                urls_to_download = selected_videos["URL"].tolist()
                
                status_container = st.container()
                with status_container:
                    st.info("Starting ingestion pipeline...")
                    
                    try:
                        with st.spinner("Downloading and processing... check terminal for detailed logs"):
                            run_pipeline(
                                urls=urls_to_download,
                                db_path=DEFAULT_DB_PATH,
                                skip_download=False,
                                dry_run=dry_run,
                                download_transcript=download_transcript
                            )
                        st.success("Ingestion complete! Check the Dashboard or Review page.")
                        st.balloons()
                    except Exception as e:
                        st.error(f"An error occurred: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Main application entry point."""
    apply_custom_css()
    
    # Ensure database exists
    if not DEFAULT_DB_PATH.exists():
        try:
            init_database()
        except Exception as e:
            st.error(f"Failed to initialize database: {e}")
    else:
        try:
            ensure_schema_upgrades()
        except Exception as e:
            st.error(f"Schema upgrade failed: {e}")
            return
    
    nav_col, content_col = st.columns([1.05, 4.0], gap="large")

    with nav_col:
        page = render_navigation_column()

    with content_col:
        if page == "📊 Dashboard":
            render_dashboard()
        elif page == "📝 Review Audio Transcript":
            render_review_page()
        elif page == "⬆️ Upload Data":
            render_upload_page()
        elif page == "🎛️ Audio Refinement":
            render_audio_refinement()
        elif page == "📥 Download Audios":
            render_ingest_page()


if __name__ == "__main__":
    main()

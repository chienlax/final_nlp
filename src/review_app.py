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
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from db import (
    get_video,
    get_videos_by_state,
    get_segments,
    update_segment_review,
    reject_segment,
    split_segment,
    get_video_progress,
    get_long_segments,
    get_database_stats,
    insert_video,
    insert_segments,
    update_video_state,
    validate_transcript_json,
    parse_transcript_json,
    init_database,
    DEFAULT_DB_PATH,
)

from utils.video_downloading_utils import download_youtube_content
from ingest_youtube import ingest_to_database

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
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
    /* Duration warning badges */
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
    
    # Try relative to data root
    audio_path = DATA_ROOT / audio_path_str
    if audio_path.exists():
        return audio_path
    
    # Try absolute path
    audio_path = Path(audio_path_str)
    if audio_path.exists():
        return audio_path
    
    return None


# =============================================================================
# SIDEBAR
# =============================================================================

def render_sidebar() -> str:
    """Render sidebar with navigation and stats."""
    with st.sidebar:
        st.title("🎧 NLP Review Tool")
        st.markdown("---")
        
        # Navigation
        page = st.radio(
            "Navigation",
            ["📊 Dashboard", "📥 YouTube Ingest", "📝 Review Videos", "⬆️ Upload Data"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # Quick stats
        try:
            stats = get_database_stats()
            
            st.markdown("### 📈 Quick Stats")
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
            
            # Long segments warning
            long_count = stats.get('long_segments', 0)
            if long_count > 0:
                st.warning(f"⚠️ {long_count} segments exceed 25s")
                
        except Exception as e:
            st.error(f"Database error: {e}")
            st.info("Click 'Initialize Database' on Dashboard to set up.")
        
        st.markdown("---")
        st.caption("v2.0 - SQLite + Streamlit")
        
        return str(page)


# =============================================================================
# YOUTUBE DOWNLOAD PAGE
# =============================================================================
def render_ingestion_page() -> None:
    """Render YouTube Ingestion GUI."""
    st.title("📥 YouTube Ingestion")
    
    st.markdown("""
    Download videos, playlists, or channels directly from YouTube.
    Files will be saved to `data/raw/audio` and added to the database.
    """)
    
    with st.form("ingest_form"):
        # URL Input
        urls_input = st.text_area(
            "YouTube URLs (one per line)",
            placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=...",
            height=100
        )
        
        st.subheader("Download Options")
        
        col1, col2 = st.columns(2)
        with col1:
            force_m4a = st.checkbox(
                "Format: m4a (Original Audio)", 
                value=True,
                help="Download highest quality audio in m4a container. Avoids conversion loss."
            )
        
        with col2:
            get_transcript = st.checkbox(
                "Fetch Manual Vietnamese Transcript", 
                value=True,
                help="Only downloads if a manual (human-created) Vietnamese transcript exists. Ignores auto-generated subs."
            )
            
        submitted = st.form_submit_button("🚀 Start Download & Ingest")
        
    if submitted and urls_input:
        urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
        
        if not urls:
            st.warning("Please enter at least one URL.")
            return

        status_container = st.empty()
        status_container.info(f"⏳ Processing {len(urls)} URLs... check terminal for detailed progress.")
        
        try:
            # 1. Download Content
            with st.spinner("Downloading from YouTube..."):
                video_ids = download_youtube_content(
                    urls=urls,
                    download_transcript=get_transcript,
                    force_m4a=force_m4a
                )
            
            if not video_ids:
                status_container.warning("No videos were downloaded. Check the URLs or terminal logs.")
                return

            # 2. Ingest to Database
            # We need to reload the metadata file to get the new entries
            import json
            from utils.video_downloading_utils import METADATA_FILE
            
            new_entries = []
            if METADATA_FILE.exists():
                with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            if entry['id'] in video_ids:
                                new_entries.append(entry)
            
            if new_entries:
                stats = ingest_to_database(new_entries, DEFAULT_DB_PATH)
                
                status_container.success(f"""
                ✅ **Ingestion Complete!**
                - Downloaded: {len(video_ids)} videos
                - Database Inserted: {stats['inserted']}
                - Skipped/Exists: {stats['skipped']}
                """)
                st.balloons()
            else:
                status_container.error("Download finished but metadata lookup failed.")
                
        except Exception as e:
            status_container.error(f"Error during ingestion: {str(e)}")

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
    """Render video review page."""
    st.title("📝 Review Videos")
    
    # Video selection
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Get videos that need review (transcribed state)
        transcribed = get_videos_by_state('transcribed')
        pending = get_videos_by_state('pending')
        reviewed = get_videos_by_state('reviewed')
        
        all_videos = transcribed + reviewed + pending
        
        if not all_videos:
            st.info("No videos to review. Upload some data first!")
            return
        
        video_options = {
            f"{v['title'][:50]}... ({v['processing_state']})": v['video_id']
            for v in all_videos
        }
        
        selected_label = st.selectbox(
            "Select Video",
            options=list(video_options.keys()),
            key="video_selector"
        )
        
        selected_video_id = video_options.get(selected_label)
    
    with col2:
        st.write("")  # Spacing
        st.write("")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    if not selected_video_id:
        return
    
    # Load video and segments
    video = get_video(selected_video_id)
    segments = get_segments(selected_video_id, include_rejected=True)
    
    if not video:
        st.error("Video not found")
        return
    
    # Video info header
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.subheader(video['title'])
        if video.get('url'):
            st.caption(f"🔗 {video['url']}")
    
    with col2:
        progress = get_video_progress(selected_video_id)
        reviewed_pct = progress.get('review_percent', 0) or 0
        st.metric("Progress", f"{reviewed_pct:.0f}%")
    
    with col3:
        st.metric("State", video['processing_state'])
    
    # Audio player
    audio_path = get_audio_path(video)
    if audio_path:
        st.audio(str(audio_path))
    else:
        st.warning("Audio file not found")
    
    st.markdown("---")
    
    # Segments
    if not segments:
        st.info("No segments for this video. Process it with Gemini first.")
        return
    
    st.subheader(f"Segments ({len(segments)})")
    
    # Filter options
    col1, col2, col3 = st.columns(3)
    with col1:
        show_reviewed = st.checkbox("Show reviewed", value=True)
    with col2:
        show_unreviewed = st.checkbox("Show unreviewed", value=True)
    with col3:
        show_rejected = st.checkbox("Show rejected", value=False)
    
    # Filter segments
    filtered_segments = []
    for seg in segments:
        if seg['is_rejected'] and not show_rejected:
            continue
        if seg['is_reviewed'] and not seg['is_rejected'] and not show_reviewed:
            continue
        if not seg['is_reviewed'] and not show_unreviewed:
            continue
        filtered_segments.append(seg)
    
    # Render each segment
    for seg in filtered_segments:
        render_segment_editor(seg, video, audio_path)
    
    # Mark all reviewed button
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("✅ Mark Video as Reviewed", use_container_width=True):
            update_video_state(selected_video_id, 'reviewed')
            st.success("Video marked as reviewed!")
            st.rerun()
    
    with col2:
        if st.button("📦 Mark as Exported", use_container_width=True):
            update_video_state(selected_video_id, 'exported')
            st.success("Video marked as exported!")
            st.rerun()


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
            if st.button("💾 Save", key=f"save_{segment_id}", use_container_width=True):
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
            if st.button("✅ Approve", key=f"approve_{segment_id}", use_container_width=True):
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
            if st.button("❌ Reject", key=f"reject_{segment_id}", use_container_width=True):
                reject_segment(segment_id, notes if notes else "Rejected by reviewer")
                st.warning("Rejected")
                st.rerun()
        
        with col4:
            # Split segment button (only if duration > 5s)
            if new_duration > 5000:
                if st.button("✂️ Split", key=f"split_{segment_id}", use_container_width=True):
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
        if st.button("📤 Upload", use_container_width=True):
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
    
    if st.button("📥 Import", use_container_width=True):
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
    
    # Render sidebar and get page selection
    page = render_sidebar()
    
    # Render selected page
    if page == "📊 Dashboard":
        render_dashboard()
    elif page == "📥 YouTube Ingest":  # Add this check
        render_ingestion_page()
    elif page == "📝 Review Videos":
        render_review_page()
    elif page == "⬆️ Upload Data":
        render_upload_page()


if __name__ == "__main__":
    main()

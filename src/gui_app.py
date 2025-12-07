"""
NiceGUI Review Application.

Event-driven web-based interface for reviewing and correcting transcriptions
and translations. Replaces Streamlit with NiceGUI for better reactivity and
reduced lag.

Features:
    - Dashboard with real-time statistics
    - Chunk-based audio review with inline editing
    - Precise timestamp control with auto-pause
    - Bulk operations and keyboard shortcuts
    - File upload and YouTube ingestion
    - Audio denoising integration

Usage:
    python src/gui_app.py

Access:
    http://localhost:8501 (or via Tailscale tunnel)
    
Architecture:
    - Reactive state management (dataclass with property observers)
    - Event-driven UI updates (no page reloads)
    - Static file serving for audio playback
    - Async subprocess execution for long-running tasks
"""

import asyncio
import functools
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from nicegui import app, events, ui

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db import (
    DEFAULT_DB_PATH,
    aggregate_chunk_state,
    ensure_schema_upgrades,
    get_chunks_by_video,
    get_database_stats,
    get_db,
    get_long_segments,
    get_segments,
    get_video,
    get_video_progress,
    get_videos_by_state,
    init_database,
    insert_segments,
    insert_video,
    parse_transcript_json,
    reject_segment,
    split_segment,
    update_chunk_state,
    update_segment_review,
    update_video_channel,
    update_video_reviewer,
    update_video_state,
    validate_transcript_json,
)
from ingest_youtube import run_pipeline
from utils.video_downloading_utils import (
    CHUNK_QUEUE_FILE,
    ensure_js_runtime,
    fetch_playlist_metadata,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT  # Note: Not PROJECT_ROOT / "data"
AUDIO_ROOT = DATA_ROOT / "raw" / "audio"

# Segment duration thresholds (milliseconds)
WARNING_DURATION_MS = 25000  # 25 seconds - show warning
MAX_DURATION_MS = 30000  # 30 seconds - hard limit suggestion

# Pagination settings
SEGMENTS_PER_PAGE = 25

# Serve audio files statically (critical for audio player)
app.add_static_files('/data', str(DATA_ROOT))

# Dark theme styling
ui.colors(primary='#22c55e')


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def format_duration(ms: int) -> str:
    """Format milliseconds as MM:SS.ss."""
    seconds = ms / 1000
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def format_timestamp(ms: int) -> str:
    """Format milliseconds as HH:MM:SS or MM:SS."""
    seconds = ms // 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def ms_to_min_sec_ms(ms: int) -> str:
    """Convert milliseconds to min:sec.ms format (e.g., 83450 -> '1:23.45')."""
    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:05.2f}"


def min_sec_ms_to_ms(time_str: str) -> int:
    """Convert min:sec.ms format to milliseconds (e.g., '1:23.45' -> 83450)."""
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError(f"Invalid format: {time_str}")
        minutes = int(parts[0])
        seconds = float(parts[1])
        return int((minutes * 60 + seconds) * 1000)
    except Exception as e:
        logger.error(f"Invalid timestamp format '{time_str}': {e}")
        return 0


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


def get_static_audio_url(audio_path: Path) -> str:
    """Convert absolute audio path to static URL for audio player."""
    # Convert to relative path from DATA_ROOT
    try:
        relative = audio_path.relative_to(DATA_ROOT)
        return f"/data/{relative.as_posix()}"
    except ValueError:
        # If not relative to DATA_ROOT, try PROJECT_ROOT
        try:
            relative = audio_path.relative_to(PROJECT_ROOT)
            # Remove 'data/' prefix if present (since we serve from DATA_ROOT = PROJECT_ROOT)
            parts = relative.parts
            if parts[0] == 'data':
                relative = Path(*parts[1:])
            return f"/data/{relative.as_posix()}"
        except ValueError:
            logger.error(f"Cannot create static URL for {audio_path}")
            return ""


def js_runtime_status() -> str:
    """Return JS runtime health string."""
    try:
        ensure_js_runtime()
        return "ok"
    except RuntimeError:
        return "missing"


# =============================================================================
# CACHING LAYER (functools.lru_cache with TTL)
# =============================================================================

def ttl_cache(seconds: int, maxsize: int = 128) -> Callable:
    """
    Decorator for caching with TTL (Time To Live).
    
    Args:
        seconds: Cache TTL in seconds
        maxsize: Max cache size (LRU eviction)
    """
    def decorator(func: Callable) -> Callable:
        func = functools.lru_cache(maxsize=maxsize)(func)
        func.lifetime = seconds
        func.expiration = time.time() + seconds
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if time.time() > func.expiration:
                func.cache_clear()
                func.expiration = time.time() + func.lifetime
            return func(*args, **kwargs)
        
        wrapper.cache_clear = func.cache_clear
        return wrapper
    return decorator


@ttl_cache(seconds=30)
def cached_get_videos_by_state(state: str) -> List[Dict[str, Any]]:
    """Cached wrapper for get_videos_by_state with 30s TTL."""
    return get_videos_by_state(state)


@ttl_cache(seconds=60)
def cached_get_database_stats() -> Dict[str, Any]:
    """Cached wrapper for get_database_stats with 60s TTL."""
    return get_database_stats()


@ttl_cache(seconds=10)
def cached_get_segments(
    video_id: str,
    chunk_id: Optional[int] = None,
    include_rejected: bool = False
) -> List[Dict[str, Any]]:
    """Cached wrapper for get_segments with 10s TTL."""
    return get_segments(video_id, chunk_id=chunk_id, include_rejected=include_rejected)


@ttl_cache(seconds=30)
def cached_get_chunks_by_video(video_id: str) -> List[Dict[str, Any]]:
    """Cached wrapper for get_chunks_by_video with 30s TTL."""
    return get_chunks_by_video(video_id)


# =============================================================================
# STATE MANAGEMENT (Reactive Dataclass)
# =============================================================================

@dataclass
class AppState:
    """
    Global application state with reactive properties.
    
    Each property setter can trigger UI updates if needed.
    """
    # Navigation
    current_page: str = "dashboard"
    
    # Review page state
    selected_video_id: Optional[str] = None
    selected_chunk_id: Optional[int] = None
    current_page_num: Dict[int, int] = field(default_factory=dict)  # chunk_id -> page_num
    
    # Filters
    show_pending: bool = True
    show_reviewed: bool = True
    show_rejected: bool = False
    selected_channel: str = "All channels"
    
    # Audio playback
    audio_player_id: Optional[str] = None  # ID of audio element
    pending_playback: Optional[Tuple[int, int]] = None  # (start_ms, end_ms)
    
    # Upload state
    ingest_videos: List[Dict[str, Any]] = field(default_factory=list)
    playlist_cache: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    def clear_cache(self):
        """Clear all cached data (forces DB refresh)."""
        cached_get_videos_by_state.cache_clear()
        cached_get_database_stats.cache_clear()
        cached_get_segments.cache_clear()
        cached_get_chunks_by_video.cache_clear()


# Global state instance
state = AppState()


# =============================================================================
# AUDIO PLAYER COMPONENT
# =============================================================================

class AudioPlayer:
    """
    Custom audio player with precise timestamp control.
    
    Features:
    - Jump to specific timestamp
    - Auto-pause at end time
    - Chunk-relative offset calculation
    """
    
    def __init__(self, audio_url: str, chunk_start_ms: int = 0):
        """
        Initialize audio player.
        
        Args:
            audio_url: Static URL to audio file (e.g., /data/raw/audio/...)
            chunk_start_ms: Start time of this chunk in original video (for offset calc)
        """
        self.audio_url = audio_url
        self.chunk_start_ms = chunk_start_ms
        self.audio_element = None
        self.player_id = f"audio_{id(self)}"
        
    def render(self):
        """Render audio player with controls."""
        with ui.card().classes('w-full p-4'):
            ui.label('🎵 Audio Player').classes('text-lg font-bold mb-2')
            
            # HTML5 audio element
            self.audio_element = ui.html(f'''
                <audio id="{self.player_id}" controls preload="metadata" style="width: 100%;">
                    <source src="{self.audio_url}" type="audio/wav">
                    Your browser does not support the audio element.
                </audio>
            ''')
            
    def play_segment(self, start_ms: int, end_ms: int):
        """
        Play audio from start to end with auto-pause.
        
        Args:
            start_ms: Absolute start time in milliseconds
            end_ms: Absolute end time in milliseconds
        """
        # Calculate chunk-relative offsets
        relative_start_ms = max(0, start_ms - self.chunk_start_ms)
        relative_end_ms = end_ms - self.chunk_start_ms
        
        relative_start_sec = relative_start_ms / 1000
        relative_end_sec = relative_end_ms / 1000
        
        # JavaScript to control playback
        ui.run_javascript(f'''
            const audio = document.getElementById("{self.player_id}");
            if (audio) {{
                audio.currentTime = {relative_start_sec};
                audio.play();
                
                // Auto-pause at end time
                const checkTime = () => {{
                    if (audio.currentTime >= {relative_end_sec}) {{
                        audio.pause();
                        audio.removeEventListener('timeupdate', checkTime);
                    }}
                }};
                audio.addEventListener('timeupdate', checkTime);
            }}
        ''')


# =============================================================================
# NAVIGATION & LAYOUT
# =============================================================================

def create_header():
    """Create persistent header bar."""
    with ui.header().classes('bg-slate-900 text-white items-center'):
        ui.label('🎧 Code-Switch Review Tool').classes('text-xl font-bold')
        ui.space()
        
        # Quick stats
        try:
            stats = cached_get_database_stats()
            videos = stats.get('total_videos', 0)
            segments = stats.get('total_segments', 0)
            ui.label(f"Videos: {videos} | Segments: {segments}").classes('text-sm opacity-75')
        except Exception:
            pass


def create_navigation():
    """Create left navigation drawer."""
    with ui.left_drawer(fixed=False, bordered=True).classes('bg-slate-50'):
        ui.label('Navigation').classes('text-xs font-bold text-gray-500 mb-4 mt-4 px-4')
        
        # Navigation links
        nav_items = [
            ('/', '📊 Dashboard'),
            ('/review', '📝 Review Audio Transcript'),
            ('/upload', '⬆️ Upload Data'),
            ('/refinement', '🎛️ Audio Refinement'),
            ('/download', '📥 Download Audios'),
        ]
        
        for path, label in nav_items:
            ui.link(label, path).classes('block px-4 py-2 rounded hover:bg-slate-200 mb-1')
        
        ui.separator().classes('my-4')
        
        # Quick stats section
        ui.label('Quick Stats').classes('text-xs font-bold text-gray-500 mb-2 px-4')
        stats_container = ui.column().classes('px-4')
        
        def update_stats():
            """Update stats display."""
            stats_container.clear()
            with stats_container:
                try:
                    stats = cached_get_database_stats()
                    ui.label(f"Videos: {stats.get('total_videos', 0)}").classes('text-sm')
                    ui.label(f"Segments: {stats.get('total_segments', 0)}").classes('text-sm')
                    
                    reviewed = stats.get('reviewed_segments', 0)
                    total = stats.get('total_segments', 1)
                    pct = int(100 * reviewed / total) if total > 0 else 0
                    ui.label(f"Progress: {pct}%").classes('text-sm')
                    
                    long_count = stats.get('long_segments', 0)
                    if long_count > 0:
                        ui.label(f"⚠️ Long segments: {long_count}").classes('text-sm text-orange-600')
                except Exception as e:
                    ui.label(f"Error: {e}").classes('text-sm text-red-600')
        
        update_stats()
        
        ui.separator().classes('my-4')
        ui.label('v2.0 - NiceGUI').classes('text-xs text-gray-400 px-4')


# =============================================================================
# DASHBOARD PAGE
# =============================================================================

@ui.page('/')
def dashboard_page():
    """Dashboard with overview statistics."""
    create_header()
    create_navigation()
    
    with ui.column().classes('w-full p-8'):
        ui.label('📊 Dashboard').classes('text-3xl font-bold mb-6')
        
        try:
            stats = cached_get_database_stats()
        except Exception as e:
            ui.label(f"Failed to load stats: {e}").classes('text-red-600')
            if ui.button('🔧 Initialize Database'):
                try:
                    init_database()
                    ensure_schema_upgrades()
                    ui.notify('Database initialized successfully!', type='positive')
                    state.clear_cache()
                    ui.navigate.reload()
                except Exception as init_err:
                    ui.notify(f'Error: {init_err}', type='negative')
            return
        
        # Summary cards
        with ui.row().classes('w-full gap-4 mb-8'):
            with ui.card().classes('flex-1 p-6 bg-gradient-to-br from-purple-500 to-indigo-600 text-white'):
                ui.label('Total Videos').classes('text-sm opacity-75')
                ui.label(str(stats.get('total_videos', 0))).classes('text-4xl font-bold')
            
            with ui.card().classes('flex-1 p-6 bg-gradient-to-br from-blue-500 to-cyan-600 text-white'):
                ui.label('Total Hours').classes('text-sm opacity-75')
                ui.label(f"{stats.get('total_hours', 0):.1f}").classes('text-4xl font-bold')
            
            with ui.card().classes('flex-1 p-6 bg-gradient-to-br from-green-500 to-emerald-600 text-white'):
                reviewed = stats.get('reviewed_segments', 0)
                total = stats.get('total_segments', 1)
                pct = int(100 * reviewed / total) if total > 0 else 0
                ui.label('Review Progress').classes('text-sm opacity-75')
                ui.label(f"{pct}%").classes('text-4xl font-bold')
                ui.label(f"{reviewed}/{total} segments").classes('text-sm opacity-75')
            
            with ui.card().classes('flex-1 p-6 bg-gradient-to-br from-red-500 to-pink-600 text-white'):
                rejected = stats.get('rejected_segments', 0)
                ui.label('Rejected').classes('text-sm opacity-75')
                ui.label(str(rejected)).classes('text-4xl font-bold')
        
        ui.separator().classes('my-6')
        
        # Operational warnings
        status = js_runtime_status()
        if status == "missing":
            ui.label('⚠️ Install Node/Deno/Bun to avoid yt-dlp player client failures.').classes('text-orange-600 mb-4')
        
        if CHUNK_QUEUE_FILE.exists():
            queued = sum(1 for _ in CHUNK_QUEUE_FILE.open("r", encoding="utf-8"))
            ui.label(f"ℹ️ Chunking jobs queued: {queued} ({CHUNK_QUEUE_FILE})").classes('text-blue-600 mb-4')
        
        # Videos by state & Long segments
        with ui.row().classes('w-full gap-6'):
            # Left column: Videos by state
            with ui.card().classes('flex-1 p-6'):
                ui.label('📁 Videos by State').classes('text-xl font-bold mb-4')
                videos_by_state = stats.get('videos_by_state', {})
                
                if videos_by_state:
                    for state_name, count in sorted(videos_by_state.items()):
                        with ui.row().classes('justify-between mb-2'):
                            ui.label(state_name.capitalize()).classes('font-semibold')
                            ui.badge(str(count), color='primary')
                else:
                    ui.label('No videos in database').classes('text-gray-500')
            
            # Right column: Long segments
            with ui.card().classes('flex-1 p-6'):
                ui.label('⚠️ Segments Needing Attention').classes('text-xl font-bold mb-4')
                
                long_segments = get_long_segments()
                if long_segments:
                    ui.label(f"{len(long_segments)} segments exceed 25s duration").classes('text-orange-600 mb-2')
                    for seg in long_segments[:5]:  # Show first 5
                        duration = (seg['end_ms'] - seg['start_ms']) / 1000
                        ui.label(f"• {seg['video_title']}: {duration:.1f}s").classes('text-sm text-gray-700')
                else:
                    ui.label('✓ All segments within duration limits').classes('text-green-600')


# =============================================================================
# REVIEW PAGE
# =============================================================================

@ui.page('/review')
def review_page():
    """Chunk-focused video review page with inline editing."""
    create_header()
    create_navigation()
    
    with ui.column().classes('w-full p-8'):
        ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6')
        
        # Get all videos
        transcribed = cached_get_videos_by_state('transcribed')
        pending = cached_get_videos_by_state('pending')
        reviewed = cached_get_videos_by_state('reviewed')
        all_videos = transcribed + reviewed + pending
        
        if not all_videos:
            ui.label('No videos to review. Upload some data first!').classes('text-gray-600')
            return
        
        # Channel filter
        channel_names = sorted({v.get('channel_name') or "Unknown" for v in all_videos})
        
        with ui.row().classes('w-full gap-4 mb-4'):
            channel_select = ui.select(
                label='Filter by channel',
                options=["All channels"] + channel_names,
                value="All channels"
            ).classes('flex-1')
            
            def refresh():
                state.clear_cache()
                ui.navigate.reload()
            
            ui.button('🔄 Refresh', on_click=refresh).props('outline')
        
        # Filter videos by channel
        def get_filtered_videos():
            if channel_select.value == "All channels":
                return all_videos
            return [v for v in all_videos if (v.get('channel_name') or "Unknown") == channel_select.value]
        
        # Video selector
        video_container = ui.column().classes('w-full')
        
        def render_video_selector():
            video_container.clear()
            with video_container:
                filtered_videos = get_filtered_videos()
                
                video_options = {
                    f"[{v.get('channel_name') or 'Unknown'}] {v['title'][:50]} ({v['processing_state']})": v['video_id']
                    for v in filtered_videos
                }
                
                if not video_options:
                    ui.label('No videos match the selected filter').classes('text-gray-600')
                    return
                
                selected_video_select = ui.select(
                    label='Select Video',
                    options=list(video_options.keys()),
                    value=list(video_options.keys())[0] if video_options else None
                ).classes('w-full')
                
                # Video details container
                video_details_container = ui.column().classes('w-full mt-6')
                
                def render_video_details():
                    video_details_container.clear()
                    
                    if not selected_video_select.value:
                        return
                    
                    video_id = video_options[selected_video_select.value]
                    video = get_video(video_id)
                    
                    if not video:
                        with video_details_container:
                            ui.label('Video not found').classes('text-red-600')
                        return
                    
                    with video_details_container:
                        ui.separator().classes('mb-4')
                        
                        # Video header
                        with ui.row().classes('w-full gap-4 items-start mb-6'):
                            # Title and URL
                            with ui.column().classes('flex-1'):
                                ui.label(video['title']).classes('text-2xl font-bold')
                                if video.get('url'):
                                    ui.link(video['url'], video['url'], new_tab=True).classes('text-sm text-blue-600')
                            
                            # Channel (editable)
                            with ui.column().classes('w-48'):
                                ui.label('Channel:').classes('text-xs text-gray-500')
                                channel_input = ui.input(value=video.get('channel_name') or 'Unknown').classes('w-full')
                                
                                def save_channel():
                                    update_video_channel(video_id, channel_input.value)
                                    ui.notify('Channel updated!', type='positive')
                                    state.clear_cache()
                                
                                ui.button('Save', on_click=save_channel).props('dense flat')
                            
                            # Reviewer (editable)
                            with ui.column().classes('w-48'):
                                ui.label('Reviewer:').classes('text-xs text-gray-500')
                                
                                # Get existing reviewers
                                with get_db() as db:
                                    reviewers_raw = db.execute(
                                        "SELECT DISTINCT reviewer FROM videos WHERE reviewer IS NOT NULL AND reviewer != '' ORDER BY reviewer"
                                    ).fetchall()
                                    reviewers = [r['reviewer'] for r in reviewers_raw]
                                
                                current_reviewer = video.get('reviewer') or ''
                                if current_reviewer and current_reviewer not in reviewers:
                                    reviewers.append(current_reviewer)
                                
                                reviewer_options = [''] + sorted(reviewers) + ['+ Add new...']
                                reviewer_select = ui.select(
                                    options=reviewer_options,
                                    value=current_reviewer if current_reviewer in reviewer_options else ''
                                ).classes('w-full')
                                
                                def save_reviewer():
                                    value = reviewer_select.value
                                    if value == '+ Add new...':
                                        # Show dialog for new reviewer
                                        with ui.dialog() as dialog, ui.card():
                                            ui.label('Enter new reviewer name:')
                                            new_reviewer_input = ui.input().classes('w-full')
                                            with ui.row():
                                                ui.button('Cancel', on_click=dialog.close).props('flat')
                                                def confirm_new_reviewer():
                                                    if new_reviewer_input.value:
                                                        update_video_reviewer(video_id, new_reviewer_input.value)
                                                        ui.notify('Reviewer updated!', type='positive')
                                                        state.clear_cache()
                                                        dialog.close()
                                                        render_video_details()
                                                ui.button('Save', on_click=confirm_new_reviewer).props('color=primary')
                                        dialog.open()
                                    else:
                                        update_video_reviewer(video_id, value)
                                        ui.notify('Reviewer updated!', type='positive')
                                        state.clear_cache()
                                
                                ui.button('Save', on_click=save_reviewer).props('dense flat')
                            
                            # Progress
                            with ui.column().classes('w-24'):
                                ui.label('Progress:').classes('text-xs text-gray-500')
                                progress = get_video_progress(video_id)
                                reviewed_pct = progress.get('review_percent', 0) or 0
                                ui.label(f"{reviewed_pct:.0f}%").classes('text-2xl font-bold text-green-600')
                            
                            # State
                            with ui.column().classes('w-32'):
                                ui.label('State:').classes('text-xs text-gray-500')
                                agg_state = aggregate_chunk_state(video_id)
                                state_display = agg_state if agg_state else video['processing_state']
                                ui.badge(state_display, color='primary').classes('text-sm')
                        
                        ui.separator().classes('mb-4')
                        
                        # Get chunks for this video
                        chunks = cached_get_chunks_by_video(video_id)
                        
                        if not chunks:
                            ui.label('No chunks found. Process this video with chunk_audio.py first.').classes('text-gray-600')
                            return
                        
                        # Create tabs for each chunk
                        with ui.tabs().classes('w-full') as tabs:
                            for c in chunks:
                                chunk_label = f"Chunk {c['chunk_index']} ({format_timestamp(c['start_ms'])}-{format_timestamp(c['end_ms'])}) - {c['processing_state']}"
                                ui.tab(chunk_label, name=str(c['chunk_id']))
                        
                        with ui.tab_panels(tabs, value=str(chunks[0]['chunk_id'])).classes('w-full'):
                            for c in chunks:
                                with ui.tab_panel(str(c['chunk_id'])):
                                    render_chunk_review(video_id, c, video)
                
                selected_video_select.on_value_change(lambda: render_video_details())
                render_video_details()
        
        channel_select.on_value_change(lambda: render_video_selector())
        render_video_selector()


def render_chunk_review(video_id: str, chunk: Dict[str, Any], video: Dict[str, Any]):
    """
    Render chunk review interface.
    
    Args:
        video_id: Video identifier
        chunk: Chunk dictionary
        video: Video dictionary
    """
    chunk_id = chunk['chunk_id']
    chunk_index = chunk['chunk_index']
    
    # Audio player for this chunk
    audio_path_str = chunk['audio_path']
    
    # Resolve audio path
    if audio_path_str.startswith('data'):
        audio_path = PROJECT_ROOT / audio_path_str
    else:
        audio_path = DATA_ROOT / audio_path_str
    
    chunk_start_ms = chunk.get('start_ms', 0)
    
    if audio_path.exists():
        audio_url = get_static_audio_url(audio_path)
        player = AudioPlayer(audio_url, chunk_start_ms)
        player.render()
        ui.separator().classes('my-4')
    else:
        ui.label(f"⚠️ Audio file not found: {audio_path_str}").classes('text-orange-600 mb-4')
        player = None
    
    # Get segments for this chunk
    segments = cached_get_segments(video_id, chunk_id=chunk_id, include_rejected=True)
    
    if not segments:
        ui.label(f"No segments for Chunk {chunk_index}. Process with gemini_process.py first.").classes('text-gray-600')
        return
    
    # Filter controls
    ui.label('📝 Review Segments').classes('text-2xl font-bold mb-4')
    
    filter_container = ui.row().classes('w-full gap-4 mb-4')
    
    show_pending_check = ui.checkbox('Pending', value=True).classes('')
    show_reviewed_check = ui.checkbox('Reviewed', value=True).classes('')
    show_rejected_check = ui.checkbox('Rejected', value=False).classes('')
    
    filter_container.add(show_pending_check)
    filter_container.add(show_reviewed_check)
    filter_container.add(show_rejected_check)
    
    # Segment count
    segment_count_label = ui.label('').classes('ml-auto font-bold')
    filter_container.add(segment_count_label)
    
    # Segments container
    segments_container = ui.column().classes('w-full gap-4 mt-4')
    
    # Pagination state
    if chunk_id not in state.current_page_num:
        state.current_page_num[chunk_id] = 1
    
    def render_segments():
        segments_container.clear()
        
        # Filter segments
        filtered_segments = [
            s for s in segments
            if (
                (show_pending_check.value and (s.get('review_state') is None or s.get('review_state') == 'pending')) or
                (show_reviewed_check.value and s.get('review_state') in ('reviewed', 'approved')) or
                (show_rejected_check.value and s.get('review_state') == 'rejected')
            )
        ]
        
        segment_count_label.set_text(f"{len(filtered_segments)} / {len(segments)} segments (Chunk {chunk_index})")
        
        if not filtered_segments:
            with segments_container:
                ui.label('No segments match current filters').classes('text-gray-600')
            return
        
        # Pagination
        total_segments = len(filtered_segments)
        total_pages = (total_segments + SEGMENTS_PER_PAGE - 1) // SEGMENTS_PER_PAGE if total_segments > 0 else 1
        current_page = state.current_page_num[chunk_id]
        
        # Calculate pagination range
        if total_segments > SEGMENTS_PER_PAGE:
            start_idx = (current_page - 1) * SEGMENTS_PER_PAGE
            end_idx = min(start_idx + SEGMENTS_PER_PAGE, total_segments)
            paginated_segments = filtered_segments[start_idx:end_idx]
        else:
            paginated_segments = filtered_segments
            start_idx = 0
            end_idx = total_segments
        
        with segments_container:
            # Top pagination
            if total_segments > SEGMENTS_PER_PAGE:
                with ui.row().classes('w-full justify-center gap-4 mb-4'):
                    def go_prev():
                        if state.current_page_num[chunk_id] > 1:
                            state.current_page_num[chunk_id] -= 1
                            render_segments()
                    
                    def go_next():
                        if state.current_page_num[chunk_id] < total_pages:
                            state.current_page_num[chunk_id] += 1
                            render_segments()
                    
                    ui.button('← Previous', on_click=go_prev).props('outline').set_enabled(current_page > 1)
                    ui.label(f'Page {current_page} of {total_pages}').classes('self-center')
                    ui.button('Next →', on_click=go_next).props('outline').set_enabled(current_page < total_pages)
            
            # Render segments
            for seg in paginated_segments:
                render_segment_card(seg, video, player, chunk_start_ms, lambda: render_segments())
            
            # Bottom pagination
            if total_segments > SEGMENTS_PER_PAGE:
                with ui.row().classes('w-full justify-center gap-4 mt-4'):
                    ui.button('← Previous', on_click=go_prev).props('outline').set_enabled(current_page > 1)
                    ui.label(f'Page {current_page} of {total_pages}').classes('self-center')
                    ui.button('Next →', on_click=go_next).props('outline').set_enabled(current_page < total_pages)
            
            # Bulk actions
            ui.separator().classes('my-6')
            with ui.expansion(f'🔧 Bulk Actions ({len(filtered_segments)} segments in Chunk {chunk_index})', icon='settings').classes('w-full'):
                ui.label('Apply actions to all visible segments in this chunk').classes('text-sm text-gray-600 mb-4')
                
                with ui.row().classes('gap-4'):
                    def bulk_approve():
                        with get_db() as db:
                            db.execute(
                                "UPDATE segments SET review_state = 'approved' WHERE chunk_id = ?",
                                (chunk_id,)
                            )
                        ui.notify(f'Approved {len(filtered_segments)} segments!', type='positive')
                        state.clear_cache()
                        render_segments()
                    
                    def bulk_review():
                        update_chunk_state(chunk_id, 'reviewed')
                        ui.notify('Chunk marked as reviewed!', type='positive')
                        state.clear_cache()
                        render_segments()
                    
                    def bulk_reset():
                        with get_db() as db:
                            db.execute(
                                "UPDATE segments SET review_state = 'pending' WHERE chunk_id = ?",
                                (chunk_id,)
                            )
                        ui.notify('Reset all segments to pending!', type='info')
                        state.clear_cache()
                        render_segments()
                    
                    ui.button('✅ Approve All', on_click=bulk_approve).props('color=green')
                    ui.button('📋 Mark Chunk Reviewed', on_click=bulk_review).props('color=blue')
                    ui.button('🔄 Reset All to Pending', on_click=bulk_reset).props('color=orange outline')
    
    show_pending_check.on_value_change(lambda: render_segments())
    show_reviewed_check.on_value_change(lambda: render_segments())
    show_rejected_check.on_value_change(lambda: render_segments())
    
    render_segments()


def render_segment_card(
    seg: Dict[str, Any],
    video: Dict[str, Any],
    player: Optional[AudioPlayer],
    chunk_start_ms: int,
    refresh_callback: Callable
):
    """
    Render an editable segment card.
    
    Args:
        seg: Segment dictionary
        video: Video dictionary
        player: AudioPlayer instance (if available)
        chunk_start_ms: Chunk start time for offset calculation
        refresh_callback: Function to call after updates
    """
    segment_id = seg['segment_id']
    
    # Get effective values (reviewed or original)
    start_ms = seg.get('reviewed_start_ms') or seg['start_ms']
    end_ms = seg.get('reviewed_end_ms') or seg['end_ms']
    transcript = seg.get('reviewed_transcript') or seg['transcript']
    translation = seg.get('reviewed_translation') or seg['translation']
    duration_ms = end_ms - start_ms
    review_state = seg.get('review_state', 'pending') or 'pending'
    
    # Status icon
    if seg.get('is_rejected'):
        status_icon = '🔴 REJECTED'
        card_classes = 'w-full p-4 bg-red-50 border-2 border-red-300'
    elif seg.get('is_reviewed'):
        status_icon = '✅ Reviewed'
        card_classes = 'w-full p-4 bg-green-50 border-2 border-green-300'
    else:
        status_icon = '⏳ Pending'
        card_classes = 'w-full p-4'
    
    with ui.card().classes(card_classes):
        # Header
        with ui.row().classes('w-full justify-between items-center mb-3'):
            ui.label(f"#{seg['segment_index']} | {format_timestamp(start_ms)} - {format_timestamp(end_ms)}").classes('text-lg font-bold')
            ui.badge(status_icon)
        
        # Duration warning
        if duration_ms > WARNING_DURATION_MS:
            ui.label(f"⚠️ Segment is {duration_ms/1000:.1f}s (exceeds 25s limit). Consider splitting.").classes('text-orange-600 font-bold mb-2')
        
        # Play button
        if player:
            def play_segment():
                player.play_segment(start_ms, end_ms)
            
            ui.button(f'▶️ Play segment ({duration_ms/1000:.1f}s)', on_click=play_segment).props('flat color=blue')
        
        ui.separator().classes('my-3')
        
        # Timestamps
        with ui.row().classes('w-full gap-4 mb-4'):
            start_input = ui.input(label='Start', value=ms_to_min_sec_ms(start_ms), placeholder='M:SS.ss').classes('w-32')
            end_input = ui.input(label='End', value=ms_to_min_sec_ms(end_ms), placeholder='M:SS.ss').classes('w-32')
            
            # Duration display
            def update_duration():
                try:
                    new_start_ms = min_sec_ms_to_ms(start_input.value)
                    new_end_ms = min_sec_ms_to_ms(end_input.value)
                    new_duration_ms = new_end_ms - new_start_ms
                    duration_label.set_text(f"Duration: {new_duration_ms/1000:.2f}s")
                    
                    if new_duration_ms > WARNING_DURATION_MS:
                        duration_label.classes('text-red-600 font-bold', remove='text-green-600')
                    else:
                        duration_label.classes('text-green-600', remove='text-red-600 font-bold')
                except:
                    duration_label.set_text("Duration: Invalid")
            
            duration_label = ui.label(f"Duration: {duration_ms/1000:.2f}s").classes('self-center')
            if duration_ms > WARNING_DURATION_MS:
                duration_label.classes('text-red-600 font-bold')
            else:
                duration_label.classes('text-green-600')
            
            start_input.on_value_change(lambda: update_duration())
            end_input.on_value_change(lambda: update_duration())
        
        # Transcript and translation
        with ui.row().classes('w-full gap-4 mb-4'):
            transcript_input = ui.textarea(label='Transcript', value=transcript).classes('flex-1').props('auto-grow')
            translation_input = ui.textarea(label='Translation', value=translation).classes('flex-1').props('auto-grow')
        
        # Action buttons
        with ui.row().classes('gap-2'):
            def save_changes():
                try:
                    new_start_ms = min_sec_ms_to_ms(start_input.value)
                    new_end_ms = min_sec_ms_to_ms(end_input.value)
                    
                    update_segment_review(
                        segment_id=segment_id,
                        reviewed_transcript=transcript_input.value,
                        reviewed_translation=translation_input.value,
                        reviewed_start_ms=new_start_ms,
                        reviewed_end_ms=new_end_ms,
                        is_rejected=False
                    )
                    ui.notify('Segment saved!', type='positive')
                    state.clear_cache()
                    refresh_callback()
                except Exception as e:
                    ui.notify(f'Error: {e}', type='negative')
            
            def approve_segment():
                try:
                    new_start_ms = min_sec_ms_to_ms(start_input.value)
                    new_end_ms = min_sec_ms_to_ms(end_input.value)
                    
                    update_segment_review(
                        segment_id=segment_id,
                        reviewed_transcript=transcript_input.value,
                        reviewed_translation=translation_input.value,
                        reviewed_start_ms=new_start_ms,
                        reviewed_end_ms=new_end_ms,
                        is_rejected=False
                    )
                    # Update review_state to approved
                    with get_db() as db:
                        db.execute(
                            "UPDATE segments SET review_state = 'approved' WHERE segment_id = ?",
                            (segment_id,)
                        )
                    ui.notify('Segment approved!', type='positive')
                    state.clear_cache()
                    refresh_callback()
                except Exception as e:
                    ui.notify(f'Error: {e}', type='negative')
            
            def reject_segment_action():
                reject_segment(segment_id)
                ui.notify('Segment rejected!', type='warning')
                state.clear_cache()
                refresh_callback()
            
            def split_segment_action():
                # Show split dialog
                with ui.dialog() as dialog, ui.card().classes('w-96'):
                    ui.label('Split Segment').classes('text-xl font-bold mb-4')
                    ui.label(f'Original: {ms_to_min_sec_ms(start_ms)} - {ms_to_min_sec_ms(end_ms)}').classes('text-sm text-gray-600 mb-4')
                    
                    split_time_input = ui.input(
                        label='Split Time (M:SS.ss)',
                        placeholder='M:SS.ss',
                        value=ms_to_min_sec_ms(start_ms + (end_ms - start_ms) // 2)
                    ).classes('w-full mb-4')
                    
                    ui.separator().classes('my-4')
                    
                    transcript_first_input = ui.textarea(label='First Segment Transcript', value='').classes('w-full mb-2')
                    translation_first_input = ui.textarea(label='First Segment Translation', value='').classes('w-full mb-4')
                    
                    transcript_second_input = ui.textarea(label='Second Segment Transcript', value='').classes('w-full mb-2')
                    translation_second_input = ui.textarea(label='Second Segment Translation', value='').classes('w-full mb-4')
                    
                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancel', on_click=dialog.close).props('flat')
                        
                        def confirm_split():
                            try:
                                split_time_ms = min_sec_ms_to_ms(split_time_input.value)
                                
                                if split_time_ms <= start_ms or split_time_ms >= end_ms:
                                    ui.notify('Split time must be between start and end', type='negative')
                                    return
                                
                                split_segment(
                                    segment_id=segment_id,
                                    split_time_ms=split_time_ms,
                                    transcript_first=transcript_first_input.value,
                                    transcript_second=transcript_second_input.value,
                                    translation_first=translation_first_input.value,
                                    translation_second=translation_second_input.value
                                )
                                ui.notify('Segment split successfully!', type='positive')
                                state.clear_cache()
                                dialog.close()
                                refresh_callback()
                            except Exception as e:
                                ui.notify(f'Error: {e}', type='negative')
                        
                        ui.button('Split', on_click=confirm_split).props('color=primary')
                
                dialog.open()
            
            ui.button('💾 Save', on_click=save_changes).props('color=blue')
            ui.button('✅ Approve', on_click=approve_segment).props('color=green')
            ui.button('❌ Reject', on_click=reject_segment_action).props('color=red flat')
            ui.button('✂️ Split', on_click=split_segment_action).props('color=orange outline')


# =============================================================================
# UPLOAD PAGE
# =============================================================================

@ui.page('/upload')
def upload_page():
    """Data upload page."""
    create_header()
    create_navigation()
    
    with ui.column().classes('w-full p-8'):
        ui.label('⬆️ Upload Data').classes('text-3xl font-bold mb-6')
        
        # Placeholder - will implement in next phase
        ui.label('Upload functionality coming soon...').classes('text-gray-600')
        ui.label('For now, use the Download Audios page to ingest YouTube videos.').classes('text-sm text-gray-500')


# =============================================================================
# AUDIO REFINEMENT PAGE
# =============================================================================

@ui.page('/refinement')
def refinement_page():
    """Audio refinement (denoising) page."""
    create_header()
    create_navigation()
    
    with ui.column().classes('w-full p-8'):
        ui.label('🎛️ Audio Refinement').classes('text-3xl font-bold mb-6')
        
        # Placeholder - will implement in next phase
        ui.label('Denoising functionality coming soon...').classes('text-gray-600')


# =============================================================================
# DOWNLOAD AUDIOS PAGE
# =============================================================================

@ui.page('/download')
def download_page():
    """YouTube ingestion page."""
    create_header()
    create_navigation()
    
    with ui.column().classes('w-full p-8'):
        ui.label('📥 Download Audios').classes('text-3xl font-bold mb-6')
        
        # Runtime health check
        with ui.expansion('Runtime Health', icon='info').classes('mb-4'):
            status = js_runtime_status()
            if status == "ok":
                ui.label('✓ JavaScript runtime detected').classes('text-green-600')
            else:
                ui.label('⚠️ No JavaScript runtime found. Install Node.js, Deno, or Bun to avoid yt-dlp failures.').classes('text-orange-600')
        
        # Instructions
        with ui.expansion('ℹ️ Instructions', icon='help').classes('mb-6'):
            ui.markdown('''
            - Paste YouTube video or playlist URLs (one per line)
            - Click "Fetch Metadata" to load video information
            - Select which videos to download
            - Click "Download Selected" to start ingestion
            ''')
        
        # URL input
        url_input = ui.textarea(
            label='YouTube URLs (one per line)',
            placeholder='https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=...'
        ).classes('w-full mb-4').props('rows=5')
        
        # Dry run checkbox
        dry_run_check = ui.checkbox('Dry run (simulation only)', value=False).classes('mb-4')
        
        # Fetch button
        videos_container = ui.column().classes('w-full')
        
        def fetch_metadata():
            videos_container.clear()
            
            if not url_input.value:
                with videos_container:
                    ui.label('Please enter at least one URL').classes('text-orange-600')
                return
            
            urls = [line.strip() for line in url_input.value.split('\n') if line.strip()]
            
            with videos_container:
                ui.label('Fetching metadata...').classes('text-blue-600 mb-4')
            
            # Fetch metadata
            fetched_videos = []
            for url in urls:
                try:
                    if url in state.playlist_cache:
                        videos = state.playlist_cache[url]
                    else:
                        videos = fetch_playlist_metadata(url)
                        state.playlist_cache[url] = videos
                    fetched_videos.extend(videos)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")
            
            state.ingest_videos = fetched_videos
            
            videos_container.clear()
            
            if not fetched_videos:
                with videos_container:
                    ui.label('No videos found').classes('text-gray-600')
                return
            
            with videos_container:
                ui.label(f'Found {len(fetched_videos)} videos').classes('text-lg font-bold mb-4')
                
                # Simple table with checkboxes
                with ui.column().classes('w-full gap-2'):
                    select_all_check = ui.checkbox('Select All', value=True).classes('font-bold mb-2')
                    
                    video_checks = []
                    for idx, video in enumerate(fetched_videos):
                        with ui.row().classes('items-center gap-4 p-2 border rounded'):
                            check = ui.checkbox(value=True)
                            video_checks.append(check)
                            ui.label(f"{video.get('title', 'Unknown')}").classes('flex-1')
                            ui.label(video.get('duration', 'Unknown')).classes('text-sm text-gray-600')
                    
                    def toggle_all():
                        for check in video_checks:
                            check.value = select_all_check.value
                    
                    select_all_check.on_value_change(lambda: toggle_all())
                
                ui.separator().classes('my-4')
                
                # Download button
                def download_selected():
                    selected = [
                        fetched_videos[i] for i in range(len(fetched_videos))
                        if i < len(video_checks) and video_checks[i].value
                    ]
                    
                    if not selected:
                        ui.notify('No videos selected', type='warning')
                        return
                    
                    ui.notify(f'Starting ingestion of {len(selected)} videos...', type='info')
                    
                    # Call run_pipeline
                    try:
                        video_ids = [v.get('id') for v in selected]
                        urls = [v.get('url') for v in selected]
                        
                        # Run pipeline in background (simplified - in production use asyncio)
                        for url in urls:
                            run_pipeline(
                                url=url,
                                download_transcript=True,
                                dry_run=dry_run_check.value
                            )
                        
                        ui.notify('Ingestion complete!', type='positive')
                        state.clear_cache()
                    except Exception as e:
                        ui.notify(f'Error: {e}', type='negative')
                        logger.error(f"Ingestion error: {e}")
                
                ui.button('📥 Download Selected', on_click=download_selected).props('color=primary size=lg')
        
        ui.button('🔍 Fetch Metadata', on_click=fetch_metadata).props('color=primary outline')


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main application entry point."""
    # Ensure database exists
    if not DEFAULT_DB_PATH.exists():
        logger.info("Database not found, initializing...")
        init_database()
        ensure_schema_upgrades()
    else:
        ensure_schema_upgrades()
    
    # Start NiceGUI server
    ui.run(
        host='0.0.0.0',  # Bind to all IPs (for Tailscale)
        port=8501,
        title='Code-Switch Review Tool',
        dark=None,  # Auto-detect dark mode
        reload=False,
        show=False  # Don't auto-open browser
    )


if __name__ == '__main__':
    main()

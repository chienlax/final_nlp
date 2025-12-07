"""
NiceGUI Review Application - Simplified Multi-Page Version.

Event-driven web interface for reviewing transcriptions and translations.
Uses NiceGUI's proper multi-page pattern with page decorators defined
before ui.run().
"""

import asyncio
import functools
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from nicegui import app, ui

# Configure paths
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
    reject_segment,
    split_segment,
    update_chunk_state,
    update_segment_review,
    update_video_channel,
    update_video_reviewer,
)
from utils.video_downloading_utils import CHUNK_QUEUE_FILE, ensure_js_runtime

# =============================================================================
# CONFIGURATION
# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT
AUDIO_ROOT = DATA_ROOT / "raw" / "audio"

WARNING_DURATION_MS = 25000
MAX_DURATION_MS = 30000
SEGMENTS_PER_PAGE = 25

# Serve audio files
app.add_static_files('/data', str(DATA_ROOT))

# Styling
ui.colors(primary='#22c55e')


# =============================================================================
# UTILITIES
# =============================================================================

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
    """Convert ms to min:sec.ms format."""
    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:05.2f}"


def min_sec_ms_to_ms(time_str: str) -> int:
    """Convert min:sec.ms format to milliseconds."""
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError(f"Invalid format: {time_str}")
        minutes = int(parts[0])
        seconds = float(parts[1])
        return int((minutes * 60 + seconds) * 1000)
    except Exception as e:
        logger.error(f"Invalid timestamp: {time_str}, {e}")
        return 0


def get_static_audio_url(audio_path: Path) -> str:
    """Convert audio path to static URL."""
    try:
        relative = audio_path.relative_to(DATA_ROOT)
        return f"/data/{relative.as_posix()}"
    except ValueError:
        try:
            relative = audio_path.relative_to(PROJECT_ROOT)
            parts = relative.parts
            if parts[0] == 'data':
                relative = Path(*parts[1:])
            return f"/data/{relative.as_posix()}"
        except ValueError:
            return ""


def ttl_cache(seconds: int, maxsize: int = 128):
    """Decorator for caching with TTL."""
    def decorator(func):
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
def cached_get_videos_by_state(state: str):
    return get_videos_by_state(state)


@ttl_cache(seconds=60)
def cached_get_database_stats():
    return get_database_stats()


def clear_all_caches():
    """Clear all TTL caches."""
    cached_get_videos_by_state.cache_clear()
    cached_get_database_stats.cache_clear()


# =============================================================================
# PAGES
# =============================================================================

@ui.page('/')
def dashboard():
    """Dashboard page."""
    ui.label('📊 Dashboard').classes('text-3xl font-bold mb-6 p-8')
    
    with ui.column().classes('w-full p-8'):
        try:
            stats = cached_get_database_stats()
        except Exception as e:
            ui.label(f"Error: {e}").classes('text-red-600')
            if ui.button('Initialize Database'):
                init_database()
                ensure_schema_upgrades()
                ui.notify('Database initialized!', type='positive')
                ui.navigate.reload()
            return
        
        # Summary cards
        with ui.row().classes('w-full gap-4 mb-6'):
            with ui.card().classes('p-6 bg-gradient-to-br from-purple-500 to-indigo-600 text-white'):
                ui.label('Videos').classes('text-sm opacity-75')
                ui.label(str(stats.get('total_videos', 0))).classes('text-4xl font-bold')
            
            with ui.card().classes('p-6 bg-gradient-to-br from-green-500 to-emerald-600 text-white'):
                reviewed = stats.get('reviewed_segments', 0)
                total = stats.get('total_segments', 1)
                pct = int(100 * reviewed / total) if total > 0 else 0
                ui.label('Progress').classes('text-sm opacity-75')
                ui.label(f"{pct}%").classes('text-4xl font-bold')
        
        ui.button('Go to Review', on_click=lambda: ui.navigate.to('/review')).props('size=lg color=primary')


@ui.page('/review')
def review():
    """Review page."""
    ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6 p-8')
    
    with ui.column().classes('w-full p-8'):
        # Get videos
        transcribed = cached_get_videos_by_state('transcribed')
        pending = cached_get_videos_by_state('pending')
        reviewed = cached_get_videos_by_state('reviewed')
        all_videos = transcribed + reviewed + pending
        
        if not all_videos:
            ui.label('No videos to review').classes('text-gray-600')
            ui.button('Back to Dashboard', on_click=lambda: ui.navigate.to('/')).props('flat')
            return
        
        # Video selector
        video_options = {
            f"{v['title'][:50]}": v['video_id']
            for v in all_videos
        }
        
        selected = ui.select(
            label='Select Video',
            options=list(video_options.keys()),
            value=list(video_options.keys())[0] if video_options else None
        ).classes('w-full mb-4')
        
        # Video details container
        details_container = ui.column().classes('w-full')
        
        def show_video():
            if not selected.value:
                return
            
            details_container.clear()
            video_id = video_options[selected.value]
            video = get_video(video_id)
            
            if not video:
                with details_container:
                    ui.label('Video not found').classes('text-red-600')
                return
            
            with details_container:
                ui.label(video['title']).classes('text-2xl font-bold mb-4')
                
                # Get chunks
                chunks = get_chunks_by_video(video_id)
                if not chunks:
                    ui.label('No chunks found').classes('text-gray-600')
                    return
                
                # Simple chunk display (first chunk only for demo)
                chunk = chunks[0]
                show_chunk(video_id, chunk, video)
        
        selected.on_value_change(lambda: show_video())
        show_video()


def show_chunk(video_id: str, chunk: Dict[str, Any], video: Dict[str, Any]):
    """Display chunk with segments."""
    ui.label(f"Chunk {chunk['chunk_index']}").classes('text-xl font-bold mt-4 mb-2')
    
    # Audio player
    audio_path_str = chunk['audio_path']
    if audio_path_str.startswith('data'):
        audio_path = PROJECT_ROOT / audio_path_str
    else:
        audio_path = DATA_ROOT / audio_path_str
    
    if audio_path.exists():
        audio_url = get_static_audio_url(audio_path)
        ui.html(f'''
            <audio controls preload="metadata" style="width: 100%; margin: 10px 0;">
                <source src="{audio_url}" type="audio/wav">
            </audio>
        ''')
    
    # Get segments
    segments = get_segments(video_id, chunk_id=chunk['chunk_id'])
    if not segments:
        ui.label('No segments found').classes('text-gray-600')
        return
    
    ui.label(f"{len(segments)} segments").classes('text-sm text-gray-600 mb-4')
    
    # Show first few segments
    for seg in segments[:5]:
        show_segment(seg, video_id, chunk)


def show_segment(seg: Dict[str, Any], video_id: str, chunk: Dict[str, Any]):
    """Display editable segment card."""
    start_ms = seg.get('reviewed_start_ms') or seg['start_ms']
    end_ms = seg.get('reviewed_end_ms') or seg['end_ms']
    transcript = seg.get('reviewed_transcript') or seg['transcript']
    translation = seg.get('reviewed_translation') or seg['translation']
    
    with ui.card().classes('w-full p-4 mb-3'):
        ui.label(f"#{seg['segment_index']} | {format_timestamp(start_ms)} - {format_timestamp(end_ms)}").classes('font-bold mb-2')
        
        t_input = ui.textarea(label='Transcript', value=transcript).classes('w-full mb-2')
        tr_input = ui.textarea(label='Translation', value=translation).classes('w-full mb-2')
        
        def save():
            update_segment_review(
                segment_id=seg['segment_id'],
                reviewed_transcript=t_input.value,
                reviewed_translation=tr_input.value,
                is_rejected=False
            )
            ui.notify('Saved!', type='positive')
            clear_all_caches()
        
        ui.button('💾 Save', on_click=save).props('color=primary sm')


# =============================================================================
# MAIN
# =============================================================================

if __name__ in {"__main__", "__mp_main__"}:
    # Ensure database exists
    if not DEFAULT_DB_PATH.exists():
        init_database()
        ensure_schema_upgrades()
    else:
        ensure_schema_upgrades()
    
    ui.run(
        host='0.0.0.0',
        port=8501,
        title='Code-Switch Review Tool',
        show=False,
        reload=False
    )

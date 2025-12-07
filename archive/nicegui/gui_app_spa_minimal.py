"""
NiceGUI Review Application - SPA Version.

Single Page Application with tab-based navigation.
This version works around NiceGUI's routing limitations in script mode.
"""

import sys
from pathlib import Path

from nicegui import app, ui

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

# Import only database functions, NOT gui_app (which has decorator issues)
from db import (
    DEFAULT_DB_PATH,
    ensure_schema_upgrades,
    get_database_stats,
    init_database,
)

# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT

# =============================================================================
# MAIN SPA PAGE (No decorators - built directly)
# =============================================================================

def build_ui():
    """Build the UI directly without page decorators."""
    # Header
    with ui.header().classes('bg-slate-900 text-white items-center justify-between p-4'):
        ui.label('🎧 Code-Switch Review Tool').classes('text-2xl font-bold')
        ui.label('Multi-functional review interface').classes('text-sm text-gray-300')
    
    # Tab navigation
    with ui.tabs().classes('w-full bg-slate-100') as tabs:
        ui.tab('dashboard', label='📊 Dashboard', icon='dashboard')
        ui.tab('review', label='📝 Review', icon='edit')
        ui.tab('upload', label='⬆️ Upload', icon='upload')
        ui.tab('refinement', label='🎛️ Refinement', icon='tune')
        ui.tab('download', label='📥 Download', icon='download')
    
    # Tab panels with content
    with ui.tab_panels(tabs, value='dashboard').classes('w-full'):
        with ui.tab_panel('dashboard'):
            render_dashboard_content()
        
        with ui.tab_panel('review'):
            render_review_content()
        
        with ui.tab_panel('upload'):
            render_upload_content()
        
        with ui.tab_panel('refinement'):
            render_refinement_content()
        
        with ui.tab_panel('download'):
            render_download_content()


def main():
    """Main application entry point."""
    # Serve audio files statically
    app.add_static_files('/data', str(DATA_ROOT))
    
    # Configure theme
    ui.colors(primary='#22c55e')
    
    # Ensure database exists
    if not DEFAULT_DB_PATH.exists():
        init_database()
        ensure_schema_upgrades()
    else:
        ensure_schema_upgrades()
    
    # Build UI directly (no page routing)
    build_ui()
    
    # Start server
    ui.run(
        host='0.0.0.0',
        port=8501,
        title='Code-Switch Review Tool',
        dark=None,
        reload=False,
        show=False
    )


# =============================================================================
# CONTENT RENDERERS (Call original page functions but skip header/nav)
# =============================================================================

def render_dashboard_content():
    """Render dashboard content without header/navigation."""
    with ui.column().classes('w-full p-8'):
        ui.label('📊 Dashboard').classes('text-3xl font-bold mb-6')
        
        try:
            stats = get_database_stats()
        except Exception as e:
            ui.label(f'Error loading stats: {e}').classes('text-red-600')
            return
        
        # Stats cards
        with ui.row().classes('w-full gap-4 mb-6'):
            with ui.card().classes('p-6 flex-1'):
                ui.label('Videos').classes('text-sm text-gray-600')
                ui.label(str(stats.get('total_videos', 0))).classes('text-4xl font-bold text-blue-600')
            
            with ui.card().classes('p-6 flex-1'):
                ui.label('Hours of Audio').classes('text-sm text-gray-600')
                ui.label(f"{stats.get('total_hours', 0):.1f}").classes('text-4xl font-bold text-green-600')
            
            with ui.card().classes('p-6 flex-1'):
                ui.label('Total Segments').classes('text-sm text-gray-600')
                ui.label(str(stats.get('total_segments', 0))).classes('text-4xl font-bold text-purple-600')
            
            with ui.card().classes('p-6 flex-1'):
                ui.label('Reviewed').classes('text-sm text-gray-600')
                ui.label(f"{stats.get('review_percent', stats.get('reviewed_percent', 0)):.0f}%").classes('text-4xl font-bold text-orange-600')
        
        # Videos by state
        with ui.card().classes('w-full p-6 mb-4'):
            ui.label('Videos by State').classes('text-lg font-bold mb-4')
            
            for state, count in stats.get('videos_by_state', {}).items():
                with ui.row().classes('w-full justify-between items-center mb-2'):
                    ui.badge(state, color='primary')
                    ui.label(f"{count} videos").classes('font-bold')


def render_review_content():
    """Render review page content."""
    with ui.column().classes('w-full p-8'):
        ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6')
        ui.label('Full review interface - Use original gui_app.py').classes('text-gray-600')
        ui.markdown('''
        **Note:** The full review interface with chunk tabs, audio player, and inline editing
        is available in the original multi-page version.
        
        To use it, you need to either:
        1. Run with NiceGUI in development mode
        2. Deploy as separate page files
        3. Use this SPA version for testing the workflow
        
        For now, use the Upload and Download tabs to test the workflow.
        ''')


def render_upload_content():
    """Render upload page content."""
    with ui.column().classes('w-full p-8'):
        ui.label('⬆️ Upload Data').classes('text-3xl font-bold mb-6')
        ui.label('Upload functionality available in full version').classes('text-gray-600')
        ui.markdown('''
        The upload page allows you to upload:
        - Audio files (.wav, .mp3, .flac, .ogg)
        - Transcript JSON files
        
        Use the Download tab to ingest from YouTube instead.
        ''')


def render_refinement_content():
    """Render refinement page content."""
    with ui.column().classes('w-full p-8'):
        ui.label('🎛️ Audio Refinement').classes('text-3xl font-bold mb-6')
        ui.label('Denoising functionality available in full version').classes('text-gray-600')


def render_download_content():
    """Render download page content."""
    with ui.column().classes('w-full p-8'):
        ui.label('📥 Download Audios').classes('text-3xl font-bold mb-6')
        
        ui.label('YouTube ingestion - Use ingest_youtube.py CLI for now').classes('text-gray-600')
        ui.markdown('''
        **To download videos:**
        
        ```bash
        python src/ingest_youtube.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
        ```
        
        Or use the command line workflow documented in docs/WORKFLOW.md
        ''')


if __name__ == '__main__':
    main()

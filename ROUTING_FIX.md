# QUICK FIX: NiceGUI Routing Issue

**Problem:** `RuntimeError: ui.page cannot be used in NiceGUI scripts where you define UI in the global scope.`

**Solution:** Convert to Single Page App (SPA) with tab-based navigation

**Time Required:** 1-2 hours

---

## Step-by-Step Fix

### Step 1: Backup Current Version
```bash
cp src/gui_app.py src/gui_app_broken.py
```

### Step 2: Replace Page Decorators with Single Page

**BEFORE:**
```python
@ui.page('/')
def dashboard():
    # dashboard code

@ui.page('/review')
def review():
    # review code

@ui.page('/upload')
def upload():
    # upload code
```

**AFTER:**
```python
@ui.page('/')
def main_app():
    # Navigation tabs
    with ui.tabs().classes('w-full') as tabs:
        ui.tab('dashboard', label='📊 Dashboard', icon='dashboard')
        ui.tab('review', label='📝 Review', icon='edit')
        ui.tab('upload', label='⬆️ Upload', icon='upload')
        ui.tab('refinement', label='🎛️ Refinement', icon='tune')
        ui.tab('download', label='📥 Download', icon='download')
    
    # Tab panels (content for each tab)
    with ui.tab_panels(tabs, value='dashboard').classes('w-full'):
        with ui.tab_panel('dashboard'):
            render_dashboard()
        
        with ui.tab_panel('review'):
            render_review()
        
        with ui.tab_panel('upload'):
            render_upload()
        
        with ui.tab_panel('refinement'):
            render_refinement()
        
        with ui.tab_panel('download'):
            render_download()
```

### Step 3: Convert Page Functions to Render Functions

**BEFORE:**
```python
@ui.page('/review')
def review():
    """Review page."""
    create_header()  # ❌ Remove this (no header needed in tabs)
    create_navigation()  # ❌ Remove this
    
    with ui.column().classes('w-full p-8'):
        ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6')
        # ... rest of review page code
```

**AFTER:**
```python
def render_review():
    """Render review tab content."""
    with ui.column().classes('w-full p-8'):
        ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6')
        # ... rest of review page code (same as before)
```

### Step 4: Update Main Function

**BEFORE:**
```python
if __name__ in {"__main__", "__mp_main__"}:
    if not DEFAULT_DB_PATH.exists():
        init_database()
        ensure_schema_upgrades()
    else:
        ensure_schema_upgrades()
    
    ui.run(host='0.0.0.0', port=8501, title='Code-Switch Review Tool', show=False, reload=False)
```

**AFTER:**
```python
if __name__ in {"__main__", "__mp_main__"}:
    # Database initialization
    if not DEFAULT_DB_PATH.exists():
        init_database()
        ensure_schema_upgrades()
    else:
        ensure_schema_upgrades()
    
    # Start server (all pages registered via decorators above)
    ui.run(
        host='0.0.0.0',
        port=8501,
        title='Code-Switch Review Tool',
        show=False,
        reload=False
    )
```

---

## Complete Example

Here's a minimal working example showing the pattern:

```python
from nicegui import app, ui
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT = PROJECT_ROOT

# Serve static files
app.add_static_files('/data', str(DATA_ROOT))

# Utility functions (unchanged)
def format_timestamp(ms: int) -> str:
    seconds = ms // 1000
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"

# Render functions (converted from @ui.page functions)
def render_dashboard():
    with ui.column().classes('w-full p-8'):
        ui.label('📊 Dashboard').classes('text-3xl font-bold mb-6')
        with ui.card().classes('p-6'):
            ui.label('Welcome to the Dashboard!')
            ui.button('Go to Review', on_click=lambda: tabs.set_value('review'))

def render_review():
    with ui.column().classes('w-full p-8'):
        ui.label('📝 Review Videos').classes('text-3xl font-bold mb-6')
        with ui.card().classes('p-6'):
            ui.label('Review interface goes here')

def render_upload():
    with ui.column().classes('w-full p-8'):
        ui.label('⬆️ Upload Data').classes('text-3xl font-bold mb-6')
        ui.label('Upload functionality coming soon...')

# SINGLE page with tabs
@ui.page('/')
def main_app():
    global tabs  # Make tabs accessible to button callbacks
    
    # Header
    with ui.header().classes('bg-slate-900 text-white'):
        ui.label('🎧 Code-Switch Review Tool').classes('text-xl font-bold')
    
    # Navigation tabs
    with ui.tabs().classes('w-full bg-slate-100') as tabs:
        ui.tab('dashboard', label='📊 Dashboard', icon='dashboard')
        ui.tab('review', label='📝 Review', icon='edit')
        ui.tab('upload', label='⬆️ Upload', icon='upload')
    
    # Tab content
    with ui.tab_panels(tabs, value='dashboard').classes('w-full'):
        with ui.tab_panel('dashboard'):
            render_dashboard()
        
        with ui.tab_panel('review'):
            render_review()
        
        with ui.tab_panel('upload'):
            render_upload()

# Main entry point
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host='0.0.0.0', port=8501, show=False)
```

---

## Verification Checklist

After making changes:

1. ✅ No `@ui.page` decorators except for `main_app()`
2. ✅ No `create_header()` or `create_navigation()` calls in render functions
3. ✅ All page functions renamed to `render_*`
4. ✅ Tabs use icon names from Material Design Icons
5. ✅ `global tabs` declared if you need to switch tabs programmatically

---

## Testing the Fix

```bash
# 1. Start the app
python src/gui_app.py

# 2. Should start without errors
# 3. Open browser to http://localhost:8501
# 4. Click between tabs - should switch instantly
# 5. Test review workflow in Review tab
```

---

## Common Gotchas

### 1. Tab Not Switching
**Problem:** Button click doesn't switch tabs

**Fix:**
```python
# Make tabs accessible globally
@ui.page('/')
def main_app():
    global tabs  # Add this
    with ui.tabs() as tabs:
        # ...
```

### 2. Styles Not Applied
**Problem:** Tabs look unstyled

**Fix:**
```python
# Add classes to tabs container
with ui.tabs().classes('w-full bg-slate-100') as tabs:
    # ...

# Add classes to panels
with ui.tab_panels(tabs).classes('w-full p-4'):
    # ...
```

### 3. State Not Persisting
**Problem:** State resets when switching tabs

**Fix:**
```python
# Use global state object
state = AppState()  # Define outside main_app()

def render_review():
    # Access global state
    if state.selected_video_id:
        # ...
```

---

## Expected Result

After the fix:
- ✅ App starts without errors
- ✅ Single page with tab navigation at top
- ✅ Clicking tabs switches content instantly
- ✅ All features work (dashboard, review, etc.)
- ✅ No page reloads when switching tabs
- ✅ State persists across tab switches

---

## Time Estimate

- **Reading this guide:** 10 minutes
- **Making changes:** 30-60 minutes
- **Testing:** 20-30 minutes
- **Total:** 1-2 hours

---

## If You Get Stuck

### Option 1: Use Simplified Version
```bash
# Already working, just basic features
python src/gui_app_v2.py
```

### Option 2: Ask for Help
- Check `docs/NICEGUI_MIGRATION.md` for more details
- Review NiceGUI examples: https://nicegui.io/documentation/tabs
- Read `src/gui_app_v2.py` for working example

### Option 3: Rollback
```bash
# Revert to Streamlit
pip install streamlit>=1.28.0
streamlit run src/review_app.py
```

---

**Next:** After fixing routing, proceed to full testing workflow (see `docs/QUICKSTART_NICEGUI.md`)

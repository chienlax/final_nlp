"""Preprocessing module for Vietnamese-English CS Speech Translation pipeline.

Active scripts:
- gemini_process.py: Gemini 2.5 Pro transcription + translation
- denoise_audio.py: DeepFilterNet noise removal (optional)
- chunk_audio.py: Audio chunking for long videos (>10 min)

Pipeline Flow (SQLite + Streamlit):
    pending → (denoise) → (chunk) → gemini_process → transcribed
        → review_app.py (Streamlit) → reviewed → export_final.py → exported

Architecture: SQLite database + Streamlit review UI (January 2025 migration)
"""

__version__ = "4.0.0"
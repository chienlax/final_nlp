"""
"""Preprocessing module for Vietnamese-English CS Speech Translation pipeline.

This module contains all preprocessing scripts for the audio processing pipeline:
- gemini_process.py: Unified Gemini transcription + translation with structured output
- gemini_repair_translation.py: Repair script for translation issues
- prepare_review_audio.py: Cut sentence-level audio for Label Studio review
- apply_review.py: Apply human corrections back to database
- denoise_audio.py: DeepFilterNet noise removal (optional)

Pipeline Flow:
    RAW → gemini_process.py → TRANSLATED (with needs_translation_review flag if issues)
        → gemini_repair_translation.py (if issues detected) → ready for human review
        → prepare_review_audio.py → Label Studio → apply_review.py → FINAL

Schema Version: 3.1 (Unified Gemini processing pipeline)
"""

__version__ = "3.1.0"

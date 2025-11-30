"""
Preprocessing module for Vietnamese-English CS Speech Translation pipeline.

This module contains all preprocessing scripts for the audio processing pipeline:
- whisperx_align.py: WhisperX alignment using Vietnamese wav2vec2 model
- segment_audio.py: Audio segmentation into 10-30s chunks
- gemini_process.py: Unified Gemini transcription + translation with structured output
- gemini_repair_translation.py: Repair script for translation issues
- denoise_audio.py: DeepFilterNet noise removal

Pipeline Flow:
    RAW → gemini_process.py → TRANSLATED (with needs_translation_review flag if issues)
        → gemini_repair_translation.py (if issues detected) → ready for human review

Schema Version: 3.1 (Unified Gemini processing pipeline)
"""

__version__ = "3.1.0"

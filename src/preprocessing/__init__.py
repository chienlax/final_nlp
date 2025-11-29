"""
Preprocessing module for Vietnamese-English CS Speech Translation pipeline.

This module contains all preprocessing scripts for the audio processing pipeline:
- whisperx_align.py: WhisperX alignment using Vietnamese wav2vec2 model
- segment_audio.py: Audio segmentation into 10-30s chunks
- translate.py: Gemini API translation with key rotation
- denoise_audio.py: DeepFilterNet noise removal

Schema Version: 3.0 (Simplified YouTube-only pipeline)
"""

__version__ = "3.0.0"

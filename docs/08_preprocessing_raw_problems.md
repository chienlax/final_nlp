# 08. Preprocessing Raw Data: Problems & Solutions

This document catalogs all known challenges in the preprocessing pipeline for Vietnamese-English Code-Switching (CS) Speech Translation data. Use this as a planning reference before implementation.

---

## Table of Contents

1. [Audio Segmentation Problems](#1-audio-segmentation-problems)
2. [Signal Enhancement Problems](#2-signal-enhancement-problems)
3. [TTS Synthesis Problems](#3-tts-synthesis-problems)
4. [Cross-Cutting Infrastructure Problems](#4-cross-cutting-infrastructure-problems)
5. [Data Quality & Validation Problems](#5-data-quality--validation-problems)
6. [Additional Workflow Problems](#6-additional-workflow-problems)
7. [Decision Matrix](#7-decision-matrix)
8. [Next Steps](#8-next-steps)

---

## 1. Audio Segmentation Problems

### 1.1 MFA Dictionary Mismatch (Code-Switching)

| Aspect | Details |
|--------|---------|
| **Problem** | Montreal Forced Aligner (MFA) uses a **single pronunciation dictionary** per run. Vietnamese-English CS audio contains words from both languages, but MFA's Vietnamese dictionary does not include English phonemes (and vice versa). Running with only the Vietnamese dictionary causes English words to fail alignment or be forced into incorrect Vietnamese phoneme sequences. |
| **Impact** | Misaligned timestamps, dropped words, garbage phoneme outputs for English tokens. |
| **Proposed Solutions** | |
| Option A | **Merged Dictionary**: Create a custom dictionary combining Vietnamese phonemes (from `vietnamese_mfa`) and English phonemes (from `english_us_arpa`). Requires manual phoneme mapping to avoid conflicts (e.g., Vietnamese `a` vs English `æ`). |
| Option B | **Two-Pass Alignment**: Run MFA twice (once with Vietnamese model, once with English model), then merge alignments by selecting the higher-confidence result per word. Slower but avoids dictionary conflicts. |
| Option C | **Hybrid LID-First**: Use word-level Language ID to tag each word before alignment, then route Vietnamese words to Vietnamese MFA and English words to English MFA in a single coordinated pass. |
| **Recommendation** | Start with **Option B** (two-pass) for simplicity. Migrate to **Option A** (merged dictionary) once phoneme mapping is validated. |

---

### 1.2 Timestamp Drift Between YouTube Captions and Audio

| Aspect | Details |
|--------|---------|
| **Problem** | YouTube caption timestamps are approximate (often rounded to 0.1s or 0.5s boundaries). The actual speech may start 100-500ms before or after the caption timestamp. This drift accumulates over long videos. |
| **Impact** | MFA alignment fails when the seed timestamps are too far from reality. Segments may cut off word beginnings/endings. |
| **Proposed Solutions** | |
| Option A | **Pre-alignment VAD Pass**: Run Voice Activity Detection (VAD) first to identify actual speech regions, then snap YouTube timestamps to nearest VAD boundary before MFA. |
| Option B | **MFA Beam Search**: Increase MFA's beam width to allow more flexibility in finding the correct alignment despite drift. Slower but more robust. |
| Option C | **Chunk-wise Alignment**: Split audio into 30-60 second chunks with overlapping boundaries, align each chunk independently, then stitch results. Prevents drift accumulation. |
| **Recommendation** | **Option C** (chunk-wise) combined with **Option A** (VAD pre-pass) for best results. |

---

### 1.3 Missing Transcripts (Auto-Generated Only or None)

| Aspect | Details |
|--------|---------|
| **Problem** | Some YouTube videos have only auto-generated captions (lower quality) or no captions at all. Auto-generated captions often hallucinate words, especially for CS content where the ASR model is confused by language mixing. |
| **Impact** | Cannot use transcript-aware MFA alignment. Must fall back to transcript-free methods. |
| **Proposed Solutions** | |
| Option A | **VAD-Only Segmentation**: Use Silero VAD or pyannote.audio to detect speech segments without any transcript. Results in "blind" segments that need ASR downstream. |
| Option B | **ASR-First Pipeline**: Run Whisper (large-v3) to generate a transcript first, then feed that transcript to MFA for refinement. Whisper handles CS better than YouTube's ASR. |
| Option C | **Skip and Flag**: Mark these samples as `NEEDS_MANUAL_TRANSCRIPT` and defer to human annotation in Label Studio. |
| **Recommendation** | **Option B** (Whisper → MFA) for videos with auto-captions. **Option A** (VAD-only) for videos with no captions at all. |

---

### 1.4 Speaker Diarization in Multi-Speaker Videos

| Aspect | Details |
|--------|---------|
| **Problem** | Vlogs often feature multiple speakers (host + guest, interviews, reactions). MFA aligns the transcript to the audio but does not identify *who* is speaking. Segments may contain overlapping speech or speaker changes mid-segment. |
| **Impact** | Training data quality degrades if different speakers are mixed in a single sample. Speaker identity is lost. |
| **Proposed Solutions** | |
| Option A | **pyannote.audio Diarization**: Run speaker diarization before segmentation to identify speaker turns. Split segments at speaker boundaries, tag each segment with speaker ID. |
| Option B | **Single-Speaker Filter**: Use diarization to estimate speaker count; if >1 speaker, either skip the video or extract only the dominant speaker's segments. |
| Option C | **Ignore for Now**: Accept mixed-speaker segments initially; refine later if needed for speaker-conditioned models. |
| **Recommendation** | **Option A** (pyannote diarization) is ideal for quality. Start with **Option C** if resources are limited. |

---

### 1.5 Segment Length Variability

| Aspect | Details |
|--------|---------|
| **Problem** | MFA outputs word-level alignments. Merging into sentence-level segments requires heuristics (punctuation, pause duration). This can produce segments ranging from 0.5s to 30s+ depending on the speaker's pacing and transcript punctuation quality. |
| **Impact** | Very short segments (<1s) lack context. Very long segments (>20s) are hard for downstream models and may span topic changes. |
| **Proposed Solutions** | |
| Option A | **Fixed-Length Chunking**: After MFA, re-segment into fixed 5-15 second chunks, splitting at word boundaries with minimum pause. |
| Option B | **Pause-Based Merging with Min/Max Bounds**: Merge words into segments using pause threshold (e.g., 300ms), but enforce min=2s, max=15s constraints. Split long segments at sentence boundaries; merge short segments with neighbors. |
| Option C | **Hierarchical Segments**: Keep both fine-grained (word-level) and coarse (sentence-level) alignments in database. Let downstream tasks choose granularity. |
| **Recommendation** | **Option B** (bounded merging) for training data. Store **Option C** (hierarchical) in database for flexibility. |

---

### 1.6 Non-Speech Audio Events

| Aspect | Details |
|--------|---------|
| **Problem** | Vlogs contain non-speech audio: music intros/outros, sound effects, laughter, coughs, filler sounds ("uhh", "hmm"). These are not in the transcript but occupy audio time. |
| **Impact** | MFA struggles to align silence/noise regions. Resulting segments may include unwanted audio at boundaries. |
| **Proposed Solutions** | |
| Option A | **VAD Masking**: Run VAD first, mask non-speech regions, only align within speech regions. |
| Option B | **Post-Alignment Trimming**: After MFA, trim segment boundaries to exclude leading/trailing silence using energy-based detection. |
| Option C | **Filler Word Dictionary**: Add common fillers ("ờ", "à", "uhh", "umm") to the pronunciation dictionary so MFA can align them explicitly. |
| **Recommendation** | Combine **Option A** (VAD masking) + **Option B** (post-trim) + **Option C** (filler dictionary). |

---

## 2. Signal Enhancement Problems

### 2.1 Over-Denoising Artifacts

| Aspect | Details |
|--------|---------|
| **Problem** | Aggressive noise reduction can introduce "musical noise" (tonal artifacts), remove speech harmonics, or make audio sound robotic/underwater. This is especially problematic for low-SNR recordings where the boundary between speech and noise is unclear. |
| **Impact** | Enhanced audio sounds unnatural; may hurt ASR/ST model training if artifacts are consistent patterns. |
| **Proposed Solutions** | |
| Option A | **Conservative Default**: Use DeepFilterNet with lower enhancement strength (e.g., `--atten-lim 12` instead of default 100). Accept some residual noise. |
| Option B | **SNR-Adaptive Processing**: Estimate input SNR first; only apply heavy denoising to low-SNR (<10dB) files. Skip or light-touch high-SNR files. |
| Option C | **A/B Storage**: Store both original and enhanced audio; let downstream tasks choose. Include `enhancement_strength` in metadata. |
| **Recommendation** | **Option B** (SNR-adaptive) with **Option C** (dual storage) for traceability. |

---

### 2.2 Demucs Computational Cost

| Aspect | Details |
|--------|---------|
| **Problem** | Demucs (music source separation) is GPU-intensive and processes at ~0.5x real-time even on modern GPUs. Processing hundreds of hours of "music" or "reaction" videos is expensive. |
| **Impact** | Pipeline bottleneck. High cloud compute costs if running on GPU instances. |
| **Proposed Solutions** | |
| Option A | **Strict Filtering**: Only route videos with explicit `music` category tag to Demucs. Use DeepFilterNet for everything else, including reactions without background music. |
| Option B | **Music Detection Pre-Filter**: Run a lightweight music detector (e.g., `musicnn` or simple spectral analysis) to identify segments with actual background music before routing to Demucs. |
| Option C | **Demucs Lite**: Use the smaller `htdemucs` model instead of `htdemucs_ft` for faster processing with acceptable quality trade-off. |
| **Recommendation** | **Option B** (music detection) + **Option C** (lighter model). Only use Demucs when music is confirmed present. |

---

### 2.3 Enhancement Destroying Code-Switching Cues

| Aspect | Details |
|--------|---------|
| **Problem** | Some acoustic cues that distinguish Vietnamese from English (e.g., tonal contours for Vietnamese, certain English phonemes) might be subtly affected by enhancement models trained primarily on English/Western speech. |
| **Impact** | Hypothetically, enhanced audio could lose subtle CS markers. Needs empirical validation. |
| **Proposed Solutions** | |
| Option A | **Empirical Testing**: Run a small-scale experiment comparing ASR WER on original vs enhanced CS audio. If WER increases, investigate. |
| Option B | **Vietnamese-Trained Enhancer**: If issue is confirmed, fine-tune DeepFilterNet on Vietnamese speech data. |
| Option C | **Skip Enhancement for High-Quality Sources**: If original SNR is already good (>20dB), skip enhancement entirely. |
| **Recommendation** | Start with **Option A** (empirical test) before assuming this is a real problem. |

---

### 2.4 Handling Already-Processed Audio

| Aspect | Details |
|--------|---------|
| **Problem** | Some YouTube videos are already post-processed by creators (noise-gated, compressed, EQ'd). Applying DeepFilterNet on top may cause double-processing artifacts or actually degrade quality. |
| **Impact** | Inconsistent audio quality across dataset. |
| **Proposed Solutions** | |
| Option A | **Quality Detection**: Analyze spectral characteristics to detect already-processed audio (e.g., sharp high-frequency rolloff indicating compression). Skip enhancement for these. |
| Option B | **SNR Threshold**: If estimated SNR is already >25dB, assume audio is clean enough and skip enhancement. |
| Option C | **Metadata Heuristic**: Professional channels (high subscriber count, verified) likely have good audio. Use this as a soft signal to skip enhancement. |
| **Recommendation** | **Option B** (SNR threshold) is simplest and effective. |

---

## 3. TTS Synthesis Problems

### 3.1 Word-Level Language Identification Accuracy

| Aspect | Details |
|--------|---------|
| **Problem** | To insert `[VI]`/`[EN]` tags, we need word-level LID. But short words are ambiguous: "OK" could be English or Vietnamese internet slang, "không" is Vietnamese but might appear in English contexts as a loanword. fastText/langdetect have high error rates on single words. |
| **Impact** | Incorrect tags cause TTS to use wrong phonemization, producing unnatural speech. |
| **Proposed Solutions** | |
| Option A | **Phrase-Level LID**: Instead of word-level, detect language at phrase/clause level (3-5 words). More context = better accuracy. Insert tags at phrase boundaries. |
| Option B | **Dictionary Lookup + LID Fallback**: Maintain a Vietnamese word list and English word list. Use dictionary lookup first; only use LID model for unknown words. |
| Option C | **Character-Based Heuristics**: Vietnamese uses diacritics (ă, â, ê, ô, ơ, ư, đ). If a word contains these, it's Vietnamese. If purely ASCII with common English patterns, assume English. Only use LID for edge cases. |
| Option D | **Manual Annotation**: For high-quality synthetic data, have annotators tag language spans manually in Label Studio. |
| **Recommendation** | **Option C** (character heuristics) + **Option A** (phrase-level) as fallback. Use **Option D** (manual) for gold-standard synthetic data. |

---

### 3.2 Intra-Sentence TTS Switching Artifacts

| Aspect | Details |
|--------|---------|
| **Problem** | XTTS v2 generates one language per call. To produce CS audio, we must: (1) split text into language spans, (2) synthesize each span separately, (3) concatenate audio. This introduces audible discontinuities: pitch jumps, timing mismatches, unnatural pauses, or abrupt prosody changes at boundaries. |
| **Impact** | Synthetic CS audio sounds robotic and unnatural, unlike real CS speakers who smoothly blend languages. |
| **Proposed Solutions** | |
| Option A | **Crossfade Stitching**: Apply 50-100ms crossfade at boundaries to smooth transitions. Simple but doesn't fix prosody mismatches. |
| Option B | **Prosody Conditioning**: Extract F0 (pitch) and duration from the previous span's last phoneme, use it to condition the next span's first phoneme. Requires model modification. |
| Option C | **End-to-End CS TTS Model**: Train or fine-tune a TTS model that natively handles CS input (e.g., fine-tune XTTS on real CS data). This is the "correct" solution but requires significant effort. |
| Option D | **Voice Cloning Consistency**: Use the same voice prompt for all spans in a sentence to maintain speaker consistency. Still has prosody issues but reduces voice mismatch. |
| **Recommendation** | Short-term: **Option A** (crossfade) + **Option D** (consistent voice). Long-term: Explore **Option C** (CS-native TTS). |

---

### 3.3 TTS Model Availability and Access

| Aspect | Details |
|--------|---------|
| **Problem** | High-quality CS-capable TTS models have limited availability: (1) **VALL-E X** is a research paper from Microsoft with no official open-source release; unofficial implementations lack Vietnamese support. (2) **F5-TTS** is a promising diffusion-based model with excellent zero-shot voice cloning and potential CS capabilities, but we currently **do not have access** to the model weights. |
| **Impact** | Cannot reliably use VALL-E X or F5-TTS as proposed. Limited to XTTS v2 and MMS-TTS, which have CS stitching limitations. |
| **Proposed Solutions** | |
| Option A | **Drop VALL-E X, Use XTTS v2 Only**: Focus solely on XTTS v2, which has official support and active maintenance. Accept CS stitching artifacts. |
| Option B | **Substitute with MMS-TTS**: Meta's Massively Multilingual Speech TTS supports Vietnamese (`vie`) and English (`eng`). Simpler API, consistent quality, but less expressive than XTTS. |
| Option C | **Contact F5-TTS Authors**: Email the research team to request model access for academic/research use. F5-TTS's flow-matching approach may handle CS better than autoregressive models. |
| Option D | **Fine-tune F5-TTS on YouTube Data**: If base F5-TTS becomes available (or using open checkpoints), fine-tune on our segmented YouTube CS audio to create a Vietnamese-English CS-native TTS. Requires significant compute and aligned data. |
| Option E | **Abandon Text-First Pipeline**: If TTS quality is insufficient, **drop Substack ingestion entirely** and focus only on YouTube (Audio-First pipeline). Avoids TTS complexity at the cost of losing text-sourced CS data diversity. |
| **Recommendation** | Short-term: **Option A** (XTTS v2) + **Option B** (MMS fallback). Parallel: Pursue **Option C** (contact F5-TTS authors). Fallback: **Option E** (drop Substack) if TTS proves intractable. |

---

### 3.4 Vietnamese Phoneme Coverage in TTS

| Aspect | Details |
|--------|---------|
| **Problem** | Vietnamese has 6 tones and complex vowel combinations. Some TTS models (especially English-primary ones) have incomplete Vietnamese phoneme coverage, leading to mispronunciations of tonal words or rare diacritics. |
| **Impact** | Synthetic Vietnamese sounds foreign or incorrect, reducing training data quality. |
| **Proposed Solutions** | |
| Option A | **Use ViXTTS**: Community fine-tuned XTTS specifically for Vietnamese. Better phoneme coverage than base XTTS. |
| Option B | **VITS-Based Vietnamese TTS**: Use a dedicated Vietnamese TTS model (e.g., `vietTTS`, `vinai/vits-vi`) for Vietnamese spans, XTTS for English spans. |
| Option C | **Phoneme Normalization**: Pre-process Vietnamese text to normalize rare characters and add explicit tone markers that TTS models handle better. |
| **Recommendation** | **Option B** (dedicated Vietnamese TTS for Vietnamese spans) provides best quality. Evaluate ViXTTS (**Option A**) as a unified alternative. |

---

### 3.5 Speaker Diversity in Synthetic Data

| Aspect | Details |
|--------|---------|
| **Problem** | TTS with a single voice prompt produces monotonous data. Real CS speech has diverse speakers (age, gender, accent, speaking rate). Synthetic data lacking diversity may cause model overfitting to TTS voice characteristics. |
| **Impact** | Models trained on synthetic data may not generalize to real speakers. |
| **Proposed Solutions** | |
| Option A | **Voice Prompt Bank**: Collect 50-100 diverse voice prompts (6-second clips from real Vietnamese-English speakers). Randomly select prompts for each synthesis. |
| Option B | **Voice Augmentation**: Apply pitch shifting, speed variation, and formant modification to synthetic audio to simulate speaker diversity. |
| Option C | **Multi-Model Ensemble**: Use multiple TTS models (XTTS, MMS-TTS, VITS) to generate the same text, creating natural variation. |
| **Recommendation** | **Option A** (voice bank) is most realistic. Supplement with **Option B** (augmentation) for further diversity. |

---

### 3.6 Text Normalization for TTS Input

| Aspect | Details |
|--------|---------|
| **Problem** | CS text from blogs contains: URLs, emails, numbers, dates, abbreviations, emoji, teencode (Vietnamese internet slang). TTS models cannot directly speak these; they need expansion (e.g., "5k" → "năm nghìn", "ASAP" → "as soon as possible"). |
| **Impact** | TTS produces garbage audio for unnormalized tokens or speaks them letter-by-letter. |
| **Proposed Solutions** | |
| Option A | **Rule-Based Normalizer**: Build a normalizer with rules for numbers (Vietnamese vs English reading), dates, common abbreviations, URLs (skip or say "link"). |
| Option B | **Leverage text_utils.py**: Extend existing `normalize_text()` to handle TTS-specific expansions. The teencode dictionary already exists. |
| Option C | **LLM Normalization**: Use an LLM to rewrite text into speakable form. Handles edge cases but slow and expensive. |
| **Recommendation** | **Option B** (extend existing utils) + **Option A** (rule-based) for common patterns. Reserve **Option C** (LLM) for complex edge cases. |

---

## 4. Cross-Cutting Infrastructure Problems

### 4.1 Pipeline Orchestration and Failure Recovery

| Aspect | Details |
|--------|---------|
| **Problem** | Preprocessing involves multiple sequential stages (VAD → MFA → Segment → Enhance → LID → TTS). If one stage fails mid-batch, we need to: (1) identify which samples failed, (2) resume from failure point, (3) avoid reprocessing successful samples. |
| **Impact** | Manual recovery is error-prone and wastes compute. |
| **Proposed Solutions** | |
| Option A | **Database State Machine**: Use existing `processing_state` enum to track each sample's progress. Each script queries for samples in the appropriate input state, processes them, updates state on success. Failures remain in original state for retry. |
| Option B | **DVC Pipeline with Checkpoints**: Use DVC stages with proper `deps` and `outs`. DVC handles caching and skips completed stages. |
| Option C | **Task Queue (Celery/RQ)**: Use a proper task queue for distributed processing. Each sample is a task; failed tasks go to dead-letter queue for retry. |
| **Recommendation** | **Option A** (database state machine) for simplicity—already partially implemented. Add **Option B** (DVC) for batch-level orchestration. |

---

### 4.2 Storage Growth and Data Versioning

| Aspect | Details |
|--------|---------|
| **Problem** | Each preprocessing stage creates new files: aligned TextGrids, segmented audio clips (many small files per video), enhanced audio, synthetic audio. Storage grows multiplicatively. Versioning all artifacts is expensive. |
| **Impact** | Disk space exhaustion. Slow DVC pushes. Difficulty tracking which version of enhanced data was used for training. |
| **Proposed Solutions** | |
| Option A | **Selective DVC Tracking**: Only track final outputs (`data/reviewed/`) with DVC. Intermediate stages are reproducible from raw data + code. |
| Option B | **Compressed Intermediate Storage**: Store segmented audio as compressed archives (`.tar.gz`) rather than loose files. Reduces file count and improves transfer speeds. |
| Option C | **Cloud Tiering**: Move older/intermediate data to cold storage (e.g., S3 Glacier). Keep only active data on hot storage. |
| **Recommendation** | **Option A** (selective tracking) + **Option B** (compressed intermediates). |

---

### 4.3 Compute Resource Management

| Aspect | Details |
|--------|---------|
| **Problem** | Different stages have different compute profiles: MFA is CPU-bound (multi-core), DeepFilterNet is CPU-efficient, Demucs needs GPU, TTS needs GPU. Running everything on one machine is inefficient. |
| **Impact** | Underutilized resources. Slow batch processing. |
| **Proposed Solutions** | |
| Option A | **Stage-Specific Workers**: Deploy CPU workers for MFA/DeepFilterNet, GPU workers for Demucs/TTS. Use task queue to route jobs appropriately. |
| Option B | **Sequential Batch Processing**: Process all samples through CPU stages first, then batch all GPU work together to maximize GPU utilization. |
| Option C | **Cloud Burst**: Run GPU stages on cloud (Lambda Labs, RunPod) only when needed. Keep CPU stages on local/cheap infrastructure. |
| **Recommendation** | Start with **Option B** (sequential batching). Scale to **Option A** (specialized workers) if throughput is insufficient. |

---

### 4.4 Configuration Management

| Aspect | Details |
|--------|---------|
| **Problem** | Preprocessing involves many hyperparameters: VAD threshold, MFA beam width, segment min/max length, SNR threshold for enhancement, LID confidence threshold, TTS voice prompts. These need to be: (1) versioned, (2) reproducible, (3) easily tunable. |
| **Impact** | Experiments are not reproducible. Hard to compare results across different parameter settings. |
| **Proposed Solutions** | |
| Option A | **Config File**: Single `config/preprocessing.yaml` with all parameters. Load at runtime. Version with git. |
| Option B | **Environment Variables**: Use `.env` for deployment-specific settings, config file for algorithm parameters. |
| Option C | **Hydra/OmegaConf**: Use a configuration framework that supports hierarchical configs, overrides, and experiment tracking. |
| **Recommendation** | **Option A** (YAML config) for simplicity. Upgrade to **Option C** (Hydra) if experimentation becomes complex. |

---

### 4.5 Monitoring and Logging

| Aspect | Details |
|--------|---------|
| **Problem** | Long-running preprocessing jobs need observability: progress tracking, error rates, resource utilization, quality metrics (SNR before/after, alignment confidence). |
| **Impact** | Blind spots in pipeline health. Difficult to diagnose issues. |
| **Proposed Solutions** | |
| Option A | **Structured Logging**: Use Python `logging` with JSON formatter. Include sample_id, stage, metrics in every log line. Aggregate with ELK/Loki. |
| Option B | **Database Metrics Table**: Store per-sample metrics (processing time, SNR delta, alignment score) in a `preprocessing_metrics` table. Query for dashboards. |
| Option C | **Progress Bars + Notifications**: Use `tqdm` for local runs, send Slack/Discord webhooks on batch completion or failure. |
| **Recommendation** | **Option A** (structured logging) + **Option B** (database metrics) + **Option C** (tqdm for UX). |

---

## 5. Data Quality & Validation Problems

### 5.1 Segment-Transcript Alignment Validation

| Aspect | Details |
|--------|---------|
| **Problem** | After segmentation, how do we verify that the audio segment actually matches its transcript? MFA can produce alignments that are technically "complete" but semantically wrong (words mapped to wrong audio regions). |
| **Impact** | Garbage training data that looks valid. |
| **Proposed Solutions** | |
| Option A | **ASR Cross-Check**: Run Whisper on each segment, compare ASR output to transcript using WER/CER. Flag segments with high error rate for review. |
| Option B | **Alignment Confidence Scores**: MFA outputs log-likelihood scores. Filter out low-confidence alignments. |
| Option C | **Human Sampling**: Randomly sample 5% of segments for human review in Label Studio. Use error rate to estimate overall quality. |
| **Recommendation** | **Option B** (confidence filtering) as automated gate. **Option A** (ASR cross-check) for flagged samples. **Option C** (human sampling) for validation. |

---

### 5.2 CS Content Verification

| Aspect | Details |
|--------|---------|
| **Problem** | Not all segments contain actual code-switching. Some may be monolingual Vietnamese or English. The pipeline should identify and tag true CS segments vs. monolingual segments. |
| **Impact** | Diluted CS training data if monolingual segments are not filtered or labeled. |
| **Proposed Solutions** | |
| Option A | **Reuse `detect_cs_text()`**: Apply existing CS detection from `text_utils.py` to segment transcripts. Tag each segment with `is_cs: true/false`. |
| Option B | **CS Ratio Threshold**: Compute CS ratio (Vietnamese/English word mix) per segment. Only label as CS if ratio is between 10%-90% (true mix, not occasional loanword). |
| Option C | **Separate Datasets**: Split segments into `cs_samples`, `vi_samples`, `en_samples` tables/folders for different training objectives. |
| **Recommendation** | **Option A** + **Option B** (detect + threshold) to tag segments. Consider **Option C** if training separate models. |

---

### 5.3 Audio Quality Metrics

| Aspect | Details |
|--------|---------|
| **Problem** | We need objective measures of audio quality to: (1) decide if enhancement is needed, (2) verify enhancement improved quality, (3) filter out unsalvageable samples. Metrics: SNR, PESQ, STOI, clipping ratio. |
| **Impact** | Cannot make data-driven decisions about audio processing. |
| **Proposed Solutions** | |
| Option A | **SNR Estimation**: Use `waveform_analysis` or `pyloudnorm` to estimate SNR. Store in `audio_meta.snr_db`. |
| Option B | **PESQ/STOI (Reference-Based)**: These require clean reference audio, which we don't have for real data. Only usable for synthetic data quality. |
| Option C | **DNSMOS (Non-Intrusive)**: Microsoft's DNSMOS predicts MOS score without reference. Good for real data. |
| **Recommendation** | **Option A** (SNR) for all audio. **Option C** (DNSMOS) for quality scoring. Reserve **Option B** for synthetic data validation. |

---

### 5.4 Handling Profanity, Sensitive Content

| Aspect | Details |
|--------|---------|
| **Problem** | Vietnamese vlogs may contain profanity, sensitive topics, or copyrighted music. These need to be flagged for review or exclusion depending on intended use of the model. |
| **Impact** | Legal/ethical issues with training data. |
| **Proposed Solutions** | |
| Option A | **Keyword Filter**: Maintain a list of profanity/sensitive keywords in Vietnamese and English. Flag segments containing matches. |
| Option B | **Content Classification Model**: Use a text classifier to detect sensitive content categories. |
| Option C | **Manual Review Tags**: Add `content_warning` field to samples. Populate during Label Studio review. |
| **Recommendation** | **Option A** (keyword filter) for automated flagging. **Option C** (manual tags) for nuanced cases. |

---

## 6. Additional Workflow Problems

### 6.1 Data Licensing and Copyright

| Aspect | Details |
|--------|---------|
| **Problem** | YouTube videos and Substack articles are copyrighted content. Using them for model training may violate terms of service or copyright law depending on jurisdiction and intended use (research vs. commercial). |
| **Impact** | Legal risk. Inability to release trained models or datasets publicly. |
| **Proposed Solutions** | |
| Option A | **Research-Only Use**: Restrict dataset and models to internal research. Do not publish dataset; only publish model trained on it with appropriate disclaimers. |
| Option B | **Fair Use Documentation**: Document that usage falls under fair use/research exemption. Keep records of sources for potential takedown requests. |
| Option C | **Seek Explicit Permission**: For high-value channels, contact creators for permission to use their content. |
| Option D | **Synthetic-Only Public Release**: Train on real data, but only release models fine-tuned on fully synthetic data for public use. |
| **Recommendation** | **Option A** (research-only) + **Option B** (fair use docs). Consider **Option D** for any public release. |

---

### 6.2 YouTube API Rate Limits and Account Bans

| Aspect | Details |
|--------|---------|
| **Problem** | Bulk downloading videos with `yt-dlp` and transcripts with `youtube-transcript-api` can trigger rate limiting or account/IP bans from YouTube. This disrupts data collection and may permanently block access. |
| **Impact** | Data collection halts. Need to rotate IPs or wait for cooldown. |
| **Proposed Solutions** | |
| Option A | **Throttling**: Add random delays (5-30s) between downloads. Limit to 50-100 videos per day per IP. |
| Option B | **Proxy Rotation**: Use rotating residential proxies to distribute requests across IPs. |
| Option C | **Batch Scheduling**: Download in small batches overnight during off-peak hours. |
| Option D | **Archive.org Fallback**: Check if target videos exist on Internet Archive before hitting YouTube. |
| **Recommendation** | **Option A** (throttling) + **Option C** (batch scheduling) for sustainable collection. |

---

### 6.3 Model Dependency Version Conflicts

| Aspect | Details |
|--------|---------|
| **Problem** | The preprocessing pipeline uses multiple ML models (Whisper, MFA, DeepFilterNet, Demucs, XTTS, pyannote) with conflicting dependencies. For example, XTTS requires specific PyTorch versions; MFA requires Conda; pyannote requires `pyannote.audio` with its own dependency tree. |
| **Impact** | Dependency hell. Installation failures. Runtime errors from version mismatches. |
| **Proposed Solutions** | |
| Option A | **Separate Virtual Environments**: Use different venvs/conda envs for each tool. Orchestrate via subprocess calls. |
| Option B | **Containerization**: Create separate Docker containers for each tool. Pipeline calls containers via CLI or API. |
| Option C | **Careful Pinning**: Exhaustively test compatible versions and pin in `requirements.txt`. May not always be possible. |
| Option D | **Microservice Architecture**: Deploy heavy models (TTS, Demucs) as separate services with REST APIs. Main pipeline calls APIs. |
| **Recommendation** | **Option B** (Docker containers) for isolation. Start with **Option A** (separate envs) for local development. |

---

### 6.4 Transcript Language Mismatch

| Aspect | Details |
|--------|---------|
| **Problem** | YouTube transcript language metadata can be wrong. A video marked as "Vietnamese" transcript may actually be in English, or vice versa. Auto-translated transcripts are especially unreliable. |
| **Impact** | Wrong transcript language breaks downstream processing (MFA dictionary selection, LID assumptions). |
| **Proposed Solutions** | |
| Option A | **LID Verification**: Run language detection on the full transcript text. If detected language differs from metadata, flag for review or reassign. |
| Option B | **Prefer Manual Over Auto**: Already implemented—prioritize manual captions. Auto-generated captions are more likely to have language issues. |
| Option C | **Multi-Language Detection**: For CS content, expect mixed results from LID. Accept if LID returns both `vi` and `en` with significant confidence. |
| **Recommendation** | **Option A** (LID verify) + **Option B** (prefer manual). |

---

### 6.5 Audio-Transcript Temporal Alignment for Long Videos

| Aspect | Details |
|--------|---------|
| **Problem** | For videos >30 minutes, cumulative drift between audio and transcript timestamps can exceed 5-10 seconds by the end. MFA may fail to recover from such large offsets. |
| **Impact** | Later portions of long videos have unusable alignments. |
| **Proposed Solutions** | |
| Option A | **Anchor Point Detection**: Identify clear alignment anchors (e.g., chapter markers, scene changes, distinct phrases) and re-sync at these points. |
| Option B | **Sliding Window Alignment**: Process in 2-3 minute windows with overlap. Stitch results, using overlap to detect and correct drift. |
| Option C | **Limit Video Length**: Only process videos <20 minutes where drift is manageable. Skip or split longer videos. |
| **Recommendation** | **Option B** (sliding window) is most robust. Apply **Option C** (length limit) as initial filter. |

---

### 6.6 Handling Incomplete or Corrupted Downloads

| Aspect | Details |
|--------|---------|
| **Problem** | Network interruptions can leave partial audio files or truncated transcripts. These corrupt files may not fail obviously—they might load but have missing data at the end. |
| **Impact** | Silent data corruption. Downstream processing produces incorrect results without error. |
| **Proposed Solutions** | |
| Option A | **Checksum Validation**: After download, verify file integrity (check audio duration matches metadata, transcript segment count is reasonable). |
| Option B | **Re-download on Mismatch**: If validation fails, delete and re-download with retry logic. |
| Option C | **Quarantine Directory**: Move suspicious files to a quarantine folder for manual review rather than processing them. |
| **Recommendation** | **Option A** (validation) + **Option B** (retry) + **Option C** (quarantine) for defense in depth. |

---

### 6.7 Teencode and Slang Evolution

| Aspect | Details |
|--------|---------|
| **Problem** | Vietnamese internet slang (teencode) evolves rapidly. The static `teencode.txt` dictionary will become outdated. New slang terms won't be normalized, affecting TTS pronunciation and text consistency. |
| **Impact** | Degraded text normalization over time. TTS mispronounces new slang. |
| **Proposed Solutions** | |
| Option A | **Periodic Dictionary Updates**: Schedule quarterly reviews of teencode dictionary. Add new terms from recent data. |
| Option B | **Crowdsourced Updates**: Allow annotators in Label Studio to flag unknown slang terms. Batch add to dictionary. |
| Option C | **LLM-Based Normalization**: Use an LLM to detect and expand unknown slang contextually. More robust to new terms but slower. |
| **Recommendation** | **Option B** (crowdsourced) for ongoing maintenance. **Option A** (periodic review) as baseline. |

---

### 6.8 Voice Prompt Quality for TTS

| Aspect | Details |
|--------|---------|
| **Problem** | XTTS v2 voice cloning requires a 6-second clean audio prompt. If prompts are noisy, have background music, or contain multiple speakers, the cloned voice quality degrades significantly. |
| **Impact** | Synthetic audio has artifacts, wrong speaker characteristics, or unintelligible output. |
| **Proposed Solutions** | |
| Option A | **Curated Prompt Bank**: Manually select and validate high-quality 6-second clips from our YouTube data. Filter for: single speaker, low noise, clear speech. |
| Option B | **Enhancement Before Prompting**: Run DeepFilterNet on candidate prompts before using them for voice cloning. |
| Option C | **Synthetic Prompt Verification**: Generate a test phrase with each prompt, manually verify quality before adding to bank. |
| **Recommendation** | **Option A** (curated bank) + **Option C** (verification) for quality assurance. |

---

### 6.9 GPU Memory Management for Batch Processing

| Aspect | Details |
|--------|---------|
| **Problem** | Models like XTTS, Demucs, and Whisper have high GPU memory requirements (8-16GB). Processing long audio files or large batches causes OOM errors. Memory leaks from repeated model loads can accumulate. |
| **Impact** | Crashes mid-batch. Wasted compute time. |
| **Proposed Solutions** | |
| Option A | **Chunk Long Audio**: Split audio >30s into smaller chunks for GPU processing. Concatenate results. |
| Option B | **Explicit Memory Management**: Call `torch.cuda.empty_cache()` between batches. Use context managers to ensure model unloading. |
| Option C | **Process Isolation**: Run each GPU task in a subprocess that terminates after completion, ensuring full memory release. |
| Option D | **Batch Size Tuning**: Dynamically adjust batch size based on available GPU memory. |
| **Recommendation** | **Option A** (chunking) + **Option B** (cache clearing) + **Option C** (subprocess isolation for long-running jobs). |

---

### 6.10 Reproducibility of Preprocessing Results

| Aspect | Details |
|--------|---------|
| **Problem** | Some preprocessing steps have non-deterministic behavior: VAD thresholds can produce slightly different segments on re-runs, TTS generation varies with random seeds, model inference can differ across GPU architectures. |
| **Impact** | Cannot exactly reproduce a dataset. Experiments are not fully repeatable. |
| **Proposed Solutions** | |
| Option A | **Fixed Random Seeds**: Set `torch.manual_seed()`, `numpy.random.seed()`, etc., for all stochastic operations. Document seeds in metadata. |
| Option B | **Snapshot Outputs**: Store preprocessing outputs with DVC. Re-run only regenerates if code/config changes, not on every run. |
| Option C | **Hash-Based Caching**: Hash inputs + config; if hash matches cached result, skip reprocessing. |
| **Recommendation** | **Option A** (fixed seeds) + **Option B** (DVC snapshots) for reproducibility. |

---

## 7. Decision Matrix

Summary of key decisions to make before implementation:

| Decision | Options | Effort | Quality Impact | Recommendation |
|----------|---------|--------|----------------|----------------|
| MFA Dictionary Strategy | Merged / Two-Pass / Hybrid | Med / Low / High | High / Med / High | Start Two-Pass |
| Transcript-less Videos | VAD / Whisper+MFA / Skip | Low / Med / None | Low / High / None | Whisper+MFA |
| Enhancement Routing | SNR-adaptive / Always / Never | Med / Low / None | High / Med / Low | SNR-adaptive |
| Demucs Usage | Music-detect / Category-tag / Always | Med / Low / High | High / Med / Low | Music-detect |
| LID Tagging | Word / Phrase / Manual | Low / Med / High | Low / Med / High | Phrase + heuristics |
| TTS Stitching | Crossfade / Prosody / E2E CS | Low / High / VHigh | Low / High / VHigh | Crossfade short-term |
| TTS Model | XTTS / MMS / F5-TTS / Drop Substack | Low / Low / High / None | Med / Med / High / N/A | XTTS + MMS; pursue F5-TTS |
| **Substack Pipeline** | **Keep / Drop / Defer** | **High / None / Low** | **Med / None / None** | **Defer until TTS solved** |
| Pipeline Orchestration | DB State / DVC / Task Queue | Low / Med / High | - | DB State + DVC |
| Validation | ASR check / Confidence / Human | Med / Low / High | High / Med / VHigh | All three layered |
| Dependency Management | Separate envs / Docker / Pin | Med / High / Low | - | Docker for isolation |
| Data Licensing | Research-only / Fair use / Permission | Low / Low / High | - | Research-only + docs |

---

## 8. Next Steps

1. **Team Review**: Discuss this document and mark decisions in the matrix.
2. **Priority Ordering**: Decide which problems to solve in v1 vs. defer to v2.
3. **Critical Decision: Substack Pipeline**: Decide whether to keep, drop, or defer the Text-First (Substack → TTS) pipeline based on TTS model availability.
4. **F5-TTS Outreach**: If pursuing TTS, email F5-TTS authors for model access in parallel with other work.
5. **Spike/POC**: For uncertain areas (MFA+CS, TTS stitching quality), run small experiments before full implementation.
6. **Schema Updates**: Add any new fields identified (e.g., `alignment_confidence`, `snr_db`, `is_cs`, `content_warning`) to `02_schema_v2.sql`.
7. **Dependency Audit**: Test dependency compatibility for MFA + Whisper + XTTS stack. Document working versions or containerization strategy.
8. **Implementation**: Proceed with `src/preprocessing/` module creation per the agreed plan.

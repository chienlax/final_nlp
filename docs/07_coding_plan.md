# **Comprehensive Coding Implementation Plan**

---

### **Phase 1: Environment & Data Infrastructure**
*Goal: Create a unified data pipeline that feeds identical Train/Test splits to all 3 architectures.*

* [ ] **1. Environment Setup (`training/requirements.txt`)**
    * Core: `torch`, `torchaudio`, `transformers`, `datasets`, `accelerate`.
    * Audio: `librosa`, `soundfile`.
    * Metrics: `jiwer` (for WER), `sacrebleu` (for BLEU), `evaluate`.
* [ ] **2. Data Splitter Utility (`training/utils/split_data.py`)**
    * **Input:** `data/export/manifest.tsv`.
    * **Logic:**
        * Read TSV into Pandas.
        * **Crucial:** Group by `video_id` before splitting (80% Train / 10% Dev / 10% Test). This ensures no speaker overlap between sets.
        * **Path Normalization:** Convert Windows paths (`export\video_3\...`) to Linux/Python friendly paths (`data/export/video_3/...`).
    * **Output:** `data/splits/train.csv`, `data/splits/dev.csv`, `data/splits/test.csv`.
* [ ] **3. Universal Dataset Class (`training/data/dataset.py`)**
    * **Class:** `VietEngDataset(Dataset)`.
    * **Inputs:** CSV path, `audio_root` (path to `data/`), `processor` (HuggingFace processor).
    * **Logic:**
        * Load audio via `torchaudio`.
        * **Resample:** Force 16,000Hz (Required for Wav2Vec2 & Whisper).
        * Return dict: `{'input_values': audio_array, 'transcript': text, 'translation': text}`.

---

### **Phase 2: The Core Architecture Definition**
*Goal: Define the "Wav2Vec2 + mBART" class once, to be reused by both Cascade ASR and E2E Shared models.*

* [ ] **4. Model Wrapper (`training/models/w2v2_mbart.py`)**
    * **Class:** `Wav2Vec2MBartForConditionalGeneration`.
    * **Implementation:** Use HuggingFace's `SpeechEncoderDecoderModel`.
    * **Config:**
        * Encoder: `facebook/wav2vec2-large-xlsr-53`.
        * Decoder: `facebook/mbart-large-50`.
        * Settings: `encoder.add_adapter=True` (This mimics the "bridge" layer mentioned in the paper to align audio/text dimensions).
    * **Tokenizer Setup:**
        * Define special tokens: `<2transcribe>`, `<2translate>`.
        * Resize token embeddings to fit these new tokens.

---

### **Phase 3: Model A - Cascade System (The Baseline)**
*Goal: Train two specialized models independently.*

* [ ] **5. Train ASR Component (`training/cascade/train_asr.py`)**
    * **Model:** `Wav2Vec2MBartForConditionalGeneration` (from Step 4).
    * **Data:** Source = Audio, Target = Transcript.
    * **Prompting:** Force the decoder to start with `<2transcribe>`.
    * **Metric:** WER (Word Error Rate).
* [ ] **6. Train MT Component (`training/cascade/train_mt.py`)**
    * **Model:** Standard `MBartForConditionalGeneration` (Use `facebook/mbart-large-50-many-to-many-mmt`).
    * **Data:** Source = Transcript, Target = Translation.
    * **Metric:** BLEU.
* [ ] **7. Cascade Inference Script (`training/cascade/evaluate.py`)**
    * **Logic:**
        1.  Pass Audio into **ASR Model** $\rightarrow$ Get `Hypothesis_Transcript`.
        2.  Pass `Hypothesis_Transcript` into **MT Model** $\rightarrow$ Get `Final_Translation`.
    * *Note:* This measures the "Error Propagation" effect mentioned in the paper.

---

### **Phase 4: Model B - E2E Bidirectional Shared**
*Goal: Train the unified model to multitask.*

* [ ] **8. Multitask Data Collator (`training/e2e/collator.py`)**
    * **Logic:** This is the "magic" step. For every batch of $N$ audio samples, generate $2N$ training examples:
        * **Task A (ASR):** Audio + Decoder Prompt `<2transcribe>` $\rightarrow$ Label: `transcript`.
        * **Task B (ST):** Audio + Decoder Prompt `<2translate>` $\rightarrow$ Label: `translation`.
* [ ] **9. Train Shared Model (`training/e2e/train_shared.py`)**
    * **Model:** Same `Wav2Vec2MBartForConditionalGeneration` class.
    * **Difference:** Uses the Multitask Collator. The model sees the exact same audio twice but learns to output different text based on the start token.
    * **Metric:** Compute both WER (on ASR task) and BLEU (on ST task).

---

### **Phase 5: Model C - SOTA Benchmark (Whisper)**
*Goal: Fine-tune Whisper as the modern "Gold Standard".*

* [ ] **10. Train Whisper (`training/whisper/train.py`)**
    * **Model:** `openai/whisper-small` (or `medium` if GPU allows).
    * **Config:** Use `Seq2SeqTrainer`.
    * **Task Logic:** Whisper handles this natively.
        * Set `task="transcribe"` for ASR samples.
        * Set `task="translate"` for ST samples.
    * **Data:** You can reuse the Multitask Collator logic (Step 8) but adapted for Whisper's specific token format (`<|startoftranscript|><|vi|><|transcribe|>`).

---

### **Phase 6: Evaluation & Reporting**
*Goal: Generate the tables and charts for your academic report.*

* [ ] **11. Benchmark Runner (`training/analysis/benchmark.py`)**
    * Load `test.csv`.
    * Run all 3 models on the exact same test set.
    * **Output:** `results/predictions.csv` with columns:
        * `audio_id`
        * `ref_transcript`, `ref_translation`
        * `cascade_transcript`, `cascade_translation`
        * `e2e_transcript`, `e2e_translation`
        * `whisper_transcript`, `whisper_translation`
* [ ] **12. Metrics & Charting (`training/analysis/visualize.py`)**
    * Calculate Aggregate Scores:
        * **ASR Quality:** WER / CER.
        * **Translation Quality:** BLEU / CHRF.
    * **Latency Analysis:** Measure average inference time per second of audio.
    * Generate `model_comparison.png` (Bar chart).

This plan covers the entire academic requirement: **Implementation** (Custom E2E), **Baseline** (Cascade), and **SOTA** (Whisper), ensuring you have strong "Results" to discuss in your report.
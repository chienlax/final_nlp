# Model Training Guide

**Version**: 1.0  
**Last Updated**: 2025-12-13

---

## Overview

Two-architecture training pipeline for Vietnamese-English Code-Switching Speech Translation:

| Architecture | Model | Target WER | Target BLEU |
|--------------|-------|------------|-------------|
| **Whisper** | openai/whisper-tiny (dev) / medium (prod) | < 15% | N/A |
| **E2E** | wav2vec2 + mBART | < 15% | > 25 |

---

## Training Modes

| Mode | GPU | Data | Duration | Config |
|------|-----|------|----------|--------|
| **Development** | RTX 2050 (4GB) | 25 min test set | ~30 min | `dev_*.yaml` |
| **Production** | H100 (80GB) | 40-50 hours | ~3.5 hours | `prod_*.yaml` |

---

## Quick Start

### Development (Local GPU)

```powershell
# From project root
training\run_dev.bat
```

### Production (Cloud GPU)

```bash
# Linux (H100)
./training/run_prod.sh
```

---

## Pipeline Steps

The training scripts execute these steps automatically:

```
[1/6] Install dependencies (PyTorch + CUDA)
[2/6] Split data (train/val/test)
[3/6] Train Whisper (ASR + ST multitask)
[4/6] Train E2E (wav2vec2 → mBART)
[5/6] Evaluate on test set (WER, BLEU)
[6/6] Generate charts
```

---

## Data Preparation

### Export from Annotation System

Approved segments are exported via:
```powershell
python -m backend.operations.exporter --all
```

Output: `data/export/manifest.tsv`

### Split into Train/Val/Test

```powershell
python training/data/split_data.py \
    --manifest data/export/manifest.tsv \
    --output_dir data/splits
```

**Default Split**: 80% train / 10% val / 10% test

---

## Configuration

All training configs are in `training/configs/`:

| Config | GPU | Model | Batch Size |
|--------|-----|-------|------------|
| `dev_whisper.yaml` | 4GB | whisper-tiny | 1 (acc=4) |
| `dev_e2e.yaml` | 4GB | wav2vec2-base + mbart | 1 (acc=4) |
| `prod_whisper.yaml` | 80GB | whisper-medium | 16 |
| `prod_e2e.yaml` | 80GB | wav2vec2-xlsr + mbart | 8 |

### Key Config Options

```yaml
model:
  name: "openai/whisper-tiny"
  type: "whisper"
  language: "vi"
  task: "both"  # ASR + ST multitask

training:
  batch_size: 1
  gradient_accumulation_steps: 4
  learning_rate: 1.0e-4
  num_train_epochs: 2
  fp16: true
  gradient_checkpointing: true  # Essential for low VRAM

output:
  dir: "training/outputs/dev_whisper"
```

---

## Outputs

After training completes:

```
training/outputs/
├── dev_whisper/          # Whisper checkpoints
│   └── checkpoint-*/
├── dev_e2e/              # E2E checkpoints
├── results/              # Metrics (JSON)
│   ├── whisper_metrics.json
│   └── e2e_metrics.json
└── charts/               # Visualizations (PNG)
    ├── training_loss.png
    ├── wer_comparison.png
    └── bleu_comparison.png
```

---

## Evaluation Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **WER** | Word Error Rate (ASR) | < 15% |
| **BLEU** | Translation quality | > 25 |

Run evaluation manually:

```powershell
python training/scripts/run_evaluation.py \
    --model_dir training/outputs/dev_whisper \
    --model_type whisper \
    --output training/outputs/results
```

---

## Dependencies

Training uses a **separate virtual environment** to avoid conflicts with the annotation backend.

Location: `%USERPROFILE%\.training_venvs\final_nlp`

Key packages:
- PyTorch + CUDA 12.4
- transformers, datasets, accelerate
- jiwer (WER), sacrebleu (BLEU)
- matplotlib, seaborn (charts)

---

## Directory Structure

```
training/
├── configs/              # YAML training configs
│   ├── base.yaml
│   ├── dev_whisper.yaml
│   ├── dev_e2e.yaml
│   ├── prod_whisper.yaml
│   └── prod_e2e.yaml
├── scripts/              # Main scripts
│   ├── train.py          # Training loop
│   ├── run_evaluation.py # Metrics calculation
│   └── export_charts.py  # Visualization
├── data/                 # Dataset utilities
│   ├── dataset.py        # Dataset class
│   ├── collator.py       # Data collation
│   └── split_data.py     # Train/val/test split
├── models/               # Model wrappers
├── utils/                # Helpers
├── run_dev.bat           # Windows dev script
├── run_dev.sh            # Linux dev script
├── run_prod.bat          # Windows prod script
└── run_prod.sh           # Linux prod script
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| CUDA out of memory | Reduce `batch_size`, enable `gradient_checkpointing` |
| Slow training | Increase `num_workers` in dataloader config |
| Import errors | Reinstall venv: delete `%USERPROFILE%\.training_venvs` and re-run |
| Permission denied (pip) | Use `--no-cache-dir` flag (already set in scripts) |

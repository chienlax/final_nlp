#!/bin/bash
# =============================================================================
# Development Training Pipeline - Linux (Fully Self-Contained)
# =============================================================================
# GPU: RTX 2050 (4GB) or similar low-VRAM GPU
# Data: 25 min test set (227 segments)
# Models: whisper-tiny, wav2vec2-base + mbart-large
#
# This script creates its own isolated virtual environment in training/.venv/
# Run from: final_nlp folder (project root)
# =============================================================================

set -e  # Exit on error

echo "=========================================="
echo "  Development Training Pipeline (Linux)  "
echo "=========================================="
echo ""

# Change to project root (script is in training/, so go up one level)
cd "$(dirname "$0")/.."
echo "[INFO] Working directory: $(pwd)"

# =============================================================================
# ENVIRONMENT SETUP - Creates isolated training/.venv if not exists
# =============================================================================

VENV_DIR="training/.venv"
REQUIREMENTS_FLAG="training/.requirements_installed"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "[SETUP] Creating isolated training environment..."
    python3 -m venv "$VENV_DIR"
    echo "[SETUP] Virtual environment created: $VENV_DIR"
    # Delete requirements flag to force reinstall
    rm -f "$REQUIREMENTS_FLAG"
fi

# Activate the training virtual environment
echo "[SETUP] Activating training environment..."
source "$VENV_DIR/bin/activate"

# Verify we're using the right Python
echo ""
echo "[INFO] Python: $(python --version)"
echo "[INFO] Python path: $(which python)"

# =============================================================================
# DEPENDENCY INSTALLATION
# =============================================================================

if [ ! -f "$REQUIREMENTS_FLAG" ]; then
    echo ""
    echo "[1/6] Installing dependencies..."
    
    echo "[1/6a] Upgrading pip..."
    python -m pip install --upgrade pip -q
    
    echo "[1/6b] Installing PyTorch with CUDA 12.4..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 -q
    
    echo "[1/6c] Installing remaining dependencies..."
    pip install -r training/requirements.txt -q
    
    touch "$REQUIREMENTS_FLAG"
    echo "[1/6] Dependencies installed successfully!"
else
    echo "[1/6] Dependencies already installed"
fi

# Verify PyTorch installation
echo ""
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}')"

# =============================================================================
# DATA PREPARATION
# =============================================================================

if [ ! -f "data/splits/train.csv" ]; then
    echo ""
    echo "[2/6] Splitting data..."
    python training/data/split_data.py --manifest data/export/manifest.tsv --output_dir data/splits
else
    echo "[2/6] Data already split"
fi

# =============================================================================
# TRAINING
# =============================================================================

# Train Whisper
echo ""
echo "[3/6] Training Whisper (tiny) - Est: 10 min"
echo "----------------------------------------"
python training/scripts/train.py --config training/configs/dev_whisper.yaml

# Train E2E
echo ""
echo "[4/6] Training E2E Model - Est: 20 min"
echo "----------------------------------------"
python training/scripts/train.py --config training/configs/dev_e2e.yaml

# =============================================================================
# EVALUATION
# =============================================================================

echo ""
echo "[5/6] Evaluating models..."
echo "----------------------------------------"
python training/scripts/run_evaluation.py \
    --model_dir training/outputs/dev_whisper \
    --model_type whisper \
    --output training/outputs/results

python training/scripts/run_evaluation.py \
    --model_dir training/outputs/dev_e2e \
    --model_type e2e \
    --output training/outputs/results

# Generate charts
echo ""
echo "[6/6] Generating charts..."
echo "----------------------------------------"
python training/scripts/export_charts.py \
    --results_dir training/outputs/results \
    --output training/outputs/charts \
    --dpi 300

# =============================================================================
# COMPLETE
# =============================================================================

echo ""
echo "=========================================="
echo "  DEVELOPMENT PIPELINE COMPLETE!         "
echo "=========================================="
echo ""
echo "Outputs:"
echo "  - Checkpoints: training/outputs/dev_whisper/"
echo "                 training/outputs/dev_e2e/"
echo "  - Metrics:     training/outputs/results/"
echo "  - Charts:      training/outputs/charts/"
echo ""

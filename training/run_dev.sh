#!/bin/bash
# =============================================================================
# Development Training Pipeline - Linux
# =============================================================================
# GPU: RTX 2050 (4GB) or similar low-VRAM GPU
# Data: 25 min test set (227 segments)
# Models: whisper-tiny, wav2vec2-base + mbart-large
# =============================================================================

set -e  # Exit on error

echo "=========================================="
echo "  Development Training Pipeline (Linux)  "
echo "=========================================="
echo ""

# Change to project root
cd "$(dirname "$0")/.."

# Check if virtual environment exists
if [ -d ".venv" ]; then
    echo "[SETUP] Activating virtual environment..."
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "[WARNING] No virtual environment found, using system Python"
fi

# Check Python and GPU
echo ""
echo "[INFO] Python: $(python --version)"
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}')"

# Install requirements if needed
if [ ! -f "training/.requirements_installed" ]; then
    echo ""
    echo "[1/6] Installing requirements..."
    pip install -r training/requirements.txt -q
    touch training/.requirements_installed
else
    echo "[1/6] Requirements already installed"
fi

# Split data if needed
if [ ! -f "data/splits/train.csv" ]; then
    echo ""
    echo "[2/6] Splitting data..."
    python training/data/split_data.py --manifest data/export/manifest.tsv --output_dir data/splits
else
    echo "[2/6] Data already split"
fi

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

# Evaluate models
echo ""
echo "[5/6] Evaluating models..."
echo "----------------------------------------"
python training/scripts/evaluate.py \
    --model_dir training/outputs/dev_whisper \
    --model_type whisper \
    --output training/outputs/results

python training/scripts/evaluate.py \
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

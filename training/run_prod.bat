@echo off
REM =============================================================================
REM Production Training Pipeline - Windows (H100 SXM 80GB) - Fully Self-Contained
REM =============================================================================
REM GPU: H100 SXM (80GB VRAM)
REM CPU: AMD EPYC 9554 64-core
REM Data: 40-50 hours audio
REM Models: whisper-medium, wav2vec2-large-xlsr + mbart-large
REM Budget: 6-7 hours (target: 3.5 hours)
REM
REM This script creates its own isolated virtual environment in training/.venv/
REM Run from: final_nlp folder (project root)
REM =============================================================================

echo ==========================================
echo   Production Training Pipeline (H100)
echo ==========================================
echo.

REM Record start time
set START_TIME=%TIME%

REM Change to project root (script is in training/, so go up one level)
cd /d "%~dp0\.."
echo [INFO] Working directory: %CD%

REM =============================================================================
REM GPU CHECK
REM =============================================================================

echo [SYSTEM] Checking GPU...
nvidia-smi --query-gpu=name,memory.total --format=csv
echo.

REM =============================================================================
REM ENVIRONMENT SETUP - Creates isolated venv OUTSIDE project to avoid uvicorn conflict
REM =============================================================================

REM Use venv outside project dir (uvicorn --reload watches project, causes conflict)
set VENV_DIR=%USERPROFILE%\.training_venvs\final_nlp
set REQUIREMENTS_FLAG=%VENV_DIR%\.requirements_installed

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo.
    echo [SETUP] Creating isolated training environment...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [SETUP] Virtual environment created: %VENV_DIR%
    REM Delete requirements flag to force reinstall
    if exist "%REQUIREMENTS_FLAG%" del "%REQUIREMENTS_FLAG%"
)

REM Activate the training virtual environment
echo [SETUP] Activating training environment...
call %VENV_DIR%\Scripts\activate.bat

REM Verify we're using the right Python
echo.
echo [INFO] Python:
python --version
echo [INFO] Python path:
where python

REM =============================================================================
REM DEPENDENCY INSTALLATION
REM =============================================================================

echo.
echo [1/6] Installing dependencies...

echo [1/6a] Upgrading pip...
python -m pip install --upgrade pip -q

echo [1/6b] Installing PyTorch with CUDA 12.4...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 -q
if errorlevel 1 (
    echo [ERROR] Failed to install PyTorch!
    pause
    exit /b 1
)

echo [1/6c] Installing remaining dependencies...
pip install -r training\requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install requirements!
    pause
    exit /b 1
)

REM Verify PyTorch installation
echo.
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}'); print(f'[INFO] CUDA Device: {torch.cuda.get_device_name(0)}')"

REM =============================================================================
REM DATA PREPARATION
REM =============================================================================

echo.
echo [2/6] Preparing data...
python training\data\split_data.py --manifest data\export\manifest.tsv --output_dir data\splits

REM =============================================================================
REM TRAINING
REM =============================================================================

REM Train Whisper
echo.
echo ==========================================
echo [3/6] Training Whisper (medium)
echo Estimated time: 50 minutes
echo ==========================================
python training\scripts\train.py --config training\configs\prod_whisper.yaml
if errorlevel 1 goto :error

REM Train E2E
echo.
echo ==========================================
echo [4/6] Training E2E Model (wav2vec2 + mbart)
echo Estimated time: 2 hours
echo ==========================================
python training\scripts\train.py --config training\configs\prod_e2e.yaml
if errorlevel 1 goto :error

REM =============================================================================
REM EVALUATION
REM =============================================================================

echo.
echo [5/6] Evaluating models on test set...
echo ==========================================
python training\scripts\run_evaluation.py --model_dir training\outputs\prod_whisper --model_type whisper --output training\outputs\results
python training\scripts\run_evaluation.py --model_dir training\outputs\prod_e2e --model_type e2e --output training\outputs\results

REM Generate charts
echo.
echo [6/6] Generating high-resolution charts...
echo ==========================================
python training\scripts\export_charts.py --results_dir training\outputs\results --logs_dir training\outputs --output training\outputs\charts --dpi 300

REM =============================================================================
REM COMPLETE
REM =============================================================================

echo.
echo ==========================================
echo   PRODUCTION PIPELINE COMPLETE!
echo ==========================================
echo.
echo Outputs:
echo   - Whisper checkpoint: training\outputs\prod_whisper\
echo   - E2E checkpoint:     training\outputs\prod_e2e\
echo   - Metrics:            training\outputs\results\
echo   - Charts:             training\outputs\charts\
echo.
echo Don't forget to download your checkpoints!
echo.
goto :end

:error
echo.
echo [ERROR] Training failed! Check logs above.
echo.
pause
exit /b 1

:end
echo Start time: %START_TIME%
echo End time:   %TIME%
pause

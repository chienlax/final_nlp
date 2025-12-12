@echo off
REM =============================================================================
REM Production Training Pipeline - Windows (H100 SXM 80GB)
REM =============================================================================
REM GPU: H100 SXM (80GB VRAM)
REM CPU: AMD EPYC 9554 64-core
REM Data: 40-50 hours audio
REM Models: whisper-medium, wav2vec2-large-xlsr + mbart-large
REM Budget: 6-7 hours (target: 3.5 hours)
REM =============================================================================

echo ==========================================
echo   Production Training Pipeline (H100)
echo ==========================================
echo.

REM Record start time
set START_TIME=%TIME%

REM Change to project root
cd /d "%~dp0\.."

REM Verify GPU
echo [SYSTEM] Checking GPU...
nvidia-smi --query-gpu=name,memory.total --format=csv
echo.

REM Check Python and GPU
python --version
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}'); print(f'[INFO] CUDA Device: {torch.cuda.get_device_name(0)}')"

REM Install requirements
echo.
echo [1/6] Installing requirements...
pip install -r training\requirements.txt -q

REM Split data
echo.
echo [2/6] Preparing data...
python training\data\split_data.py --manifest data\export\manifest.tsv --output_dir data\splits

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

REM Evaluate models
echo.
echo [5/6] Evaluating models on test set...
echo ==========================================
python training\scripts\evaluate.py --model_dir training\outputs\prod_whisper --model_type whisper --output training\outputs\results
python training\scripts\evaluate.py --model_dir training\outputs\prod_e2e --model_type e2e --output training\outputs\results

REM Generate charts
echo.
echo [6/6] Generating high-resolution charts...
echo ==========================================
python training\scripts\export_charts.py --results_dir training\outputs\results --logs_dir training\outputs --output training\outputs\charts --dpi 300

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

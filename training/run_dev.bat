@echo off
REM =============================================================================
REM Development Training Pipeline - Windows
REM =============================================================================
REM GPU: RTX 2050 (4GB) or similar low-VRAM GPU
REM Data: 25 min test set (227 segments)
REM Models: whisper-tiny, wav2vec2-base + mbart-large
REM =============================================================================

echo ==========================================
echo   Development Training Pipeline (Windows)
echo ==========================================
echo.

REM Change to project root
cd /d "%~dp0\.."

REM Check if virtual environment exists
if exist ".venv\Scripts\activate.bat" (
    echo [SETUP] Activating virtual environment...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [WARNING] No virtual environment found, using system Python
)

REM Check Python and GPU
echo.
python --version
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}')"

REM Install requirements if needed
if not exist "training\.requirements_installed" (
    echo.
    echo [1/6] Installing requirements...
    pip install -r training\requirements.txt -q
    echo. > training\.requirements_installed
) else (
    echo [1/6] Requirements already installed
)

REM Split data if needed
if not exist "data\splits\train.csv" (
    echo.
    echo [2/6] Splitting data...
    python training\data\split_data.py --manifest data\export\manifest.tsv --output_dir data\splits
) else (
    echo [2/6] Data already split
)

REM Train Whisper
echo.
echo [3/6] Training Whisper (tiny) - Est: 10 min
echo ----------------------------------------
python training\scripts\train.py --config training\configs\dev_whisper.yaml
if errorlevel 1 goto :error

REM Train E2E
echo.
echo [4/6] Training E2E Model - Est: 20 min
echo ----------------------------------------
python training\scripts\train.py --config training\configs\dev_e2e.yaml
if errorlevel 1 goto :error

REM Evaluate models
echo.
echo [5/6] Evaluating models...
echo ----------------------------------------
python training\scripts\evaluate.py --model_dir training\outputs\dev_whisper --model_type whisper --output training\outputs\results
python training\scripts\evaluate.py --model_dir training\outputs\dev_e2e --model_type e2e --output training\outputs\results

REM Generate charts
echo.
echo [6/6] Generating charts...
echo ----------------------------------------
python training\scripts\export_charts.py --results_dir training\outputs\results --output training\outputs\charts --dpi 300

echo.
echo ==========================================
echo   DEVELOPMENT PIPELINE COMPLETE!
echo ==========================================
echo.
echo Outputs:
echo   - Checkpoints: training\outputs\dev_whisper\
echo                  training\outputs\dev_e2e\
echo   - Metrics:     training\outputs\results\
echo   - Charts:      training\outputs\charts\
echo.
goto :end

:error
echo.
echo [ERROR] Training failed! Check logs above.
echo.
pause
exit /b 1

:end
pause

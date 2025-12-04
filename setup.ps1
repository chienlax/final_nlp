# setup.ps1
# ============================================================================
# NLP Pipeline Setup Script
# 
# Comprehensive setup script for the Vietnamese-English CS Speech Translation
# pipeline. This script handles:
#   1. Python virtual environment creation
#   2. Dependency installation
#   3. SQLite database initialization
#   4. Tailscale configuration (optional, for remote access)
#   5. Backup scheduling to Google Drive (optional)
#
# Usage:
#   .\setup.ps1                    # Full setup
#   .\setup.ps1 -SkipTailscale     # Skip Tailscale setup
#   .\setup.ps1 -SkipBackup        # Skip backup scheduling
#   .\setup.ps1 -DevMode           # Development mode (includes extra tools)
#
# Requirements:
#   - Python 3.10+ installed and in PATH
#   - FFmpeg installed (for audio processing)
#   - Git (optional, for version control)
#   - Administrator privileges (for Tailscale installation)
# ============================================================================

param(
    [switch]$SkipTailscale,
    [switch]$SkipBackup,
    [switch]$DevMode,
    [string]$DriveBackupPath = "G:\My Drive\NLP_Backups",
    [string]$PythonVersion = "3.10"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

$VENV_DIR = Join-Path $ScriptDir ".venv"
$DATA_DIR = Join-Path $ScriptDir "data"
$DB_PATH = Join-Path $DATA_DIR "lab_data.db"
$STREAMLIT_PORT = 8501
$BACKUP_SCRIPT_NAME = "backup_db.ps1"
$BACKUP_SCRIPT_PATH = Join-Path $ScriptDir $BACKUP_SCRIPT_NAME
$TASK_NAME = "NLP_DB_Hourly_Backup"

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "=" * 60 -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Message)
    Write-Host "[*] $Message" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Error2 {
    param([string]$Message)
    Write-Host "[-] $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Command {
    param([string]$Command)
    return [bool](Get-Command $Command -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# Prerequisites Check
# ---------------------------------------------------------------------------

function Test-Prerequisites {
    Write-Header "Checking Prerequisites"
    
    $allGood = $true
    
    # Python
    Write-Step "Checking Python..."
    if (Test-Command "python") {
        $pyVersion = python --version 2>&1
        Write-Success "Python found: $pyVersion"
    } else {
        Write-Error2 "Python not found in PATH"
        Write-Info "Install from: https://www.python.org/downloads/"
        $allGood = $false
    }
    
    # FFmpeg
    Write-Step "Checking FFmpeg..."
    if (Test-Command "ffmpeg") {
        $ffVersion = ffmpeg -version 2>&1 | Select-Object -First 1
        Write-Success "FFmpeg found: $ffVersion"
    } else {
        Write-Error2 "FFmpeg not found in PATH"
        Write-Info "Install with: winget install FFmpeg"
        Write-Info "Or download from: https://ffmpeg.org/download.html"
        $allGood = $false
    }
    
    # Git (optional)
    Write-Step "Checking Git..."
    if (Test-Command "git") {
        $gitVersion = git --version 2>&1
        Write-Success "Git found: $gitVersion"
    } else {
        Write-Info "Git not found (optional, but recommended)"
    }
    
    if (-not $allGood) {
        Write-Error2 "Missing prerequisites. Please install them and try again."
        exit 1
    }
    
    Write-Success "All prerequisites met!"
}

# ---------------------------------------------------------------------------
# Python Environment Setup
# ---------------------------------------------------------------------------

function Setup-PythonEnvironment {
    Write-Header "Setting Up Python Environment"
    
    # Create virtual environment
    if (-not (Test-Path $VENV_DIR)) {
        Write-Step "Creating virtual environment..."
        python -m venv $VENV_DIR
        Write-Success "Virtual environment created at: $VENV_DIR"
    } else {
        Write-Success "Virtual environment already exists"
    }
    
    # Activate virtual environment
    Write-Step "Activating virtual environment..."
    $activateScript = Join-Path $VENV_DIR "Scripts\Activate.ps1"
    . $activateScript
    Write-Success "Virtual environment activated"
    
    # Upgrade pip
    Write-Step "Upgrading pip..."
    python -m pip install --upgrade pip --quiet
    
    # Install dependencies
    Write-Step "Installing dependencies from requirements.txt..."
    $requirementsPath = Join-Path $ScriptDir "requirements.txt"
    
    if (Test-Path $requirementsPath) {
        pip install -r $requirementsPath --quiet
        Write-Success "Dependencies installed"
    } else {
        Write-Error2 "requirements.txt not found!"
        exit 1
    }
    
    # Install dev dependencies if in DevMode
    if ($DevMode) {
        Write-Step "Installing development dependencies..."
        pip install ipython jupyter black flake8 pytest --quiet
        Write-Success "Development dependencies installed"
    }
}

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------

function Setup-Database {
    Write-Header "Setting Up SQLite Database"
    
    # Create data directory
    if (-not (Test-Path $DATA_DIR)) {
        Write-Step "Creating data directory..."
        New-Item -ItemType Directory -Path $DATA_DIR -Force | Out-Null
        Write-Success "Data directory created: $DATA_DIR"
    }
    
    # Initialize database using Python
    Write-Step "Initializing SQLite database..."
    
    $initScript = @"
import sys
sys.path.insert(0, 'src')
from db import init_database
from pathlib import Path
init_database(Path('$($DB_PATH -replace '\\', '/')'))
print('Database initialized successfully!')
"@
    
    python -c $initScript
    
    if (Test-Path $DB_PATH) {
        Write-Success "Database created: $DB_PATH"
    } else {
        Write-Error2 "Database creation failed!"
    }
    
    # Create subdirectories
    $subdirs = @("raw", "raw/audio", "denoised", "segments", "export", "review")
    foreach ($subdir in $subdirs) {
        $path = Join-Path $DATA_DIR $subdir
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
    }
    Write-Success "Data subdirectories created"
}

# ---------------------------------------------------------------------------
# Tailscale Setup
# ---------------------------------------------------------------------------

function Setup-Tailscale {
    Write-Header "Tailscale Configuration"
    
    if (-not (Test-Administrator)) {
        Write-Error2 "Administrator privileges required for Tailscale installation."
        Write-Info "Run PowerShell as Administrator or use -SkipTailscale flag."
        return
    }
    
    # Check if Tailscale is installed
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    
    if (-not $tailscale) {
        Write-Step "Installing Tailscale via winget..."
        try {
            winget install --id Tailscale.Tailscale --accept-package-agreements --accept-source-agreements
            Write-Success "Tailscale installed!"
            
            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        } catch {
            Write-Error2 "Tailscale installation failed: $_"
            Write-Info "Install manually from: https://tailscale.com/download"
            return
        }
    } else {
        Write-Success "Tailscale already installed"
    }
    
    # Configure Tailscale Serve
    Write-Step "Configuring Tailscale Serve for Streamlit..."
    
    try {
        # Check if connected
        $status = tailscale status --json 2>$null | ConvertFrom-Json
        
        if (-not $status.Self.Online) {
            Write-Step "Tailscale not connected. Starting login..."
            tailscale up
        }
        
        Write-Success "Tailscale connected!"
        Write-Info "Your Tailscale IP: $($status.Self.TailscaleIPs[0])"
        
        # Configure serve
        tailscale serve reset 2>$null
        tailscale serve https / http://127.0.0.1:$STREAMLIT_PORT
        
        Write-Success "Tailscale Serve configured for port $STREAMLIT_PORT"
        
    } catch {
        Write-Error2 "Tailscale configuration failed: $_"
        Write-Info "Configure manually with: tailscale serve https / http://127.0.0.1:$STREAMLIT_PORT"
    }
}

# ---------------------------------------------------------------------------
# Backup Setup
# ---------------------------------------------------------------------------

function Setup-Backup {
    Write-Header "Backup Configuration"
    
    # Verify Google Drive path
    if (-not (Test-Path $DriveBackupPath)) {
        Write-Step "Creating backup directory: $DriveBackupPath"
        try {
            New-Item -ItemType Directory -Path $DriveBackupPath -Force | Out-Null
            Write-Success "Backup directory created"
        } catch {
            Write-Error2 "Could not create backup directory"
            Write-Info "Ensure Google Drive is installed and mounted"
            return
        }
    }
    
    # Create backup script
    Write-Step "Creating backup script..."
    
    $backupContent = @"
# backup_db.ps1 - Automated SQLite database backup
# Generated by setup.ps1

`$ErrorActionPreference = "Stop"
`$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
`$dbPath = "$DB_PATH"
`$backupDir = "$DriveBackupPath"
`$backupName = "lab_data_`$timestamp.db"

try {
    if (Test-Path `$dbPath) {
        Copy-Item -Path `$dbPath -Destination (Join-Path `$backupDir `$backupName) -Force
        Copy-Item -Path `$dbPath -Destination (Join-Path `$backupDir "lab_data_latest.db") -Force
        Write-Output "[`$(Get-Date)] Backup successful: `$backupName"
        
        # Keep last 24 backups
        Get-ChildItem `$backupDir -Filter "lab_data_*.db" |
            Where-Object { `$_.Name -ne "lab_data_latest.db" } |
            Sort-Object CreationTime -Descending |
            Select-Object -Skip 24 |
            Remove-Item -Force
    } else {
        Write-Output "[`$(Get-Date)] Database not found: `$dbPath"
    }
} catch {
    Write-Output "[`$(Get-Date)] Backup failed: `$_"
}
"@
    
    $backupContent | Out-File -FilePath $BACKUP_SCRIPT_PATH -Encoding UTF8 -Force
    Write-Success "Backup script created: $BACKUP_SCRIPT_PATH"
    
    # Create scheduled task (requires admin)
    if (Test-Administrator) {
        Write-Step "Creating hourly backup task..."
        
        try {
            Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
            
            $action = New-ScheduledTaskAction `
                -Execute "powershell.exe" `
                -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BACKUP_SCRIPT_PATH`""
            
            $trigger = New-ScheduledTaskTrigger `
                -Once `
                -At (Get-Date) `
                -RepetitionInterval (New-TimeSpan -Hours 1)
            
            $settings = New-ScheduledTaskSettingsSet `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -StartWhenAvailable
            
            Register-ScheduledTask `
                -TaskName $TASK_NAME `
                -Action $action `
                -Trigger $trigger `
                -Settings $settings `
                -Description "Hourly backup of NLP project database to Google Drive"
            
            Write-Success "Scheduled task created: $TASK_NAME"
            
            # Run initial backup
            Start-ScheduledTask -TaskName $TASK_NAME
            Write-Success "Initial backup triggered"
            
        } catch {
            Write-Error2 "Failed to create scheduled task: $_"
            Write-Info "Run backups manually: powershell -File $BACKUP_SCRIPT_PATH"
        }
    } else {
        Write-Info "Skipping scheduled task (requires admin)"
        Write-Info "Run backups manually: powershell -File $BACKUP_SCRIPT_PATH"
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

function Show-Summary {
    Write-Header "Setup Complete!"
    
    Write-Host ""
    Write-Host "Project is ready to use!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Quick Start Commands:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. Activate virtual environment:" -ForegroundColor White
    Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  2. Ingest YouTube videos:" -ForegroundColor White
    Write-Host "     python src/ingest_youtube.py https://youtube.com/..." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  3. Denoise audio:" -ForegroundColor White
    Write-Host "     python src/preprocessing/denoise_audio.py --all" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  4. Process with Gemini:" -ForegroundColor White
    Write-Host "     python src/preprocessing/gemini_process.py --all" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  5. Start review app:" -ForegroundColor White
    Write-Host "     streamlit run src/review_app.py" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  6. Export dataset:" -ForegroundColor White
    Write-Host "     python src/export_final.py" -ForegroundColor Gray
    Write-Host ""
    
    if (-not $SkipTailscale) {
        Write-Host "Remote Access:" -ForegroundColor Yellow
        Write-Host "  Your Streamlit app is accessible via Tailscale" -ForegroundColor Gray
        Write-Host "  Check your Tailscale dashboard for the URL" -ForegroundColor Gray
        Write-Host ""
    }
    
    Write-Host "Documentation:" -ForegroundColor Yellow
    Write-Host "  See docs/ folder for detailed guides" -ForegroundColor Gray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

Write-Header "NLP Pipeline Setup"
Write-Host "Setting up Vietnamese-English CS Speech Translation pipeline"
Write-Host ""

# Run setup steps
Test-Prerequisites
Setup-PythonEnvironment
Setup-Database

if (-not $SkipTailscale) {
    Setup-Tailscale
}

if (-not $SkipBackup) {
    Setup-Backup
}

Show-Summary

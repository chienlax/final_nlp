# Server Setup Guide: Windows 11 Deployment

**For**: Deploying the Speech Translation Pipeline on a Windows 11 Server  
**Version**: 1.0  
**Stack**: PostgreSQL + FastAPI + React + Tailscale + DVC

---

## Overview

This guide covers deploying the pipeline from development to a production-ready Windows 11 server accessible via Tailscale.

```
┌─────────────────────────────────────────────────────────────────┐
│                     WINDOWS 11 SERVER                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ PostgreSQL  │  │ FastAPI     │  │ Vite Dev Server         │ │
│  │ Port: 5432  │  │ Port: 8000  │  │ Port: 5173              │ │
│  │ (Service)   │  │ (Script)    │  │ (Script)                │ │
│  └─────────────┘  └──────┬──────┘  └────────────┬────────────┘ │
│                          │                       │              │
│                          └───────────┬───────────┘              │
│                                      ▼                          │
│                        ┌─────────────────────────┐              │
│                        │ Tailscale               │              │
│                        │ (VPN Mesh)              │              │
│                        └─────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
              ┌──────────┐                  ┌──────────┐
              │ Client A │                  │ Client B │
              │ (Laptop) │                  │ (Laptop) │
              └──────────┘                  └──────────┘
```

---

## 1. Server Requirements

### 1.1 Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Storage | 100 GB | 500 GB (SSD) |
| Network | 10 Mbps | 100 Mbps |

### 1.2 Software Prerequisites

| Software | Version | Purpose |
|----------|---------|---------|
| Windows 11 | 23H2+ | Operating System |
| Python | 3.10+ | Backend runtime |
| Node.js | 18+ | Frontend build |
| PostgreSQL | 15+ | Database |
| FFmpeg | Latest | Audio processing |
| Git | Latest | Version control |
| Tailscale | Latest | VPN mesh |

---

## 2. Initial Setup

### 2.1 Install Required Software

```powershell
# Install Chocolatey (if not installed)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install dependencies via Chocolatey
choco install -y python nodejs postgresql15 ffmpeg git tailscale
```

### 2.2 Clone Repository

```powershell
cd C:\Projects
git clone [YOUR_REPO_URL] final_nlp
cd final_nlp
```

### 2.3 Setup Python Environment

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2.4 Setup PostgreSQL

```powershell
# Start PostgreSQL service (should be running after install)
# Access psql
psql -U postgres

# In psql:
CREATE DATABASE speech_translation_db;
\q
```

### 2.5 Configure Environment

Copy `.env.example` to `.env` and edit:

```ini
# Database
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/speech_translation_db

# Data storage (use absolute path on server)
DATA_ROOT=C:\Projects\final_nlp\data

# Gemini API Keys (comma-separated for rotation)
GEMINI_API_KEYS=key1,key2,key3

# Ports
BACKEND_PORT=8000
FRONTEND_PORT=5173
```

### 2.6 Initialize Database

```powershell
# Run database initialization
python scripts/init_db.py
```

---

## 3. Tailscale Setup

### 3.1 Install and Login

```powershell
# Install (if not via choco)
# Download from: https://tailscale.com/download/windows

# Login via system tray icon or:
tailscale up
```

### 3.2 Get Server IP

```powershell
tailscale ip -4
# Example output: 100.64.0.1
```

Share this IP with your team members.

### 3.3 Configure Firewall

```powershell
# Allow FastAPI through firewall
New-NetFirewallRule -DisplayName "FastAPI" -Direction Inbound -Port 8000 -Protocol TCP -Action Allow

# Allow Vite dev server
New-NetFirewallRule -DisplayName "Vite" -Direction Inbound -Port 5173 -Protocol TCP -Action Allow
```

### 3.4 Team Setup

Each team member needs:
1. Install Tailscale on their laptop
2. Login with same Tailscale account (or invite to tailnet)
3. Use server's Tailscale IP in their `API_BASE` config

---

## 4. Running Services

### 4.1 Start Backend

```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Start FastAPI
cd C:\Projects\final_nlp
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

> [!IMPORTANT]
> Use `--host 0.0.0.0` to accept connections from other machines (via Tailscale).

### 4.2 Start Frontend

```powershell
# New terminal window
cd C:\Projects\final_nlp\frontend
npm install
npm run dev -- --host 0.0.0.0
```

### 4.3 Verify Access

From client machine:
- Frontend: `http://[TAILSCALE_IP]:5173`
- API Docs: `http://[TAILSCALE_IP]:8000/docs`
- Health: `http://[TAILSCALE_IP]:8000/health`

---

## 5. Data Backup with DVC + Google Drive

### 5.1 Setup DVC

```powershell
# Install DVC with Google Drive support
pip install "dvc[gdrive]"

# Initialize DVC (if not already)
dvc init
```

### 5.2 Configure Google Drive Remote

```powershell
# Add Google Drive as remote storage
dvc remote add -d gdrive gdrive://[FOLDER_ID]

# First push will trigger OAuth login
dvc push
```

To get `FOLDER_ID`:
1. Create folder in Google Drive
2. Copy folder ID from URL: `https://drive.google.com/drive/folders/[FOLDER_ID]`

### 5.3 Track Data

```powershell
# Track data directory
dvc add data/chunks
dvc add data/raw
git add data/.gitignore data/chunks.dvc data/raw.dvc
git commit -m "Track data with DVC"

# Push to Google Drive
dvc push
```

### 5.4 Automatic Backup (Task Scheduler)

Create `scripts/backup_data.ps1`:

```powershell
Set-Location C:\Projects\final_nlp
.\.venv\Scripts\Activate.ps1
dvc push
```

Schedule hourly backup:

```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\Projects\final_nlp\scripts\backup_data.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "DVC_Backup" -Action $action -Trigger $trigger -Description "Hourly DVC backup to Google Drive"
```

---

## 6. Database Backup

### 6.1 Manual Backup

```powershell
# Create backup
pg_dump -U postgres speech_translation_db > backup_$(Get-Date -Format "yyyyMMdd_HHmmss").sql
```

### 6.2 Automated Backup to Google Drive

Create `scripts/backup_db.ps1`:

```powershell
$backupDir = "C:\Projects\final_nlp\data\db_backups"
$backupFile = "$backupDir\db_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"

# Create backup directory
New-Item -ItemType Directory -Force -Path $backupDir

# Dump database
pg_dump -U postgres speech_translation_db > $backupFile

# Keep only last 7 backups locally
Get-ChildItem $backupDir -Filter "*.sql" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 7 | Remove-Item

# Push to DVC (tracked in Git)
Set-Location C:\Projects\final_nlp
.\.venv\Scripts\Activate.ps1
dvc add data/db_backups
dvc push
```

Schedule daily at 2 AM:

```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\Projects\final_nlp\scripts\backup_db.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName "DB_Backup" -Action $action -Trigger $trigger
```

---

## 7. Troubleshooting

### Port Already in Use

```
Error: Address already in use
```

**Solution**:
```powershell
# Find process using port
netstat -ano | findstr :8000

# Kill process (replace PID)
taskkill /PID [PID] /F
```

### PostgreSQL Connection Refused

```
Error: could not connect to server
```

**Solutions**:
1. Check service is running:
   ```powershell
   Get-Service postgresql*
   ```
2. Start service if stopped:
   ```powershell
   Start-Service postgresql-x64-15
   ```

### Tailscale Not Connecting

**Solutions**:
1. Check Tailscale status:
   ```powershell
   tailscale status
   ```
2. Re-authenticate:
   ```powershell
   tailscale up --reset
   ```

### DVC Push Fails

```
Error: 403 Forbidden
```

**Solutions**:
1. Re-authorize Google Drive:
   ```powershell
   dvc remote modify gdrive --local gdrive_acknowledge_abuse true
   dvc push
   ```
2. Check folder permissions in Google Drive

---

## 8. Quick Reference

| Task | Command |
|------|---------|
| Start backend | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` |
| Start frontend | `npm run dev -- --host 0.0.0.0` |
| Get Tailscale IP | `tailscale ip -4` |
| Backup database | `pg_dump -U postgres speech_translation_db > backup.sql` |
| Push to DVC | `dvc push` |
| Pull from DVC | `dvc pull` |
| Check DVC status | `dvc status` |

---

## 9. Migration Checklist

- [ ] Install all software prerequisites
- [ ] Clone repository
- [ ] Configure `.env` with production values
- [ ] Initialize PostgreSQL database
- [ ] Setup Tailscale and share IP
- [ ] Configure Windows Firewall rules
- [ ] Start backend and frontend
- [ ] Verify client access via Tailscale
- [ ] Setup DVC with Google Drive
- [ ] Configure automated backups
- [ ] Test backup/restore process

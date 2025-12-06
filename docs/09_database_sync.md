# Database Synchronization Guide

## Overview

This project uses a **hybrid sync strategy** combining automated backups with version control:

1. **Automated Backups** (hourly) → Google Drive
2. **DVC Version Control** (manual snapshots) → Google Drive + Git

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│ Dev Machine     │         │  Google Drive    │         │  Lab Machine    │
│                 │         │                  │         │                 │
│ lab_data.db ────┼────────→│ Hourly Backups   │←────────┼──── lab_data.db │
│     ↓           │         │ (24 recent)      │         │        ↑        │
│ dvc add     ────┼────────→│                  │         │    dvc pull     │
│ dvc push        │         │ DVC Cache        │←────────┼──── (team sync) │
│                 │         │ (versioned)      │         │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
         ↓                           ↑
         └──────── git push ─────────┘
```

## Setup (One-Time)

### On Development Machine

```powershell
# 1. Initialize DVC tracking
python -m dvc add data/lab_data.db

# 2. Commit to git
git add data/lab_data.db.dvc data/.gitignore
git commit -m "feat: track database with DVC"

# 3. Push to remotes
python -m dvc push
git push

# 4. Enable automated backups (optional but recommended)
.\setup.ps1  # Creates hourly backup task
```

### On Lab Machine

```powershell
# 1. Clone repository
git clone https://github.com/chienlax/final_nlp.git
cd final_nlp

# 2. Setup environment
.\setup.ps1  # Creates venv, downloads database, enables backups

# 3. Pull database from DVC
python -m dvc pull data/lab_data.db.dvc
```

## Daily Workflow

### Scenario 1: Development Machine → Lab Machine

You develop/test on your personal machine, then deploy to lab machine for team annotation.

**On Dev Machine** (after testing):
```powershell
# 1. Create DVC snapshot
python -m dvc add data/lab_data.db

# 2. Commit changes
git add data/lab_data.db.dvc src/
git commit -m "feat: improved chunking script + DB with test data"

# 3. Push to remotes
python -m dvc push
git push
```

**On Lab Machine**:
```powershell
# 1. Pull latest code
git pull

# 2. Pull latest database
python -m dvc pull data/lab_data.db.dvc

# 3. Start Streamlit for team
streamlit run src/review_app.py --server.port 8501
```

### Scenario 2: Team Annotation → Backup

Team members annotate via Tailscale-connected Streamlit on lab machine.

**Automatic** (no action needed):
- Hourly backup runs in background
- Database copied to `G:\My Drive\NLP_Backups\lab_data_YYYYMMDD_HHMMSS.db`

**After Review Session** (manual snapshot):
```powershell
# On lab machine
python -m dvc add data/lab_data.db
git add data/lab_data.db.dvc
git commit -m "DB update: reviewed 15 videos on $(Get-Date -Format 'yyyy-MM-dd')"
python -m dvc push
git push
```

**On Dev Machine** (next day):
```powershell
# Pull team's annotation work
git pull
python -m dvc pull data/lab_data.db.dvc
```

## Best Practices

### When to Create DVC Snapshots

✅ **Do snapshot**:
- After completing a milestone (e.g., 10 videos reviewed)
- Before major schema changes
- End of day if significant annotation was done
- Before switching machines

❌ **Don't snapshot**:
- After every single video (too granular)
- During active annotation (wait for session end)
- Multiple times per hour (let automated backup handle it)

### Backup Retention

- **Automated backups**: Last 24 hours (hourly granularity)
- **DVC snapshots**: Forever (via git history)

To see old versions:
```powershell
git log --oneline data/lab_data.db.dvc
git checkout abc123 data/lab_data.db.dvc
python -m dvc checkout data/lab_data.db.dvc
```

### Storage Management

**Current tracking**:
- `data/raw.dvc`: 87.6 MB (audio files)
- `data/db_sync.dvc`: 42.7 KB (old sync logs, can remove)
- `data/lab_data.db.dvc`: ~10-100 MB (will grow to 500MB)

**For 200 hours of audio**:
- Raw audio: ~50 GB
- Database: ~500 MB (estimated)
- DVC cache: ~50 GB
- **Total**: ~100 GB (well within 2TB limit)

### Conflict Resolution

If both machines modify the database simultaneously:

```powershell
# ERROR: dvc push fails due to conflicting versions

# Solution: Keep one version, discard the other
# Option A: Keep local changes
python -m dvc push --force

# Option B: Keep remote changes
python -m dvc pull --force

# There's no automatic merge for binary database files
# Coordination via team communication is required
```

**Prevention**: Designate lab machine as the "primary" for annotation, dev machine for code changes.

## Disaster Recovery

### Scenario: Lab machine hard drive failure

```powershell
# On new/replacement machine
git clone https://github.com/chienlax/final_nlp.git
cd final_nlp
.\setup.ps1
python -m dvc pull data/lab_data.db.dvc

# Database restored! Maximum loss: 1 hour of work (since last backup)
```

### Scenario: Accidental database corruption

```powershell
# Try SQLite recovery first
sqlite3 data/lab_data.db "PRAGMA integrity_check;"

# If corrupt, restore from hourly backup
Copy-Item "G:\My Drive\NLP_Backups\lab_data_latest.db" data/lab_data.db

# Or restore from DVC (last snapshot)
python -m dvc checkout data/lab_data.db.dvc --force
```

### Scenario: Need database from 2 days ago

```powershell
# Check git history
git log --oneline --since="2 days ago" data/lab_data.db.dvc

# Restore specific version
git checkout abc123 data/lab_data.db.dvc
python -m dvc checkout data/lab_data.db.dvc

# Return to latest
git checkout dev data/lab_data.db.dvc
python -m dvc checkout data/lab_data.db.dvc
```

## Monitoring

### Check Backup Status

```powershell
# View recent backups
Get-ChildItem "G:\My Drive\NLP_Backups\" | Sort-Object LastWriteTime -Descending | Select-Object -First 5

# Check scheduled task
Get-ScheduledTask -TaskName "NLP_DB_Hourly_Backup" | Select-Object State, LastRunTime, NextRunTime
```

### Check DVC Status

```powershell
# See what needs to be pushed
python -m dvc status

# Check remote connection
python -m dvc remote list -v

# See DVC cache size
Get-ChildItem .dvc/cache -Recurse | Measure-Object -Property Length -Sum
```

## Troubleshooting

See [`docs/04_troubleshooting.md`](04_troubleshooting.md#database-sync-issues) for common issues and solutions.

## Summary

- **Automated backups**: Set it and forget it (hourly protection)
- **DVC snapshots**: Explicit version control (team collaboration)
- **Storage**: 2TB Google Drive is plenty for 200 hours of audio
- **Workflow**: Dev machine for code → Lab machine for annotation → Sync via DVC
- **Recovery**: Multiple layers (hourly backups + DVC history + git commits)

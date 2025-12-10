# Getting Started: Client Ingestion Guide

**For**: Team members downloading and uploading YouTube videos  
**Version**: 1.0

---

## Overview

This guide covers how to download YouTube videos and upload them to the server for processing. As a client-side user, you will use the **Ingestion GUI** tool on your local machine.

```
Your Laptop                    Server
┌─────────────┐               ┌─────────────┐
│ ingest_gui  │──── HTTP ────▶│ FastAPI     │
│ (Tkinter)   │               │ + Postgres  │
└─────────────┘               └─────────────┘
```

---

## 1. Prerequisites

### 1.1 Required Software

| Software | Version | Installation |
|----------|---------|-------------|
| Python | 3.10+ | [python.org](https://python.org) |
| FFmpeg | Latest | `choco install ffmpeg` or [ffmpeg.org](https://ffmpeg.org) |
| yt-dlp | Latest | `pip install yt-dlp` |

### 1.2 Project Setup

```powershell
# Clone repository (or receive from team lead)
cd your-workspace
git clone [repo-url] final_nlp
cd final_nlp

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 1.3 Configure Server Connection

Edit `.env` file in project root:

```ini
# Server API endpoint (get from team lead)
API_BASE=http://[SERVER_TAILSCALE_IP]:8000/api

# Local temp directory
DATA_ROOT=./data
```

> [!IMPORTANT]
> Get the server's Tailscale IP from your team lead. You must have Tailscale installed and connected to the team network.

---

## 2. Using the Ingestion GUI

### 2.1 Launch

```powershell
# Activate venv first
.\.venv\Scripts\Activate.ps1

# Run GUI
python ingest_gui.py
```

### 2.2 Interface Overview

```
┌─────────────────────────────────────────────────────────┐
│ 🎙️ Speech Translation - YouTube Ingestion              │
├─────────────────────────────────────────────────────────┤
│ User: [Chien ▼]    Channel: (auto-detected)             │
├─────────────────────────────────────────────────────────┤
│ ┌───────────┬────────────┬────────────┐                 │
│ │Video URLs │ Playlists  │ Channel    │ ◄── 3 Tabs     │
│ └───────────┴────────────┴────────────┘                 │
│                                                         │
│ [Text area for URLs]                                    │
│                                                         │
│ [Fetch Videos]                                          │
├─────────────────────────────────────────────────────────┤
│ Videos:                                                 │
│ ╔═════════════════════════════════════════════════════╗ │
│ ║ Title                  │ Duration │ Channel │ Status║ │
│ ╠═════════════════════════════════════════════════════╣ │
│ ║ Episode 101           │ 45:23    │ Channel │ ✓ OK  ║ │
│ ║ Episode 102           │ 32:15    │ Channel │ ⚠️ Dup║ │
│ ╚═════════════════════════════════════════════════════╝ │
├─────────────────────────────────────────────────────────┤
│ [Select All] [Check Duplicates] [Download Selected]     │
├─────────────────────────────────────────────────────────┤
│ Progress: 5/10 (✓3 ✗1 ⏭1)  [████░░░░░░]                │
├─────────────────────────────────────────────────────────┤
│ Log: ✓ Downloaded Episode 101                           │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Download Workflow

### Step 1: Select Your User

From the **User** dropdown, select your name. This identifies who uploaded each video.

### Step 2: Choose Input Mode (Tab)

| Tab | Use Case | Input |
|-----|----------|-------|
| **Video URLs** | Individual videos | Paste URLs (comma/newline separated) |
| **Playlists** | Entire playlists | Paste playlist URLs |
| **Channel** | Browse all videos | Paste channel URL |

### Step 3: Fetch Videos

Click **Fetch Videos** (or **Fetch Playlists** / **Fetch Channel**).

- The GUI extracts video metadata
- Channel is **auto-detected** from video info
- Videos appear in the list

### Step 4: Check for Duplicates

Click **Check Duplicates** to validate against the server database.

| Status | Meaning |
|--------|---------|
| ✓ OK | Safe to download |
| ⚠️ Duplicate | Already in database - will be skipped |
| ✗ Error | API unreachable |

### Step 5: Download Selected

1. Select videos (or click **Select All**)
2. Click **Download Selected**
3. Watch progress bar
4. Review summary in log

---

## 4. Troubleshooting

### Cannot Connect to Server

```
Error: Connection refused
```

**Solutions**:
1. Check Tailscale is running and connected
2. Verify `API_BASE` in `.env` matches server IP
3. Ask team lead if server is online

### Video Already Exists

```
⚠️ Duplicate
```

**Expected behavior**: Duplicates are automatically skipped. This protects against double-uploads.

### Download Failed

```
✗ Failed: [error message]
```

**Common causes**:
- Private video (not accessible)
- Age-restricted content
- YouTube rate limiting (wait and retry)
- Network timeout

### FFmpeg Not Found

```
FileNotFoundError: 'ffmpeg'
```

**Solutions**:
1. Install FFmpeg: `choco install ffmpeg`
2. Or download from [ffmpeg.org](https://ffmpeg.org)
3. Restart terminal after installation

---

## 5. Best Practices

### Do ✓

- Always **Check Duplicates** before downloading
- Download in batches (10-20 videos at a time)
- Review the log for any failures
- Keep your User selection consistent

### Don't ✗

- Don't download dubbed audio (system auto-filters but be aware)
- Don't close GUI mid-download
- Don't upload copyrighted content without permission

---

## 6. After Upload

Once videos are uploaded to the server:

1. **Chunking**: Server splits audio into 5-minute chunks
2. **AI Processing**: Gemini transcribes each chunk
3. **Review**: Chunks appear in the web UI for annotation

Your work is done! The server-side team handles processing.

---

## Quick Reference

| Action | Command/Button |
|--------|----------------|
| Start GUI | `python ingest_gui.py` |
| Check server status | Open browser: `http://[SERVER_IP]:8000/health` |
| View logs | Scroll log panel at bottom of GUI |
| Clear list | Click **Clear List** button |

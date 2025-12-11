# Getting Started Guide

**Version**: 2.0  
**Last Updated**: 2025-12-11

---

## Overview

This guide covers two scenarios:

1. **Client-Side Users**: Downloading YouTube videos and uploading to the server
2. **Annotators**: Accessing the annotation interface remotely via Tailscale

```
Annotator Laptop           Server Machine              Client Laptop
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│ Browser      │─Tailscale─▶│ Frontend    │          │ ingest_gui   │
│ (Review UI)  │          │ (Vite:5173) │          │ (Tkinter)    │
└──────────────┘          │              │          └──────────────┘
                          │ Backend      │◀─ HTTP ───┘
                          │ (FastAPI)    │
                          └──────────────┘
```

---

## Part 1: Accessing the Annotation Interface

**For**: Team members reviewing and annotating transcriptions

## Part 2: Client Ingestion (YouTube Downloads)

**For**: Team members downloading and uploading YouTube videos

### 2.1 Prerequisites

| Requirement | Installation | Notes |
|-------------|--------------|-------|
| Tailscale | [tailscale.com](https://tailscale.com/download) | VPN for secure team access |
| Modern Browser | Chrome/Firefox/Edge | For React frontend |

### 1.2 Get Server Access Info

Contact your team lead for:

1. **Tailscale IP Address**: `100.64.x.x` (example: `100.64.1.5`)
2. **User Credentials**: Your username for the annotation system

> [!IMPORTANT]  
> You must be connected to the team's Tailscale network. Open Tailscale and ensure the status shows "Connected".

### 1.3 Access the Annotation Interface

1. **Verify Tailscale Connection**
   ```powershell
   # Check your Tailscale status (optional)
   tailscale status
   ```

2. **Open the Frontend**
   - Navigate to: `http://[SERVER_TAILSCALE_IP]:5173`
   - Example: `http://100.64.1.5:5173`

3. **Select Your User**
   - On the main page, select your username from the dropdown
   - This tracks who reviews/approves each chunk

### 1.4 Annotation Workflow

Once logged in, you'll see the Workbench interface:

```
┌────────────────────────────────────────────────────────┐
│ 🎯 Workbench                                           │
├────────────────────────────────────────────────────────┤
│ Video: Episode 102 | Chunk: 05 | Status: In Review     │
├────────────────────────────────────────────────────────┤
│ ┌─ Waveform ────────────────────────────────────────┐  │
│ │                                                    │  │
│ │  [Audio visualization with timestamps]            │  │
│ │                                                    │  │
│ └────────────────────────────────────────────────────┘  │
│                                                        │
│ Segments:                                              │
│ ┌─────┬──────────┬──────────┬───────────────────────┐ │
│ │  #  │ Start    │ End      │ Transcript/Translation│ │
│ ├─────┼──────────┼──────────┼───────────────────────┤ │
│ │ 1   │ 00:04.5  │ 00:08.2  │ [Editable text]       │ │
│ │ 2   │ 00:08.5  │ 00:12.0  │ [Editable text]       │ │
│ └─────┴──────────┴──────────┴───────────────────────┘ │
│                                                        │
│ [Flag Noisy Audio]  [Save]  [Approve Chunk]            │
└────────────────────────────────────────────────────────┘
```

**Key Actions**:
- **Edit Timestamps**: Click on start/end time fields (format: `MM:SS.f`)
- **Edit Text**: Click on transcript/translation cells
- **Flag Noisy Audio**: Mark chunks for DeepFilterNet processing
- **Approve**: Finalizes chunk for export

### 1.5 Troubleshooting Access Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `Connection Refused` | Tailscale not connected | Open Tailscale app, ensure "Connected" status |
| `Page Won't Load` | Wrong IP or server offline | Verify IP with team lead, check server status |
| `API Errors (CORS)` | Server config issue | Team lead: add Tailscale IP to CORS_ORIGINS in `.env` |
| `Slow Performance` | Network latency | Check Tailscale connection quality |

**Debug Commands** (run on your machine):
```powershell
# Test connection to backend API
curl http://[SERVER_IP]:8000/health

# Check Tailscale route
ping [SERVER_IP]
```

---

## Part 2: Client Ingestion (YouTube Downloads)

**For**: Team members downloading and uploading YouTube videos

### 2.1 Prerequisites

#### 2.1.1 Required Software

| Software | Version | Installation |
|----------|---------|-------------|
| Python | 3.10+ | [python.org](https://python.org) |
| FFmpeg | Latest | `choco install ffmpeg` or [ffmpeg.org](https://ffmpeg.org) |
| yt-dlp | Latest | `pip install yt-dlp` |

#### 2.1.2 Project Setup

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

#### 2.1.3 Configure Server Connection

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

### 2.2 Using the Ingestion GUI

#### 2.2.1 Launch

```powershell
# Activate venv first
.\.venv\Scripts\Activate.ps1

# Run GUI
python ingest_gui.py
```

#### 2.2.2 Interface Overview

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

### 2.3 Download Workflow

#### Step 1: Select Your User

From the **User** dropdown, select your name. This identifies who uploaded each video.

#### Step 2: Choose Input Mode (Tab)

| Tab | Use Case | Input |
|-----|----------|-------|
| **Video URLs** | Individual videos | Paste URLs (comma/newline separated) |
| **Playlists** | Entire playlists | Paste playlist URLs |
| **Channel** | Browse all videos | Paste channel URL |

#### Step 3: Fetch Videos

Click **Fetch Videos** (or **Fetch Playlists** / **Fetch Channel**).

- The GUI extracts video metadata
- Channel is **auto-detected** from video info
- Videos appear in the list

#### Step 4: Check for Duplicates

Click **Check Duplicates** to validate against the server database.

| Status | Meaning |
|--------|---------|
| ✓ OK | Safe to download |
| ⚠️ Duplicate | Already in database - will be skipped |
| ✗ Error | API unreachable |

#### Step 5: Download Selected

1. Select videos (or click **Select All**)
2. Click **Download Selected**
3. Watch progress bar
4. Review summary in log

---

### 2.4 Troubleshooting

#### Cannot Connect to Server

```
Error: Connection refused
```

**Solutions**:
1. Check Tailscale is running and connected
2. Verify `API_BASE` in `.env` matches server IP
3. Ask team lead if server is online

#### Video Already Exists

```
⚠️ Duplicate
```

**Expected behavior**: Duplicates are automatically skipped. This protects against double-uploads.

#### Download Failed

```
✗ Failed: [error message]
```

**Common causes**:
- Private video (not accessible)
- Age-restricted content
- YouTube rate limiting (wait and retry)
- Network timeout

#### FFmpeg Not Found

```
FileNotFoundError: 'ffmpeg'
```

**Solutions**:
1. Install FFmpeg: `choco install ffmpeg`
2. Or download from [ffmpeg.org](https://ffmpeg.org)
3. Restart terminal after installation

---

### 2.5 Best Practices

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

### 2.6 After Upload

Once videos are uploaded to the server:

1. **Chunking**: Server splits audio into 5-minute chunks
2. **AI Processing**: Gemini transcribes each chunk
3. **Review**: Chunks appear in the web UI for annotation

Your work is done! The server-side team handles processing.

---

## Part 3: Server Setup (For Server Admin)

**For**: Person managing the server machine

### 3.1 Network Configuration

#### 3.1.1 Get Tailscale IP

```powershell
# On the server machine, get Tailscale IP
tailscale ip -4
# Example output: 100.64.1.5
```

Share this IP with your team.

#### 3.1.2 Firewall Rules (Windows)

Already configured (as shown in your output):

```powershell
# Allow Vite dev server
New-NetFirewallRule -DisplayName "Vite" -Direction Inbound -LocalPort 5173 -Protocol TCP -Action Allow

# Allow FastAPI backend
New-NetFirewallRule -DisplayName "FastAPI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

**Verify rules**:
```powershell
Get-NetFirewallRule -DisplayName "Vite","FastAPI" | Format-Table DisplayName,Enabled,Direction,Action
```

#### 3.1.3 Configure CORS (Backend)

Edit [.env](.env) on server:

```ini
# Add Tailscale IP to CORS origins
CORS_ORIGINS=http://localhost:5173,http://100.64.1.5:5173
```

This allows the frontend to make API requests when accessed via Tailscale.

### 3.2 Start Services

Use the automated startup script:

```powershell
# Navigate to project root
cd C:\Users\ORLab\main_source\final_nlp

# Start all services (Backend + Frontend + Worker)
.\scripts\start_server.ps1
```

**What happens**:
1. Checks PostgreSQL service
2. Activates virtual environment
3. Installs/updates dependencies
4. Initializes database
5. Starts FastAPI on `0.0.0.0:8000`
6. Starts Vite on `0.0.0.0:5173`
7. Starts Gemini worker (optional: add `-SkipWorker` flag to skip)

**Verify services are running**:

```powershell
# Check processes
Get-Process | Where-Object {$_.ProcessName -like "*python*" -or $_.ProcessName -like "*node*"}

# Test backend
curl http://localhost:8000/health

# Test frontend (from teammate's machine)
curl http://[SERVER_TAILSCALE_IP]:5173
```

### 3.3 Share Access Info with Team

Provide teammates with:

1. **Tailscale IP**: `100.64.x.x`
2. **Frontend URL**: `http://[TAILSCALE_IP]:5173`
3. **Their Username**: For selecting in the UI
4. **Instructions**: Link to this document

**Template message**:
```
Hey team,

Server is live! Access the annotation interface at:
http://100.64.1.5:5173

Your username: [THEIR_NAME]

Make sure Tailscale is connected before accessing.

Guide: docs/04_getting-started.md
```

---

## Quick Reference

### For Annotators
| Action | URL/Command |
|--------|-------------|
| Access annotation UI | `http://[SERVER_IP]:5173` |
| Check backend health | `http://[SERVER_IP]:8000/health` |
| Test Tailscale | `ping [SERVER_IP]` |

### For Clients (Ingestion)
| Action | Command/Button |
|--------|----------------|
| Start GUI | `python ingest_gui.py` |
| Check server status | `http://[SERVER_IP]:8000/health` |
| View logs | Scroll log panel at bottom of GUI |

### For Server Admin
| Action | Command |
|--------|---------|
| Start all services | `.\scripts\start_server.ps1` |
| Get Tailscale IP | `tailscale ip -4` |
| Check firewall | `Get-NetFirewallRule -DisplayName "Vite","FastAPI"` |
| Verify backend | `curl http://localhost:8000/health` |

---

**Support**: Contact team lead for access issues or server problems.

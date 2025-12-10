# Technical Specification: Vietnamese-English Code-Switching Pipeline
**Version:** 1.0

---

## 1. Executive Summary & Architecture

### 1.1 Project Objective

To construct a high-quality, verified Speech Translation dataset (Vietnamese-English Code-Switching) consisting of **150+ hours** of audio. The pipeline automates the "heavy lifting" (transcription/translation) using **Gemini 2.5 Flash**, leaving human annotators to focus solely on verification and fine-tuning.

**Final Deliverables:**

1.  **Audio Segments:** 2-25s .wav clips (16kHz, Mono).
2.  **Manifest File:** A `manifest.tsv` containing absolute paths, transcripts, and translations suitable for model training.

### 1.2 High-Level Architecture (The Stack)

We utilize a **3-Tier Client-Server Architecture** secured via **Tailscale**. This ensures that while the database and heavy storage live on one powerful machine (The Server), annotators can work from lightweight laptops (The Clients).

| Tier | Component | Technology | Responsibility |
| :--- | :--- | :--- | :--- |
| **Presentation** | **Frontend** | React (Vite) + Wavesurfer.js | Visualizes waveforms, manages user interactions, handles "Relative Time" logic. |
| **Logic** | **Backend** | FastAPI (Python 3.10+) | Orchestrates file locking, mounts the file system, executes background Denoising tasks. |
| **Data** | **Database** | PostgreSQL | Stores metadata, user states, and transcription text. **The Single Source of Truth.** |
| **Storage** | **File System** | Local Disk + Google Drive | Stores physical .m4a and .wav files. Synced for backup. |

### 1.3 The "Data Factory" Lifecycle (Visual Data Flow)

Data moves through the system in four strict stages. Every stage is a "Gate" that the data must pass through.

#### Stage 1: Ingestion (Distributed -> Centralized)

*   **Input:** User runs `ingest_gui.py` on their local laptop.
*   **Validation:** Script checks `yt-dlp` metadata for `original_url` to prevent duplicates.
*   **Process:** `yt-dlp` downloads audio (Config: `format_sort=['lang:vi', 'acodec:aac']`).
*   **Storage:** File is uploaded via API to Server Path: `/mnt/data/raw/{video_id}.m4a`. Metadata inserted into Video table.

#### Stage 2: Core Processing (The "Meat Grinder")

*   **Input:** Server detects new file in `/mnt/data/raw`.
*   **Process A (Chunking):** FFmpeg splits audio into 5-minute chunks with 5-second overlap.
*   **Process B (AI):** Gemini 2.5 Flash generates JSON transcripts for each chunk.
*   **Storage:**
    *   Audio: `/mnt/data/chunks/{video_id}/{chunk_id}.wav`
    *   Text: Parsed JSON inserted into Segment table (using **Relative Time**).

#### Stage 3: Human Review (The Annotation Loop)

*   **Input:** User requests "Next Pending Chunk" via React Frontend.
*   **Locking:** Backend sets `Chunk.locked_by_user_id = {user_id}`.
*   **Action:** User corrects text, adjusts timestamps, or toggles `[Flag for Denoise]`.
*   **Storage:** Updates Segment table. Status set to `APPROVED` or `FLAGGED`.

#### Stage 4: Operations & Export (The "Night Shift")

*   **Process A (Denoise):** Background script scans DB for `denoise_status="flagged"`. Runs DeepFilterNet on specific chunks.
*   **Process B (Export):** Script reads `APPROVED` segments.
*   **Logic:** Converts **Relative Time** (00:04) -> **Absolute Time** (05:04). Handles 5s overlap stitching.
*   **Output:** Generates `dataset/manifest.tsv`.

### 1.4 Key Architectural Decisions

#### A. The "Relative Time" Standard

To prevent math errors during the manual review process, the Database and Frontend operate **exclusively** in "Chunk Time."

*   **The Rule:** A timestamp is always relative to the start of the 5-minute chunk file.
*   **Example:** If a user marks a segment at 00:10.00, it means 10 seconds into the .wav file.
*   **Why:** We do not want the Frontend to calculate `(Chunk_Index * 300) + 10`. That calculation happens **once**, purely in the final Export script.

#### B. Directory Structure (The "File System")

We do not scatter files. The backend mounts a single root directory.

*   **Root:** `/mnt/data/project_speech`
    *   `├── raw/` (Original 1-hour .m4a downloads)
    *   `├── chunks/` (The working directory)
        *   `├── video_{id}/`
            *   `├── chunk_00.wav`
            *   `├── chunk_01.wav`
    *   `├── processed/` (Denoised versions, if generated)
    *   `├── logs/` (Server processing logs)

#### C. Concurrency Control (The "Lock")

Since we have 3 users and 1 database:

*   **Constraint:** A user can only edit a chunk if `Chunk.locked_by_user_id` is either NULL or their own ID.
*   **Enforcement:** The FastAPI backend rejects `POST /save` requests if the lock belongs to someone else.

**Critique for the Team:** This architecture favors consistency over speed. We split the "Creation" (Gemini) from the "Review" (React) to ensure that if the AI fails, the human workflow is not blocked. We use Postgres to manage the state because files on disk cannot tell us "User A is working on this right now."

---

## 2. Database Schema

### 2.1 Overview & Entity Relationships

The database serves as the Single Source of Truth (SSoT) for the pipeline. It manages the hierarchy of data and the state of the workflow (who is doing what).

**The Hierarchy:**

1.  **Channel:** A YouTube source (e.g., "Vietcetera").
2.  **Video:** A specific episode downloaded from that channel.
3.  **Chunk:** A 5-minute slice of that video (The "Unit of Work").
4.  **Segment:** A 2-25 second clip inside a chunk (The "Training Data").

**Key Relationships:**

*   **One-to-Many:** A Channel has many Videos. A Video has many Chunks. A Chunk has many Segments.
*   **User-to-Data:** A User can *upload* many videos. A User can *lock* (edit) only one Chunk at a time.

### 2.2 SQLModel Code Definitions

The following Python code defines the exact structure of the PostgreSQL tables.

#### A. Enums (The State Machine)

We use Enums to prevent "Magic Strings" and ensure valid states.

```python
from enum import Enum
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class UserRole(str, Enum):
    ADMIN = "admin"        # Can delete data / manage users
    ANNOTATOR = "annotator" # Can only edit/review

class ProcessingStatus(str, Enum):
    PENDING = "pending"          # Just created/uploaded
    PROCESSING = "processing"    # Gemini/FFmpeg running
    REVIEW_READY = "review_ready" # AI finished, waiting for human
    IN_REVIEW = "in_review"      # Currently locked by a user
    APPROVED = "approved"        # Human verified, ready for export
    REJECTED = "rejected"        # Audio unusable

class DenoiseStatus(str, Enum):
    NOT_NEEDED = "not_needed"    # Default
    FLAGGED = "flagged"          # User requested cleanup
    QUEUED = "queued"            # Night Shift script picked it up
    PROCESSED = "processed"      # DeepFilterNet finished
```

#### B. The Users & Channels

```python
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True) # e.g., "Dat", "Alice"
    role: UserRole = Field(default=UserRole.ANNOTATOR)
    
    # Relationships
    uploaded_videos: List["Video"] = Relationship(back_populates="uploader")
    locked_chunks: List["Chunk"] = Relationship(back_populates="locker")

class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    url: str = Field(unique=True) # Constraint: No duplicate channels
    
    videos: List["Video"] = Relationship(back_populates="channel")
```

#### C. The Video (Ingestion Layer)

```python
class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(foreign_key="channel.id")
    uploaded_by_id: int = Field(foreign_key="user.id")
    
    # Metadata
    title: str
    duration_seconds: int
    
    # Constraint: Duplicate Prevention
    # If someone tries to download a URL that exists here, the script REJECTS it.
    original_url: str = Field(unique=True) 
    
    # File Path (No Ambiguity)
    # Stored as relative path: "raw/video_{id}.m4a"
    # The Backend prepends "/mnt/data/" at runtime.
    file_path: str 
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    channel: Channel = Relationship(back_populates="videos")
    uploader: User = Relationship(back_populates="uploaded_videos")
    chunks: List["Chunk"] = Relationship(back_populates="video")
```

#### D. The Chunk (Workflow Layer)

This is the most critical table for the Frontend workflow.

```python
class Chunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key="video.id")
    
    # Ordering
    chunk_index: int # 0, 1, 2... used for Absolute Time calculation
    
    # File Path
    # Stored as relative path: "chunks/video_{id}/chunk_{index}.wav"
    audio_path: str 
    
    # State Management
    status: ProcessingStatus = Field(default=ProcessingStatus.PENDING)
    denoise_status: DenoiseStatus = Field(default=DenoiseStatus.NOT_NEEDED)
    
    # Concurrency Control (The "Ghost Lock")
    locked_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    lock_expires_at: Optional[datetime] = Field(default=None) # Cleanup for crashed sessions
    
    # Relationships
    video: Video = Relationship(back_populates="chunks")
    locker: Optional[User] = Relationship(back_populates="locked_chunks")
    segments: List["Segment"] = Relationship(back_populates="chunk")
```

#### E. The Segment (Data Layer)

This table stores the training data. **Crucially, it uses Relative Time.**

```python
class Segment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: int = Field(foreign_key="chunk.id")
    
    # Timestamps (RELATIVE to the Chunk file)
    # 0.0s = Start of the 5-minute .wav file
    # Example: start=4.5 means 4.5 seconds into the chunk.
    start_time_relative: float 
    end_time_relative: float
    
    # The Content
    transcript: str # Original code-switched text
    translation: str # Vietnamese translation
    
    # Quality Control
    is_verified: bool = Field(default=False) # Checkbox on Frontend
    
    chunk: Chunk = Relationship(back_populates="segments")
```

### 2.3 System Constraints & Logic

#### A. The "Ghost Lock" Logic (Concurrency)

Since we operate in a team, we must prevent two people from editing the same chunk.

1.  **Acquiring Lock:** When a user opens a Chunk, the Backend checks `locked_by_user_id`.
    *   If `None`: Set `locked_by_user_id = CurrentUser` and `lock_expires_at = Now + 30 mins`.
    *   If Matches `CurrentUser`: Refresh `lock_expires_at`.
    *   If Matches `OtherUser`: Return `403 Forbidden` (Frontend shows "Locked by Friend A").
2.  **Stale Locks:** If a user closes their laptop without saving, the lock remains.
    *   **Logic:** Any request checking for locks will treat a lock as `NULL` if `lock_expires_at < CurrentTime`.

#### B. Unique Ingestion

To prevent storage bloat and duplicate work:

*   **Constraint:** `Video.original_url` is Unique.
*   **Workflow:** The Ingestion Script **must** query `GET /api/videos/check?url={youtube_url}` before running `yt-dlp`. If it returns True, the download is skipped.

#### C. Relative vs. Absolute Time

*   **Database Storage:** Always **Relative** (0s - 305s). This matches the audio player on the Frontend perfectly.
*   **Export Calculation:** Absolute time is calculated only during the generation of `manifest.tsv`:
    $$AbsoluteTime = (ChunkIndex \times 300) + RelativeTime$$
    (Note: 300 seconds = 5 minutes. We ignore the overlap duration in the base offset calculation, handling it via the Stitching Algorithm).

**Critique:** This schema is normalized and type-safe. By using Enums for status, we prevent typos like "proccesing" vs "processing". By enforcing `unique=True` on URLs at the database level, we protect the system from accidental double-uploads even if the Python script fails.

---

## 3. Ingestion & Pre-Processing Strategy

### 3.1 Ingestion Workflow (Client-Side)

The ingestion process is handled by a local Python GUI script (`ingest_gui.py`) distributed to all team members. This script ensures that no "dubbed" or duplicate audio ever reaches the server.

**The 3-Tab GUI Architecture:**

The ingestion GUI uses a **tabbed interface** with three distinct modes for different ingestion workflows:

| Tab | Name | Purpose | Input Type |
| :--- | :--- | :--- | :--- |
| 1 | **Video URLs** | Download individual videos | Multi-line text (comma/newline separated URLs) |
| 2 | **Playlists** | Download entire playlists | Multi-line text (comma/newline separated playlist URLs) |
| 3 | **Channel** | Browse and select from a channel | Single channel URL with video browser |

**Key Features:**

*   **Auto-Channel Detection:** The GUI automatically extracts channel metadata from fetched videos and creates the channel in the database if it doesn't exist (`POST /api/channels`).
*   **Global Progress Bar:** Displays "Downloaded 5/23 videos" with counts for success (✓), failed (✗), and skipped (⏭).
*   **Error Summary:** At batch completion, logs a summary of all failed videos with error messages.
*   **Bulk Duplicate Check:** "Check Duplicates" validates all selected videos against `GET /api/videos/check` before download.

**The Data Flow:**
User Selection → Tab Input → Fetch Metadata → Auto-Channel Detection → Validation API → yt-dlp Download → Upload to Server

#### A. Authentication (The "Honor System")

To track `uploaded_by_id` without complex login systems:

1.  **Startup:** The script requests `GET /api/users` from the backend.
2.  **Prompt:** A dropdown appears: *"Select your name: [Chien, May, VeeAnh]"*.
3.  **Session:** The selected `user_id` is stored in memory and attached to every upload request header (`X-User-ID`).

#### B. Channel Auto-Detection

All three tabs use **automatic channel detection**:

1.  **Metadata Extraction:** When videos are fetched, the GUI extracts `channel_name` and `channel_url` from the first video's metadata.
2.  **Database Check:** Calls `GET /api/channels/by-url?url={channel_url}` to check if channel exists.
3.  **Auto-Creation:** If not found, calls `POST /api/channels` with the extracted name and URL.
4.  **UI Feedback:** The channel label updates to show "Vietcetera (ID: 3)" in green when successfully detected.

```python
# API Functions for Channel Management
def get_or_create_channel(name: str, url: str) -> Optional[dict]:
    """Get existing channel by URL, or create a new one."""
    # 1. Try to find existing
    resp = requests.get(f"{API_BASE}/channels/by-url", params={"url": url})
    if resp.status_code == 200:
        return resp.json()
    
    # 2. Create new channel
    resp = requests.post(f"{API_BASE}/channels", json={"name": name, "url": url})
    if resp.status_code == 201:
        return resp.json()
    
    return None
```

#### C. Validation (Duplicate Prevention)

Before invoking `yt-dlp`, the script checks if the video already exists in our database.

*   **Action:** User clicks "Check Duplicates" button.
*   **Request:** `GET /api/videos/check?original_url= ...` for each selected video.
*   **Logic:**
    *   If `exists=True`: Mark status as "⚠️ Duplicate" and skip during download.
    *   If `exists=False`: Mark status as "✓ OK" and proceed.

#### D. Error Handling Strategy

Bulk operations use **skip-and-continue** semantics:

*   **On Failure:** Log the error, mark video as "✗ {error}", increment failed counter, continue to next video.
*   **On Completion:** Print summary showing success/failed/skipped counts and list all failed videos with their error messages.
*   **No Halt:** A single failure does not stop the batch; all selected videos are attempted.

### 3.2 yt-dlp Configuration (Code-First)

We use a strict configuration to force the download of the **original audio track** (Vietnamese) and reject auto-generated dubs.

```python
# ingestion/downloader.py
import yt_dlp

def get_yt_dlp_config(output_dir: Path, video_id: str):
    """
    Get strict yt-dlp configuration for Vietnamese audio.
    
    Note:
        format_sort uses COLON syntax for preferences (field:value).
        See: https://github.com/yt-dlp/yt-dlp#sorting-formats
    """
    return {
        # 1. Format Selection:
        # Prioritize Vietnamese audio, then AAC codec, then bitrate
        # CRITICAL: Use colon (:) not equals (=) in format_sort!
        'format': 'bestaudio/best',
        'format_sort': ['lang:vi', 'acodec:aac', 'abr'],

        # 2. Output Template:
        'outtmpl': str(output_dir / f'{video_id}.%(ext)s'),

        # 3. Post-Processing:
        # Convert to standardized m4a (AAC)
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
            'preferredquality': '128',
        }],

        # 4. Metadata:
        'writeinfojson': True,
        'writethumbnail': False,

        # 5. Silence & Safety:
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,  # Skip private videos without crashing
    }
```

### 3.3 Server-Side Processing (The Watcher)

Once the client uploads the file to the server, the server-side pipeline takes over.

#### A. Directory Structure (No Ambiguity)

The backend mounts the storage at `/mnt/data/project_speech`. All paths in the database are relative to this root.

```plaintext
/mnt/data/project_speech/
├── raw/                      # <-- Uploads land here
│   ├── video_101.m4a
│   └── video_102.m4a
├── chunks/                   # <-- FFmpeg output
│   ├── video_101/
│   │   ├── chunk_000.wav     # (00:00 - 05:05)
│   │   ├── chunk_001.wav     # (05:00 - 10:05)
│   │   └── ...
├── spectrograms/             # <-- Cached images for UI (Optional)
└── logs/                     # <-- Pipeline logs
```

#### B. The Chunking Logic (FFmpeg)

We do **not** use the standard `-f segment` command because it does not support overlapping easily. Instead, we use a Python loop to invoke ffmpeg precisely.

**The Algorithm:**

1.  **Chunk Duration:** 300 seconds (5 minutes).
2.  **Overlap:** 5 seconds.
3.  **Logic:**
    *   Chunk 0: Start 0, Duration 305.
    *   Chunk N: Start N * 300, Duration 305.

**The Processing Script:**

```python
# processing/chunker.py
import subprocess
import os

CHUNK_LENGTH = 300 # 5 minutes
OVERLAP = 5        # 5 seconds

def process_video_into_chunks(video_id: int, input_path: str, output_dir: str):
    """
    Spawns FFmpeg processes to split audio with overlap.
    """
    # 1. Get total duration (using ffprobe)
    total_duration = get_duration(input_path) 
   
    current_start = 0
    chunk_index = 0
    
    while current_start < total_duration:
        # Calculate duration for this segment (300 + 5 = 305s)
        # Unless it's the very end of the file.
        duration = CHUNK_LENGTH + OVERLAP
        
        output_filename = f"chunk_{chunk_index:03d}.wav"
        output_full_path = os.path.join(output_dir, output_filename)
        
        # 2. The FFmpeg Command
        # -ss : Start time
        # -t  : Duration
        # -ac 1 : Convert to Mono (Crucial for ASR)
        # -ar 16000 : Resample to 16kHz (Standard for Gemini/Whisper)
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ss", str(current_start),
            "-t", str(duration),
            "-ac", "1",
            "-ar", "16000",
            output_full_path
        ]
        
        subprocess.run(cmd, check=True)
        
        # 3. Database Entry
        # Create the Chunk record in DB with status="pending"
        create_chunk_record(video_id, chunk_index, output_filename)
        
        # 4. Advance cursor
        # Move forward by 300s (NOT 305s, to create the overlap)
        current_start += CHUNK_LENGTH
        chunk_index += 1
```

### 3.4 Separation of Concerns Note

*   **Client Script:** Handles "Garbage In" prevention (Duplicates, Dubs).
*   **Server Script:** Handles normalization (16kHz Mono) and logical splitting.
*   **Database:** Records the existence of `chunk_001.wav` but does **not** yet know what text is inside it. That is the job of the Gemini Worker (Phase 4).

**Critique:** This strategy moves the complexity of "Audio Formatting" (Mono, 16kHz) to the server. This is safer than relying on 3 different friends having the correct FFmpeg version installed on their laptops. The server acts as a standardizing funnel.

---

## 4. The API & Backend Logic

### 4.1 Overview

The Backend is built with **FastAPI**. It is stateless, meaning it relies entirely on the PostgreSQL database for state.

**Base URL:** `http://{TAILSCALE_IP}:8000/api`

### 4.2 Authentication (The "Honor System" Middleware)

Since we are a trusted team of 3, we use **Identity Assertion** via HTTP Headers rather than OAuth.

**The Mechanism:**

1.  **Frontend/GUI:** Sends header `X-User-ID: 2` with every request.
2.  **Backend:** A Dependency Injector validates this ID against the User table.

```python
# auth/deps.py
from fastapi import Header, HTTPException, Depends
from sqlmodel import Session

async def get_current_user(
    x_user_id: int = Header(...), 
    session: Session = Depends(get_session)
) -> User:
    """
    Validates that the user ID in the header actually exists.
    """
    user = session.get(User, x_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid User ID")
    return user
```

### 4.3 Endpoint Specifications

#### A. Channel Management (Ingestion Support)

**Goal:** Support auto-channel-detection in the ingestion GUI.

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `GET /api/channels` | GET | List all channels (dropdown population) |
| `GET /api/channels/by-url?url=...` | GET | Find channel by YouTube URL |
| `POST /api/channels` | POST | Create new channel (auto-creation) |
| `GET /api/channels/{id}` | GET | Get channel by ID |

```python
# routers/users.py (Channel endpoints)

@router.get("/channels/by-url", response_model=ChannelResponse)
def get_channel_by_url(
    url: str = Query(...),
    session: Session = Depends(get_session)
):
    """Find a channel by its YouTube URL."""
    channel = session.exec(select(Channel).where(Channel.url == url)).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.post("/channels", response_model=ChannelResponse, status_code=201)
def create_channel(
    data: ChannelCreate,
    session: Session = Depends(get_session)
):
    """Create a new YouTube source channel."""
    # Check for duplicate URL
    existing = session.exec(select(Channel).where(Channel.url == data.url)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Channel already exists (ID: {existing.id})")
    
    channel = Channel(name=data.name, url=data.url)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return channel
```

#### B. Fetching Work (GET /chunks)

**Goal:** Annotators need to find the next "Available" chunk to work on without stepping on each other's toes.

**Logic:**

1.  **Filter:** Find all chunks where status is `REVIEW_READY` (AI finished) OR `IN_REVIEW`.
2.  **Exclusion:** Exclude chunks currently locked by *other* users.
3.  **Sorting:** Prioritize chunks from the same video to maintain context flow.

```python
@router.get("/chunks/next")
def get_next_task(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    # 1. Check if user already has a lock (Unfinished work)
    existing_lock = session.exec(
        select(Chunk).where(Chunk.locked_by_user_id == user.id)
    ).first()
    
    if existing_lock:
        return existing_lock

    # 2. Find next available
    # Status is READY, and Lock is NULL (or expired)
    stmt = (
        select(Chunk)
        .where(Chunk.status == ProcessingStatus.REVIEW_READY)
        .where(Chunk.locked_by_user_id == None)
        .order_by(Chunk.video_id, Chunk.chunk_index)
        .limit(1)
    )
    return session.exec(stmt).first()
```

#### C. The Concurrency Guard (POST /chunks/{id}/lock)

**Goal:** Prevent "Edit Wars."

**Logic:**

1.  **Input:** Chunk ID.
2.  **Check:** Is this chunk locked by someone else?
    *   *Yes:* Return `409 Conflict`.
    *   *No:* Update `locked_by_user_id = user.id`, `lock_expires_at = Now + 30m`.
3.  **Ghost Lock Cleanup:** If `lock_expires_at` is in the past, overwrite it.

#### C. Triggering Operations (POST /chunks/{id}/flag-noise)

**Goal:** Mark audio for the "Night Shift" denoise batch.

```python
@router.post("/chunks/{chunk_id}/flag-noise")
def flag_chunk_for_denoise(
    chunk_id: int,
    session: Session = Depends(get_session)
):
    chunk = session.get(Chunk, chunk_id)
    # Update Status
    chunk.denoise_status = DenoiseStatus.FLAGGED
    session.add(chunk)
    session.commit()
    
    return {"status": "queued_for_night_shift"}
```

### 4.4 Gemini Integration (The Core Processing)

This runs as a background worker (triggered manually or automatically after ingestion).

#### A. The Prompt Engineering

We use a **System Instruction** to enforce strict JSON formatting and timestamps.

**System Prompt:**

```plaintext
You are a professional transcriber for Vietnamese-English Code-Switching audio.
Your task is to output a strictly valid JSON array of segments.

RULES:
1. TIMESTAMPS: Must be relative to the start of the audio file (00:00).
   Format: "MM:SS.mmm" (e.g., "04:05.123").
2. CONTENT: Transcribe exactly what is spoken. Do not summarize.
3. LANGUAGE: Detect Vietnamese and English automatically.
4. TRANSLATION: Provide a Vietnamese translation for every segment.

OUTPUT FORMAT:
[
  {
    "start": "00:00.000",
    "end": "00:05.123",
    "text": "Hello các bạn, hôm nay...",
    "translation": "Xin chào các bạn, hôm nay..."
  }
]
```

#### B. JSON Parsing & Database Injection

**Data Flow:** Gemini API -> Raw Text -> JSON Validator -> Database

**The Python Logic:**

1.  **Call Gemini:** `response = model.generate_content([audio_file, prompt])`.
2.  **Clean Output:** Strip Markdown backticks (`json ... `).
3.  **Parse:** `data = json.loads(cleaned_text)`.
4.  **Convert Time:** Helper function parses "MM:SS.mmm" into float seconds (e.g., "01:30.500" -> 90.5).
5.  **Insert:**

```python
# processing/gemini_worker.py

def save_segments_to_db(chunk_id: int, json_data: list, session: Session):
    for item in json_data:
        # CONVERT: String time -> Float Relative Seconds
        start_seconds = parse_time_string(item["start"])
        end_seconds = parse_time_string(item["end"])
        
        segment = Segment(
            chunk_id=chunk_id,
            start_time_relative=start_seconds, # STORE RELATIVE
            end_time_relative=end_seconds,     # STORE RELATIVE
            transcript=item["text"],
            translation=item["translation"],
            is_verified=False
        )
        session.add(segment)
    
    # Update Chunk Status
    chunk = session.get(Chunk, chunk_id)
    chunk.status = ProcessingStatus.REVIEW_READY
    session.commit()
```

### 4.5 Separation of Concerns: Time Handling

To reiterate the critical design decision:

*   **Frontend/API:** Only ever sees/sends **Relative Seconds** (0.0 to 305.0).
*   **Database:** Stores **Relative Seconds**.
*   **Export Script:** The **ONLY** place where `chunk_index * 300` is added.

**Why?** If Gemini hallucinates a timestamp like "05:10" in a 5-minute file, the validation logic is simple: if `end_time > 305`: reject. If we used absolute timestamps (e.g., "1:05:10"), validation would require complex queries joining the Video table.

---

## 5. Frontend: The Annotation Workbench

### 5.1 Tech Stack & Overview

The frontend is a Single Page Application (SPA) built with **React (Vite)**. It communicates with the FastAPI backend via REST.

*   **Core Library:** `wavesurfer.js` (Audio Visualization) + `wavesurfer.js-regions` (Segment manipulation).
*   **UI Framework:** Material UI (MUI) or Ant Design (for dense data tables).
*   **State Management:** React Query (TanStack Query) for handling API server state and caching.

**The "Relative Time" Visual Contract:**
The Frontend never calculates absolute time.

*   **Input:** The player loads `chunk_05.wav` (Duration: 5m 05s).
*   **Display:** The timeline starts at 00:00 and ends at 05:05.
*   **Data:** A timestamp of 10.5 means "10.5 seconds from the start of this file."

### 5.2 Layout Specifications

The Workbench is divided into three vertical zones to optimize vertical screen real estate.

#### Zone A: The Control Header (Fixed Top)
Contains global actions for the specific chunk.

*   **Left:** Breadcrumbs (Dashboard > Channel Name > Video 01 > Chunk #5).
*   **Center:**
    *   **Denoise Toggle:** A generic button `[ 🔊 Flag as Noisy ]`.
        *   *Active State (Orange):* Audio is noisy.
        *   *Inactive State (Gray):* Audio is clean.
    *   **Lock Status:** "🔒 Locked by You" (Green) or "🔒 Locked by Dat" (Red).
*   **Right:** `[ Save Changes ]` (Primary Button), `[ Mark as Finished ]`.

#### Zone B: The Visualizer (Top 30%)
A large, zoomable waveform.

*   **Library:** `wavesurfer.js`.
*   **Regions:** Semi-transparent colored boxes overlaid on the waveform representing segments.
*   **Interaction:**
    *   **Drag Region:** Moves `start_time` and `end_time` together.
    *   **Resize Region Edge:** Adjusts just start or end.
    *   **Click Region:** Loops that specific segment.

#### Zone C: The Editor Table (Bottom 70% - Scrollable)
A dense list of segments synced to the waveform regions.

| Check | Play | Start | End | Transcript (Code-Switch) | Translation (Vietnamese) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `[x]` | `[▶]` | 00:05.1 | 00:09.2 | [Input Text] | [Input Text] |

### 5.3 Waveform Logic & Implementation

The critical link between the visual waveform and the text table is the **Region ID**.

**Data Flow:**
API Load -> React State -> Wavesurfer Regions

**Code-First Implementation Logic:**

```javascript
// Logic for syncing Regions (Visual) with Segments (Data)
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';

// 1. Initialization
const ws = WaveSurfer.create({
    container: '#waveform',
    url: '/api/v1/static/chunks/video_123/chunk_05.wav', // Backend mounts this path
    plugins: [
        RegionsPlugin.create() // Enable the region plugin
    ]
});

// 2. Load Segments from API
const segments = apiResponse.data; // [{id: 101, start: 5.1, end: 9.2, ...}]

// 3. Render Regions
segments.forEach(seg => {
    ws.plugins.regions.addRegion({
        id: seg.id.toString(), // CRITICAL: Link Region ID to DB Segment ID
        start: seg.start_time_relative,
        end: seg.end_time_relative,
        color: 'rgba(0, 0, 255, 0.1)',
        drag: true,
        resize: true
    });
});

// 4. Handle User Interaction (The "Write" Path)
ws.plugins.regions.on('region-updated', (region) => {
    // When user stops dragging a box
    updateReactState(region.id, {
        start: region.start,
        end: region.end
    });
    // Triggers "Unsaved Changes" flag
});
```

### 5.4 Key Feature Implementation

#### A. The "Flag for Denoise" Toggle

*   **Visual:** A toggle button.
*   **Action:**
    1.  User clicks Toggle.
    2.  Frontend sends: `POST /api/chunks/{id}/flag-noise`.
    3.  **Optimistic UI:** Button turns Orange immediately.
    4.  **Background:** Backend updates `denoise_status = 'flagged'`.

#### B. The "Verify Segment" Checkbox

*   **Visual:** A checkbox at the start of every table row.
*   **Logic:**
    *   **Default:** Unchecked (False) when loaded from Gemini.
    *   **User Action:** Annotator listens, corrects text, clicks Checkbox.
    *   **Data:** Updates local React state `segment.is_verified = true`.
    *   **Validation:** The "Mark Chunk as Finished" button is **Disabled** until 100% of segments are verified.

#### C. Keyboard Shortcuts (Productivity)

We hijack the browser's standard events to speed up workflow.

| Shortcut | Scope | Action |
| :--- | :--- | :--- |
| `Ctrl + Space` | Global | Play/Pause current segment loop. |
| `Ctrl + Enter` | Text Input | Save current row and move focus to next row. |
| `Ctrl + ArrowRight` | Global | Skip forward 5 seconds. |
| `Ctrl + D` | Global | Toggle "Denoise" flag. |

### 5.5 Data Synchronization Strategy

To prevent data loss:

1.  **Auto-Save (Debounced):**
    *   When a user stops typing for 2 seconds, trigger `PUT /api/segments/{id}`.
2.  **Explicit Save:**
    *   The "Save Changes" button sends the entire state of the chunk (all segments) to `PUT /api/chunks/{id}/sync`.
3.  **Locking Lifecycle:**
    *   **Mount:** `POST /chunks/{id}/lock` -> Returns `200 OK` (Editable) or `409 Conflict` (Read-Only Mode).
    *   **Unmount:** `POST /chunks/{id}/unlock`.

**Critique:** This design minimizes complex math on the client. By mapping the database ID directly to the Wavesurfer Region ID, we create a robust 1:1 link. If the user drags a box, the table updates. If the user edits the timestamp numbers in the table, the box moves.

### 5.6 Frontend Navigation Architecture

The application uses a **5-Tab Navigation System** with horizontal tabs in the header. Each tab corresponds to a distinct functional area.

#### Tab Structure

| Tab | Page Component | Mockup Reference | Description |
| :--- | :--- | :--- | :--- |
| **Dashboard** | `DashboardPage.tsx` | gemini_ui_1 | Channel overview with stats, system metrics |
| **Channel** | `ChannelPage.tsx` | gemini_ui_2 | Video list (dynamic tab, appears when channel selected) |
| **Annotation** | `WorkbenchPage.tsx` | gemini_ui_3, gemini_ui_4 | Waveform + segment editing workbench |
| **Processing** | `ProcessingPage.tsx` | gemini_ui_5 | Denoise queue management, batch processing |
| **Export** | `ExportPage.tsx` | gemini_ui_7 | Dataset export configuration, progress |
| **Settings** | `SettingsPage.tsx` | - | User management, system info |

#### Navigation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  User Selection Screen (gemini_ui_6)                             │
│  → Select user profile to login                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Main App with Tab Navigation                                    │
├─────────────────────────────────────────────────────────────────┤
│  [Dashboard] [Channel*] [Annotation] [Processing] [Export] [Settings] │
└─────────────────────────────────────────────────────────────────┘
        │            │              │            │          │
        ▼            │              ▼            ▼          ▼
   Channel Grid      │         Workbench    Queue Table   Export
   + Stats Panel     │                                    Config
        │            │
        ▼ (click)    │
   ─────────────────►│
   Opens Channel Tab │◄── Shows video list for selected channel
                     │
                     ▼ (click video)
                  Opens Annotation tab with video preloaded
```

*The Channel tab is **dynamic** - it only appears when a channel is selected from Dashboard.

#### State Management

The `App.tsx` component manages:
- `currentTab`: Active tab identifier
- `selectedChannel`: Currently selected channel for Channel tab
- `selectedVideoId` / `selectedChunkId`: Preselection for cross-tab navigation

#### Cross-Tab Navigation

The following callbacks enable seamless navigation between tabs:

1. **Dashboard → Channel**: `onChannelSelect(channel)` → Sets channel, switches to Channel tab
2. **Channel → Annotation**: `onVideoSelect(videoId)` → Sets video, switches to Annotation tab

---

## 6. Operations: The "Night Shift" & Export

### 6.1 Batch Denoising (The "Night Shift")

To allow annotators to flag noisy audio without breaking their flow, we treat denoising as an asynchronous batch job. This is triggered manually via the API (e.g., at the end of the day) and runs on the server.

**The Workflow:**
Annotator Flag -> Database Queue -> Background Script -> File Replacement

#### A. The Trigger & Logging

The backend uses Python’s logging module to create a persistent audit trail.

**Log Location:** `/mnt/data/project_speech/logs/server_processing.log`

```python
# operations/logger_config.py
import logging

logging.basicConfig(
    filename='/mnt/data/project_speech/logs/server_processing.log',
    level=logging.INFO,
    format='%(asctime)s - [NIGHT_SHIFT] - %(levelname)s - %(message)s'
)
```

#### B. The Processing Logic (Code-First)

This script runs inside a FastAPI BackgroundTask. It processes chunks sequentially to avoid overloading the GPU.

```python
# operations/denoiser.py
import subprocess
import os
from sqlmodel import Session, select

def run_batch_denoise(session: Session):
    """
    Scans DB for FLAGGED chunks and runs DeepFilterNet.
    """
    logging.info("Starting Batch Denoise Job...")
    
    # 1. Fetch Queue
    stmt = select(Chunk).where(Chunk.denoise_status == DenoiseStatus.FLAGGED)
    chunks = session.exec(stmt).all()
    
    if not chunks:
        logging.info("No chunks flagged. Exiting.")
        return

    for chunk in chunks:
        try:
            logging.info(f"Processing Chunk {chunk.id} ({chunk.audio_path})...")
            
            # 2. Mark as Processing (Lock it)
            chunk.denoise_status = DenoiseStatus.QUEUED
            session.add(chunk)
            session.commit()
            
            # 3. Construct Paths
            # Input: /mnt/data/project_speech/chunks/vid_1/chunk_05.wav
            input_abs_path = os.path.join(DATA_ROOT, chunk.audio_path)
            # Output: /mnt/data/project_speech/chunks/vid_1/chunk_05_clean.wav
            output_abs_path = input_abs_path.replace(".wav", "_clean.wav")
            
            # 4. Execute DeepFilterNet (Shell Command)
            # Assumes 'deepFilter' is in PATH. 
            cmd = ["deepFilter", input_abs_path, "-o", output_abs_path]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            
            # 5. Atomic Swap (The "No Ambiguity" Path Update)
            # We update the DB to point to the CLEAN file.
            # The relative path changes from "chunk_05.wav" to "chunk_05_clean.wav"
            old_path = chunk.audio_path
            new_relative_path = old_path.replace(".wav", "_clean.wav")
            
            chunk.audio_path = new_relative_path
            chunk.denoise_status = DenoiseStatus.PROCESSED
            session.add(chunk)
            session.commit()
            
            logging.info(f"Success: Chunk {chunk.id} updated to {new_relative_path}")
            
        except Exception as e:
            logging.error(f"Failed Chunk {chunk.id}: {str(e)}")
            chunk.denoise_status = DenoiseStatus.FLAGGED # Revert to flag for retry
            session.add(chunk)
            session.commit()
            
    logging.info("Batch Denoise Job Completed.")
```

### 6.2 The Export Algorithm (The Final Assembly)

This is the **only** place in the entire pipeline where Absolute Time is calculated. The script reads the database, resolves overlaps, cuts the physical audio clips, and generates the manifest.

#### A. The "Stitching" Logic

We deal with the 5-second overlap (300s to 305s) using a strict "Ownership Rule."

**The Rule:**

*   **Chunk N** owns the timeline from 00:00 to 05:00 (Relative).
*   **Chunk N+1** starts at 05:00 absolute.
*   **Action:** If a segment in Chunk N starts at 05:01 (Relative), it is **discarded** because Chunk N+1 will contain that same audio starting at 00:01 (Relative).
*   **Exception:** The **Last Chunk** keeps everything until the file ends.

#### B. The Export Script (Python)

```python
# operations/exporter.py
import csv
import subprocess

def export_dataset(session: Session, output_dir: str):
    """
    Generates training data: small clips + manifest.tsv
    """
    # 1. Setup Manifest
    manifest_path = os.path.join(output_dir, "manifest.tsv")
    clips_dir = os.path.join(output_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    
    with open(manifest_path, 'w', newline='', encoding='utf-8') as tsvfile:
        writer = csv.writer(tsvfile, delimiter='\t')
        # Header
        writer.writerow(['audio_filepath', 'text', 'translation', 'duration'])
        
        # 2. Iterate Videos
        videos = session.exec(select(Video)).all()
        
        for video in videos:
            # Sort chunks to ensure time continuity
            sorted_chunks = sorted(video.chunks, key=lambda c: c.chunk_index)
            total_chunks = len(sorted_chunks)
            
            for i, chunk in enumerate(sorted_chunks):
                if chunk.status != ProcessingStatus.APPROVED:
                    continue # Skip unverified chunks
                
                input_audio = os.path.join(DATA_ROOT, chunk.audio_path)
                
                # 3. Iterate Segments
                for segment in chunk.segments:
                    if not segment.is_verified:
                        continue
                        
                    # --- THE STITCHING LOGIC ---
                    # Drop overlap unless it's the last chunk
                    if i < (total_chunks - 1) and segment.start_time_relative >= 300.0:
                        continue 
                    
                    # 4. Cut the Clip (Physical Generation)
                    # We cut directly from the Chunk file using relative times.
                    clip_filename = f"{video.id}_{chunk.chunk_index}_{segment.id}.wav"
                    clip_path = os.path.join(clips_dir, clip_filename)
                    
                    # FFmpeg: Extract specific region without re-encoding if possible
                    # But for safety/precision, we re-encode to ensuring perfect headers
                    cmd = [
                        "ffmpeg", "-y", "-i", input_audio,
                        "-ss", str(segment.start_time_relative),
                        "-to", str(segment.end_time_relative),
                        "-ac", "1", "-ar", "16000",
                        clip_path
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    # 5. Write to Manifest
                    duration = segment.end_time_relative - segment.start_time_relative
                    writer.writerow([
                        os.path.abspath(clip_path), # Absolute system path
                        segment.transcript,
                        segment.translation,
                        f"{duration:.2f}"
                    ])
                    
    print(f"Export Complete. Manifest at: {manifest_path}")
```

### 6.3 Separation of Concerns Summary

*   **Frontend:** Sees 05:01.
*   **Database:** Stores 05:01.
*   **Export Script:** Sees 05:01 -> Recognizes it is > 05:00 -> **Drops it** to avoid duplication with the next chunk.

---

**Completion:**
This concludes the Technical Specification Document.

We have defined the Architecture, Database, Ingestion, API, Frontend, and Operations.
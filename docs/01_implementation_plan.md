# **Technical Specification: Vietnamese-English Code-Switching Pipeline**
Version: 1.0
---

## **1\. Executive Summary & Architecture**

### **1.1 Project Objective**

To construct a high-quality, verified Speech Translation dataset (Vietnamese-English Code-Switching) consisting of **150+ hours** of audio. The pipeline automates the "heavy lifting" (transcription/translation) using **Gemini 2.5 Flash**, leaving human annotators to focus solely on verification and fine-tuning.

**Final Deliverables:**

1. **Audio Segments:** 2-25s .wav clips (16kHz, Mono).  
2. **Manifest File:** A manifest.tsv containing absolute paths, transcripts, and translations suitable for model training.

### **1.2 High-Level Architecture (The Stack)**

We utilize a **3-Tier Client-Server Architecture** secured via **Tailscale**. This ensures that while the database and heavy storage live on one powerful machine (The Server), annotators can work from lightweight laptops (The Clients).

| Tier | Component | Technology | Responsibility |
| :---- | :---- | :---- | :---- |
| **Presentation** | **Frontend** | React (Vite) \+ Wavesurfer.js | Visualizes waveforms, manages user interactions, handles "Relative Time" logic. |
| **Logic** | **Backend** | FastAPI (Python 3.10+) | Orchestrates file locking, mounts the file system, executes background Denoising tasks. |
| **Data** | **Database** | PostgreSQL | Stores metadata, user states, and transcription text. **The Single Source of Truth.** |
| **Storage** | **File System** | Local Disk \+ Google Drive | Stores physical .m4a and .wav files. Synced for backup. |

### 

### **1.3 The "Data Factory" Lifecycle (Visual Data Flow)**

Data moves through the system in four strict stages. Every stage is a "Gate" that the data must pass through.

#### **Stage 1: Ingestion (Distributed \-\> Centralized)**

* **Input:** User runs ingest\_gui.py on their local laptop.  
* **Validation:** Script checks yt-dlp metadata for original\_url to prevent duplicates.  
* **Process:** yt-dlp downloads audio (Config: format\_sort=\['lang=vi', 'orig'\]).  
* **Storage:** File is uploaded via API to Server Path: /mnt/data/raw/{video\_id}.m4a. Metadata inserted into Video table.

#### **Stage 2: Core Processing (The "Meat Grinder")**

* **Input:** Server detects new file in /mnt/data/raw.  
* **Process A (Chunking):** FFmpeg splits audio into 5-minute chunks with 5-second overlap.  
* **Process B (AI):** Gemini 2.5 Flash generates JSON transcripts for each chunk.  
* **Storage:**  
  * Audio: /mnt/data/chunks/{video\_id}/{chunk\_id}.wav  
  * Text: Parsed JSON inserted into Segment table (using **Relative Time**).

#### **Stage 3: Human Review (The Annotation Loop)**

* **Input:** User requests "Next Pending Chunk" via React Frontend.  
* **Locking:** Backend sets Chunk.locked\_by\_user\_id \= {user\_id}.  
* **Action:** User corrects text, adjusts timestamps, or toggles [Flag for Denoise].  
* **Storage:** Updates Segment table. Status set to APPROVED or FLAGGED.

#### **Stage 4: Operations & Export (The "Night Shift")**

* **Process A (Denoise):** Background script scans DB for denoise\_status="flagged". Runs DeepFilterNet on specific chunks.  
* **Process B (Export):** Script reads APPROVED segments.  
* **Logic:** Converts **Relative Time** (00:04) \-\> **Absolute Time** (05:04). Handles 5s overlap stitching.  
* **Output:** Generates dataset/manifest.tsv.

### **1.4 Key Architectural Decisions**

#### **A. The "Relative Time" Standard**

To prevent math errors during the manual review process, the Database and Frontend operate **exclusively** in "Chunk Time."

* **The Rule:** A timestamp is always relative to the start of the 5-minute chunk file.  
* **Example:** If a user marks a segment at 00:10.00, it means 10 seconds into the .wav file.  
* **Why:** We do not want the Frontend to calculate (Chunk\_Index \* 300\) \+ 10. That calculation happens **once**, purely in the final Export script.

#### **B. Directory Structure (The "File System")**

We do not scatter files. The backend mounts a single root directory.

* **Root:** /mnt/data/project\_speech  
  * ├── raw/ (Original 1-hour .m4a downloads)  
  * ├── chunks/ (The working directory)  
    * ├── video\_{id}/  
      * ├── chunk\_00.wav  
      * ├── chunk\_01.wav  
  * ├── processed/ (Denoised versions, if generated)  
  * ├── logs/ (Server processing logs)

#### **C. Concurrency Control (The "Lock")**

Since we have 3 users and 1 database:

* **Constraint:** A user can only edit a chunk if Chunk.locked\_by\_user\_id is either NULL or their own ID.  
* **Enforcement:** The FastAPI backend rejects POST /save requests if the lock belongs to someone else.

**Critique for the Team**: This architecture favors consistency over speed. We split the "Creation" (Gemini) from the "Review" (React) to ensure that if the AI fails, the human workflow is not blocked. We use Postgres to manage the state because files on disk cannot tell us "User A is working on this right now."

Here is **Section 2: Database Schema** of your Technical Specification Document.

This section defines the "Brain" of your operations. We use **PostgreSQL** with **SQLModel** (a wrapper around SQLAlchemy) to ensure strict typing and relational integrity.

---

## **2\. Database Schema**

### **2.1 Overview & Entity Relationships**

The database serves as the Single Source of Truth (SSoT) for the pipeline. It manages the hierarchy of data and the state of the workflow (who is doing what).

**The Hierarchy:**

1. **Channel:** A YouTube source (e.g., "Vietcetera").  
2. **Video:** A specific episode downloaded from that channel.  
3. **Chunk:** A 5-minute slice of that video (The "Unit of Work").  
4. **Segment:** A 2-25 second clip inside a chunk (The "Training Data").

**Key Relationships:**

* **One-to-Many:** A Channel has many Videos. A Video has many Chunks. A Chunk has many Segments.  
* **User-to-Data:** A User can *upload* many videos. A User can *lock* (edit) only one Chunk at a time.

---

### **2.2 SQLModel Code Definitions**

The following Python code defines the exact structure of the PostgreSQL tables.

#### **A. Enums (The State Machine)**

We use Enums to prevent "Magic Strings" and ensure valid states.

Python

from enum import Enum  
from datetime import datetime  
from typing import Optional, List  
from sqlmodel import SQLModel, Field, Relationship

class UserRole(str, Enum):  
    ADMIN \= "admin"        \# Can delete data / manage users  
    ANNOTATOR \= "annotator" \# Can only edit/review

class ProcessingStatus(str, Enum):  
    PENDING \= "pending"          \# Just created/uploaded  
    PROCESSING \= "processing"    \# Gemini/FFmpeg running  
    REVIEW\_READY \= "review\_ready" \# AI finished, waiting for human  
    IN\_REVIEW \= "in\_review"      \# Currently locked by a user  
    APPROVED \= "approved"        \# Human verified, ready for export  
    REJECTED \= "rejected"        \# Audio unusable

class DenoiseStatus(str, Enum):  
    NOT\_NEEDED \= "not\_needed"    \# Default  
    FLAGGED \= "flagged"          \# User requested cleanup  
    QUEUED \= "queued"            \# Night Shift script picked it up  
    PROCESSED \= "processed"      \# DeepFilterNet finished

#### **B. The Users & Channels**

Python

class User(SQLModel, table=True):  
    id: Optional\[int\] \= Field(default=None, primary\_key=True)  
    username: str \= Field(unique=True, index=True) \# e.g., "Dat", "Alice"  
    role: UserRole \= Field(default=UserRole.ANNOTATOR)  
      
    \# Relationships  
    uploaded\_videos: List\["Video"\] \= Relationship(back\_populates="uploader")  
    locked\_chunks: List\["Chunk"\] \= Relationship(back\_populates="locker")

class Channel(SQLModel, table=True):  
    id: Optional\[int\] \= Field(default=None, primary\_key=True)  
    name: str \= Field(index=True)  
    url: str \= Field(unique=True) \# Constraint: No duplicate channels  
      
    videos: List\["Video"\] \= Relationship(back\_populates="channel")

#### **C. The Video (Ingestion Layer)**

Python

class Video(SQLModel, table=True):  
    id: Optional\[int\] \= Field(default=None, primary\_key=True)  
    channel\_id: int \= Field(foreign\_key="channel.id")  
    uploaded\_by\_id: int \= Field(foreign\_key="user.id")  
      
    \# Metadata  
    title: str  
    duration\_seconds: int  
      
    \# Constraint: Duplicate Prevention  
    \# If someone tries to download a URL that exists here, the script REJECTS it.  
    original\_url: str \= Field(unique=True)   
      
    \# File Path (No Ambiguity)  
    \# Stored as relative path: "raw/video\_{id}.m4a"  
    \# The Backend prepends "/mnt/data/" at runtime.  
    file\_path: str   
      
    created\_at: datetime \= Field(default\_factory=datetime.utcnow)  
      
    \# Relationships  
    channel: Channel \= Relationship(back\_populates="videos")  
    uploader: User \= Relationship(back\_populates="uploaded\_videos")  
    chunks: List\["Chunk"\] \= Relationship(back\_populates="video")

#### **D. The Chunk (Workflow Layer)**

This is the most critical table for the Frontend workflow.

Python

class Chunk(SQLModel, table=True):  
    id: Optional\[int\] \= Field(default=None, primary\_key=True)  
    video\_id: int \= Field(foreign\_key="video.id")  
      
    \# Ordering  
    chunk\_index: int \# 0, 1, 2... used for Absolute Time calculation  
      
    \# File Path  
    \# Stored as relative path: "chunks/video\_{id}/chunk\_{index}.wav"  
    audio\_path: str   
      
    \# State Management  
    status: ProcessingStatus \= Field(default=ProcessingStatus.PENDING)  
    denoise\_status: DenoiseStatus \= Field(default=DenoiseStatus.NOT\_NEEDED)  
      
    \# Concurrency Control (The "Ghost Lock")  
    locked\_by\_user\_id: Optional\[int\] \= Field(default=None, foreign\_key="user.id")  
    lock\_expires\_at: Optional\[datetime\] \= Field(default=None) \# Cleanup for crashed sessions  
      
    \# Relationships  
    video: Video \= Relationship(back\_populates="chunks")  
    locker: Optional\[User\] \= Relationship(back\_populates="locked\_chunks")  
    segments: List\["Segment"\] \= Relationship(back\_populates="chunk")

#### **E. The Segment (Data Layer)**

This table stores the training data. **Crucially, it uses Relative Time.**

Python

class Segment(SQLModel, table=True):  
    id: Optional\[int\] \= Field(default=None, primary\_key=True)  
    chunk\_id: int \= Field(foreign\_key="chunk.id")  
      
    \# Timestamps (RELATIVE to the Chunk file)  
    \# 0.0s \= Start of the 5-minute .wav file  
    \# Example: start=4.5 means 4.5 seconds into the chunk.  
    start\_time\_relative: float   
    end\_time\_relative: float  
      
    \# The Content  
    transcript: str \# Original code-switched text  
    translation: str \# Vietnamese translation  
      
    \# Quality Control  
    is\_verified: bool \= Field(default=False) \# Checkbox on Frontend  
      
    chunk: Chunk \= Relationship(back\_populates="segments")  
---

### **2.3 System Constraints & Logic**

#### **A. The "Ghost Lock" Logic (Concurrency)**

Since we operate in a team, we must prevent two people from editing the same chunk.

1. **Acquiring Lock:** When a user opens a Chunk, the Backend checks locked\_by\_user\_id.  
   * If None: Set locked\_by\_user\_id \= CurrentUser and lock\_expires\_at \= Now \+ 30 mins.  
   * If Matches CurrentUser: Refresh lock\_expires\_at.  
   * If Matches OtherUser: Return 403 Forbidden (Frontend shows "Locked by Friend A").  
2. **Stale Locks:** If a user closes their laptop without saving, the lock remains.  
   * **Logic:** Any request checking for locks will treat a lock as NULL if lock\_expires\_at \< CurrentTime.

#### **B. Unique Ingestion**

To prevent storage bloat and duplicate work:

* **Constraint:** Video.original\_url is Unique.  
* **Workflow:** The Ingestion Script **must** query GET /api/videos/check?url={youtube\_url} before running yt-dlp. If it returns True, the download is skipped.

#### **C. Relative vs. Absolute Time**

* **Database Storage:** Always **Relative** (0s \- 305s). This matches the audio player on the Frontend perfectly.  
* Export Calculation: Absolute time is calculated only during the generation of manifest.tsv:  
  $$AbsoluteTime \= (ChunkIndex \\times 300\) \+ RelativeTime$$  
  (Note: 300 seconds \= 5 minutes. We ignore the overlap duration in the base offset calculation, handling it via the Stitching Algorithm).

Critique: This schema is normalized and type-safe. By using Enums for status, we prevent typos like "proccesing" vs "processing". By enforcing unique=True on URLs at the database level, we protect the system from accidental double-uploads even if the Python script fails.

Here is **Section 3: Ingestion & Pre-Processing Strategy** of your Technical Specification Document.

This section details exactly how data enters the system. It replaces ad-hoc manual downloading with a standardized, reproducible Python workflow that runs on the client machines (Ingestion) and the server (Processing).

---

## **3\. Ingestion & Pre-Processing Strategy**

### **3.1 Ingestion Workflow (Client-Side)**

The ingestion process is handled by a local Python GUI script (ingest\_gui.py) distributed to all team members. This script ensures that no "dubbed" or duplicate audio ever reaches the server.

The Data Flow:

User Selection \-\> Input Links \-\> Validation API \-\> yt-dlp Download \-\> Upload to Server

#### **A. Authentication (The "Honor System")**

To track uploaded\_by\_id without complex login systems:

1. **Startup:** The script requests GET /api/users from the backend.  
2. **Prompt:** A dropdown appears: *"Select your name: \[Dat, Friend A, Friend B\]"*.  
3. **Session:** The selected user\_id is stored in memory and attached to every upload request header.

#### **B. Validation (Duplicate Prevention)**

Before invoking yt-dlp, the script checks if the video already exists in our database.

* **Action:** Script parses the Video ID from the link.  
* **Request:** GET /api/videos/check?original\_url= ...  
* **Logic:**  
  * If 200 OK (True): Display "⚠️ Video already exists. Skipping."  
  * If 404 Not Found (False): Proceed to download.

---

### **3.2 yt-dlp Configuration (Code-First)**

We use a strict configuration to force the download of the **original audio track** (Vietnamese) and reject auto-generated dubs.

Python

\# ingestion/downloader.py

import yt\_dlp

def get\_yt\_dlp\_config(video\_id: str):

    return {

        \# 1\. Format Selection:

        \# Prioritize Vietnamese audio ('lang=vi'). 

        \# If not found, prioritize 'original' source ('orig').

        \# Fallback to best audio available if explicit tags are missing.

        'format': 'bestaudio/best',

        'format\_sort': \['lang=vi', 'orig', 'res:128'\],

        \# 2\. Output Template:

        \# Save temporarily to local disk before upload

        'outtmpl': f'./temp\_downloads/{video\_id}.%(ext)s',

        \# 3\. Post-Processing:

        \# Convert whatever format (webm, m4a) to standardized m4a (AAC)

        \# This ensures compatibility with standard players.

        'postprocessors': \[{

            'key': 'FFmpegExtractAudio',

            'preferredcodec': 'm4a',

            'preferredquality': '128',

        }\],

        \# 4\. Metadata:

        \# Write info.json to parse title, duration, and channel name later.

        'writeinfojson': True,

        'writethumbnail': False,

        \# 5\. Silence & Safety:

        'quiet': True,

        'no\_warnings': True,

        'ignoreerrors': True, \# Skip private videos without crashing the batch

    }

---

### **3.3 Server-Side Processing (The Watcher)**

Once the client uploads the file to the server, the server-side pipeline takes over.

#### **A. Directory Structure (No Ambiguity)**

The backend mounts the storage at /mnt/data/project\_speech. All paths in the database are relative to this root.

Plaintext

/mnt/data/project\_speech/

├── raw/                      \# \<-- Uploads land here

│   ├── video\_101.m4a

│   └── video\_102.m4a

├── chunks/                   \# \<-- FFmpeg output

│   ├── video\_101/

│   │   ├── chunk\_000.wav     \# (00:00 \- 05:05)

│   │   ├── chunk\_001.wav     \# (05:00 \- 10:05)

│   │   └── ...

├── spectrograms/             \# \<-- Cached images for UI (Optional)

└── logs/                     \# \<-- Pipeline logs

#### **B. The Chunking Logic (FFmpeg)**

We do **not** use the standard \-f segment command because it does not support overlapping easily. Instead, we use a Python loop to invoke ffmpeg precisely.

**The Algorithm:**

1. **Chunk Duration:** 300 seconds (5 minutes).  
2. **Overlap:** 5 seconds.  
3. **Logic:**  
   * Chunk 0: Start 0, Duration 305.  
   * Chunk N: Start N \* 300, Duration 305.

**The Processing Script:**

Python

\# processing/chunker.py

import subprocess

import os

CHUNK\_Length \= 300 \# 5 minutes

OVERLAP \= 5        \# 5 seconds

def process\_video\_into\_chunks(video\_id: int, input\_path: str, output\_dir: str):

    """

    Spawns FFmpeg processes to split audio with overlap.

    """

    \# 1\. Get total duration (using ffprobe)

    total\_duration \= get\_duration(input\_path) 

   

    current\_start \= 0

    chunk\_index \= 0

    

    while current\_start \< total\_duration:

        \# Calculate duration for this segment (300 \+ 5 \= 305s)

        \# Unless it's the very end of the file.

        duration \= CHUNK\_LENGTH \+ OVERLAP

        

        output\_filename \= f"chunk\_{chunk\_index:03d}.wav"

        output\_full\_path \= os.path.join(output\_dir, output\_filename)

        

        \# 2\. The FFmpeg Command

        \# \-ss : Start time

        \# \-t  : Duration

        \# \-ac 1 : Convert to Mono (Crucial for ASR)

        \# \-ar 16000 : Resample to 16kHz (Standard for Gemini/Whisper)

        cmd \= \[

            "ffmpeg", "-y",

            "-i", input\_path,

            "-ss", str(current\_start),

            "-t", str(duration),

            "-ac", "1",

            "-ar", "16000",

            output\_full\_path

        \]

        

        subprocess.run(cmd, check=True)

        

        \# 3\. Database Entry

        \# Create the Chunk record in DB with status="pending"

        create\_chunk\_record(video\_id, chunk\_index, output\_filename)

        

        \# 4\. Advance cursor

        \# Move forward by 300s (NOT 305s, to create the overlap)

        current\_start \+= CHUNK\_LENGTH

        chunk\_index \+= 1

### **3.4 Separation of Concerns Note**

* **Client Script:** Handles "Garbage In" prevention (Duplicates, Dubs).  
* **Server Script:** Handles normalization (16kHz Mono) and logical splitting.  
* **Database:** Records the existence of chunk\_001.wav but does **not** yet know what text is inside it. That is the job of the Gemini Worker (Phase 4).

**Critique**: This strategy moves the complexity of "Audio Formatting" (Mono, 16kHz) to the server. This is safer than relying on 3 different friends having the correct FFmpeg version installed on their laptops. The server acts as a standardizing funnel.

---

## **4\. The API & Backend Logic**

### **4.1 Overview**

The Backend is built with **FastAPI**. It is stateless, meaning it relies entirely on the PostgreSQL database for state.

**Base URL:** http://{TAILSCALE\_IP}:8000/api/v1

---

### **4.2 Authentication (The "Honor System" Middleware)**

Since we are a trusted team of 3, we use **Identity Assertion** via HTTP Headers rather than OAuth.

**The Mechanism:**

1. **Frontend:** Sends header X-User-ID: 2 with every request.  
2. **Backend:** A Dependency Injector validates this ID against the User table.

Python

\# auth/deps.py

from fastapi import Header, HTTPException, Depends

from sqlmodel import Session

async def get\_current\_user(

    x\_user\_id: int \= Header(...), 

    session: Session \= Depends(get\_session)

) \-\> User:

    """

    Validates that the user ID in the header actually exists.

    """

    user \= session.get(User, x\_user\_id)

    if not user:

        raise HTTPException(status\_code=401, detail="Invalid User ID")

    return user

---

### **4.3 Endpoint Specifications**

#### **A. Fetching Work (GET /chunks)**

**Goal:** Annotators need to find the next "Available" chunk to work on without stepping on each other's toes.

**Logic:**

1. **Filter:** Find all chunks where status is REVIEW\_READY (AI finished) OR IN\_REVIEW.  
2. **Exclusion:** Exclude chunks currently locked by *other* users.  
3. **Sorting:** Prioritize chunks from the same video to maintain context flow.

Python

@router.get("/chunks/next")

def get\_next\_task(

    user: User \= Depends(get\_current\_user),

    session: Session \= Depends(get\_session)

):

    \# 1\. Check if user already has a lock (Unfinished work)

    existing\_lock \= session.exec(

        select(Chunk).where(Chunk.locked\_by\_user\_id \== user.id)

    ).first()

    

    if existing\_lock:

        return existing\_lock

    \# 2\. Find next available

    \# Status is READY, and Lock is NULL (or expired)

    stmt \= (

        select(Chunk)

        .where(Chunk.status \== ProcessingStatus.REVIEW\_READY)

        .where(Chunk.locked\_by\_user\_id \== None)

        .order\_by(Chunk.video\_id, Chunk.chunk\_index)

        .limit(1)

    )

    return session.exec(stmt).first()

#### **B. The Concurrency Guard (POST /chunks/{id}/lock)**

**Goal:** Prevent "Edit Wars."

**Logic:**

1. **Input:** Chunk ID.  
2. **Check:** Is this chunk locked by someone else?  
   * *Yes:* Return 409 Conflict.  
   * *No:* Update locked\_by\_user\_id \= user.id, lock\_expires\_at \= Now \+ 30m.  
3. **Ghost Lock Cleanup:** If lock\_expires\_at is in the past, overwrite it.

#### **C. Triggering Operations (POST /chunks/{id}/flag-noise)**

**Goal:** Mark audio for the "Night Shift" denoise batch.

Python

@router.post("/chunks/{chunk\_id}/flag-noise")

def flag\_chunk\_for\_denoise(

    chunk\_id: int,

    session: Session \= Depends(get\_session)

):

    chunk \= session.get(Chunk, chunk\_id)

    \# Update Status

    chunk.denoise\_status \= DenoiseStatus.FLAGGED

    session.add(chunk)

    session.commit()

    

    return {"status": "queued\_for\_night\_shift"}

---

### **4.4 Gemini Integration (The Core Processing)**

This runs as a background worker (triggered manually or automatically after ingestion).

#### **A. The Prompt Engineering**

We use a **System Instruction** to enforce strict JSON formatting and timestamps.

**System Prompt:**

Plaintext

You are a professional transcriber for Vietnamese-English Code-Switching audio.

Your task is to output a strictly valid JSON array of segments.

RULES:

1\. TIMESTAMPS: Must be relative to the start of the audio file (00:00).

   Format: "MM:SS.mmm" (e.g., "04:05.123").

2\. CONTENT: Transcribe exactly what is spoken. Do not summarize.

3\. LANGUAGE: Detect Vietnamese and English automatically.

4\. TRANSLATION: Provide a Vietnamese translation for every segment.

OUTPUT FORMAT:

\[

  {

    "start": "00:00.000",

    "end": "00:05.123",

    "text": "Hello các bạn, hôm nay...",

    "translation": "Xin chào các bạn, hôm nay..."

  }

\]

#### **B. JSON Parsing & Database Injection**

**Data Flow:** Gemini API \-\> Raw Text \-\> JSON Validator \-\> Database

**The Python Logic:**

1. **Call Gemini:** response \= model.generate\_content(\[audio\_file, prompt\]).  
2. **Clean Output:** Strip Markdown backticks (json ... ).  
3. **Parse:** data \= json.loads(cleaned\_text).  
4. **Convert Time:** Helper function parses "MM:SS.mmm" into float seconds (e.g., "01:30.500" \-\> 90.5).  
5. **Insert:**

Python

\# processing/gemini\_worker.py

def save\_segments\_to\_db(chunk\_id: int, json\_data: list, session: Session):

    for item in json\_data:

        \# CONVERT: String time \-\> Float Relative Seconds

        start\_seconds \= parse\_time\_string(item\["start"\])

        end\_seconds \= parse\_time\_string(item\["end"\])

        

        segment \= Segment(

            chunk\_id=chunk\_id,

            start\_time\_relative=start\_seconds, \# STORE RELATIVE

            end\_time\_relative=end\_seconds,     \# STORE RELATIVE

            transcript=item\["text"\],

            translation=item\["translation"\],

            is\_verified=False

        )

        session.add(segment)

    

    \# Update Chunk Status

    chunk \= session.get(Chunk, chunk\_id)

    chunk.status \= ProcessingStatus.REVIEW\_READY

    session.commit()

---

### **4.5 Separation of Concerns: Time Handling**

To reiterate the critical design decision:

* **Frontend/API:** Only ever sees/sends **Relative Seconds** (0.0 to 305.0).  
* **Database:** Stores **Relative Seconds**.  
* **Export Script:** The **ONLY** place where chunk\_index \* 300 is added.

**Why?** If Gemini hallucinates a timestamp like "05:10" in a 5-minute file, the validation logic is simple: if end\_time \> 305: reject. If we used absolute timestamps (e.g., "1:05:10"), validation would require complex queries joining the Video table.

---

## **5\. Frontend: The Annotation Workbench**

### **5.1 Tech Stack & Overview**

The frontend is a Single Page Application (SPA) built with **React (Vite)**. It communicates with the FastAPI backend via REST.

* **Core Library:** wavesurfer.js (Audio Visualization) \+ wavesurfer.js-regions (Segment manipulation).  
* **UI Framework:** Material UI (MUI) or Ant Design (for dense data tables).  
* **State Management:** React Query (TanStack Query) for handling API server state and caching.

The "Relative Time" Visual Contract:

The Frontend never calculates absolute time.

* **Input:** The player loads chunk\_05.wav (Duration: 5m 05s).  
* **Display:** The timeline starts at 00:00 and ends at 05:05.  
* **Data:** A timestamp of 10.5 means "10.5 seconds from the start of this file."

---

### **5.2 Layout Specifications**

The Workbench is divided into three vertical zones to optimize vertical screen real estate.

#### **Zone A: The Control Header (Fixed Top)**

Contains global actions for the specific chunk.

* **Left:** Breadcrumbs (Dashboard \> Channel Name \> Video 01 \> Chunk \#5).  
* **Center:**  
  * **Denoise Toggle:** A generic button \[ 🔊 Flag as Noisy \].  
    * *Active State (Orange):* Audio is noisy.  
    * *Inactive State (Gray):* Audio is clean.  
  * **Lock Status:** "🔒 Locked by You" (Green) or "🔒 Locked by Dat" (Red).  
* **Right:** \[ Save Changes \] (Primary Button), \[ Mark as Finished \].

#### **Zone B: The Visualizer (Top 30%)**

A large, zoomable waveform.

* **Library:** wavesurfer.js.  
* **Regions:** Semi-transparent colored boxes overlaid on the waveform representing segments.  
* **Interaction:**  
  * **Drag Region:** Moves start\_time and end\_time together.  
  * **Resize Region Edge:** Adjusts just start or end.  
  * **Click Region:** Loops that specific segment.

#### **Zone C: The Editor Table (Bottom 70% \- Scrollable)**

A dense list of segments synced to the waveform regions.

| Check | Play | Start | End | Transcript (Code-Switch) | Translation (Vietnamese) |
| :---- | :---- | :---- | :---- | :---- | :---- |
| \[x\] | \[▶\] | 00:05.1 | 00:09.2 | \[Input Text\] | \[Input Text\] |

---

### **5.3 Waveform Logic & Implementation**

The critical link between the visual waveform and the text table is the **Region ID**.

Data Flow:

API Load \-\> React State \-\> Wavesurfer Regions

**Code-First Implementation Logic:**

JavaScript

// Logic for syncing Regions (Visual) with Segments (Data)

import WaveSurfer from 'wavesurfer.js';

import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';

// 1\. Initialization

const ws \= WaveSurfer.create({

    container: '\#waveform',

    url: '/api/v1/static/chunks/video\_123/chunk\_05.wav', // Backend mounts this path

    plugins: \[

        RegionsPlugin.create() // Enable the region plugin

    \]

});

// 2\. Load Segments from API

const segments \= apiResponse.data; // \[{id: 101, start: 5.1, end: 9.2, ...}\]

// 3\. Render Regions

segments.forEach(seg \=\> {

    ws.plugins.regions.addRegion({

        id: seg.id.toString(), // CRITICAL: Link Region ID to DB Segment ID

        start: seg.start\_time\_relative,

        end: seg.end\_time\_relative,

        color: 'rgba(0, 0, 255, 0.1)',

        drag: true,

        resize: true

    });

});

// 4\. Handle User Interaction (The "Write" Path)

ws.plugins.regions.on('region-updated', (region) \=\> {

    // When user stops dragging a box

    updateReactState(region.id, {

        start: region.start,

        end: region.end

    });

    // Triggers "Unsaved Changes" flag

});

---

### **5.4 Key Feature Implementation**

#### **A. The "Flag for Denoise" Toggle**

* **Visual:** A toggle button.  
* **Action:**  
  1. User clicks Toggle.  
  2. Frontend sends: POST /api/chunks/{id}/flag-noise.  
  3. **Optimistic UI:** Button turns Orange immediately.  
  4. **Background:** Backend updates denoise\_status \= 'flagged'.

#### **B. The "Verify Segment" Checkbox**

* **Visual:** A checkbox at the start of every table row.  
* **Logic:**  
  * **Default:** Unchecked (False) when loaded from Gemini.  
  * **User Action:** Annotator listens, corrects text, clicks Checkbox.  
  * **Data:** Updates local React state segment.is\_verified \= true.  
  * **Validation:** The "Mark Chunk as Finished" button is **Disabled** until 100% of segments are verified.

#### **C. Keyboard Shortcuts (Productivity)**

We hijack the browser's standard events to speed up workflow.

| Shortcut | Scope | Action |
| :---- | :---- | :---- |
| Ctrl \+ Space | Global | Play/Pause current segment loop. |
| Ctrl \+ Enter | Text Input | Save current row and move focus to next row. |
| Ctrl \+ ArrowRight | Global | Skip forward 5 seconds. |
| Ctrl \+ D | Global | Toggle "Denoise" flag. |

---

### **5.5 Data Synchronization Strategy**

To prevent data loss:

1. **Auto-Save (Debounced):**  
   * When a user stops typing for 2 seconds, trigger PUT /api/segments/{id}.  
2. **Explicit Save:**  
   * The "Save Changes" button sends the entire state of the chunk (all segments) to PUT /api/chunks/{id}/sync.  
3. **Locking Lifecycle:**  
   * **Mount:** POST /chunks/{id}/lock \-\> Returns 200 OK (Editable) or 409 Conflict (Read-Only Mode).  
   * **Unmount:** POST /chunks/{id}/unlock.

**Critique**: This design minimizes complex math on the client. By mapping the database ID directly to the Wavesurfer Region ID, we create a robust 1:1 link. If the user drags a box, the table updates. If the user edits the timestamp numbers in the table, the box moves.

---

## **6\. Operations: The "Night Shift" & Export**

### **6.1 Batch Denoising (The "Night Shift")**

To allow annotators to flag noisy audio without breaking their flow, we treat denoising as an asynchronous batch job. This is triggered manually via the API (e.g., at the end of the day) and runs on the server.

The Workflow:

Annotator Flag \-\> Database Queue \-\> Background Script \-\> File Replacement

#### **A. The Trigger & Logging**

The backend uses Python’s logging module to create a persistent audit trail.

**Log Location:** /mnt/data/project\_speech/logs/server\_processing.log

Python

\# operations/logger\_config.py

import logging

logging.basicConfig(

    filename='/mnt/data/project\_speech/logs/server\_processing.log',

    level=logging.INFO,

    format\='%(asctime)s \- \[NIGHT\_SHIFT\] \- %(levelname)s \- %(message)s'

)

#### **B. The Processing Logic (Code-First)**

This script runs inside a FastAPI BackgroundTask. It processes chunks sequentially to avoid overloading the GPU.

Python

\# operations/denoiser.py

import subprocess

import os

from sqlmodel import Session, select

def run\_batch\_denoise(session: Session):

    """

    Scans DB for FLAGGED chunks and runs DeepFilterNet.

    """

    logging.info("Starting Batch Denoise Job...")

    

    \# 1\. Fetch Queue

    stmt \= select(Chunk).where(Chunk.denoise\_status \== DenoiseStatus.FLAGGED)

    chunks \= session.exec(stmt).all()

    

    if not chunks:

        logging.info("No chunks flagged. Exiting.")

        return

    for chunk in chunks:

        try:

            logging.info(f"Processing Chunk {chunk.id} ({chunk.audio\_path})...")

            

            \# 2\. Mark as Processing (Lock it)

            chunk.denoise\_status \= DenoiseStatus.QUEUED

            session.add(chunk)

            session.commit()

            

            \# 3\. Construct Paths

            \# Input: /mnt/data/project\_speech/chunks/vid\_1/chunk\_05.wav

            input\_abs\_path \= os.path.join(DATA\_ROOT, chunk.audio\_path)

            \# Output: /mnt/data/project\_speech/chunks/vid\_1/chunk\_05\_clean.wav

            output\_abs\_path \= input\_abs\_path.replace(".wav", "\_clean.wav")

            

            \# 4\. Execute DeepFilterNet (Shell Command)

            \# Assumes 'deepFilter' is in PATH. 

            cmd \= \["deepFilter", input\_abs\_path, "-o", output\_abs\_path\]

            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

            

            \# 5\. Atomic Swap (The "No Ambiguity" Path Update)

            \# We update the DB to point to the CLEAN file.

            \# The relative path changes from "chunk\_05.wav" to "chunk\_05\_clean.wav"

            old\_path \= chunk.audio\_path

            new\_relative\_path \= old\_path.replace(".wav", "\_clean.wav")

            

            chunk.audio\_path \= new\_relative\_path

            chunk.denoise\_status \= DenoiseStatus.PROCESSED

            session.add(chunk)

            session.commit()

            

            logging.info(f"Success: Chunk {chunk.id} updated to {new\_relative\_path}")

            

        except Exception as e:

            logging.error(f"Failed Chunk {chunk.id}: {str(e)}")

            chunk.denoise\_status \= DenoiseStatus.FLAGGED \# Revert to flag for retry

            session.add(chunk)

            session.commit()

            

    logging.info("Batch Denoise Job Completed.")

---

### **6.2 The Export Algorithm (The Final Assembly)**

This is the **only** place in the entire pipeline where Absolute Time is calculated. The script reads the database, resolves overlaps, cuts the physical audio clips, and generates the manifest.

#### **A. The "Stitching" Logic**

We deal with the 5-second overlap (300s to 305s) using a strict "Ownership Rule."

**The Rule:**

* **Chunk N** owns the timeline from 00:00 to 05:00 (Relative).  
* **Chunk N+1** starts at 05:00 absolute.  
* **Action:** If a segment in Chunk N starts at 05:01 (Relative), it is **discarded** because Chunk N+1 will contain that same audio starting at 00:01 (Relative).  
* **Exception:** The **Last Chunk** keeps everything until the file ends.

#### **B. The Export Script (Python)**

Python

\# operations/exporter.py

import csv

import subprocess

def export\_dataset(session: Session, output\_dir: str):

    """

    Generates training data: small clips \+ manifest.tsv

    """

    \# 1\. Setup Manifest

    manifest\_path \= os.path.join(output\_dir, "manifest.tsv")

    clips\_dir \= os.path.join(output\_dir, "clips")

    os.makedirs(clips\_dir, exist\_ok=True)

    

    with open(manifest\_path, 'w', newline='', encoding='utf-8') as tsvfile:

        writer \= csv.writer(tsvfile, delimiter='\\t')

        \# Header

        writer.writerow(\['audio\_filepath', 'text', 'translation', 'duration'\])

        

        \# 2\. Iterate Videos

        videos \= session.exec(select(Video)).all()

        

        for video in videos:

            \# Sort chunks to ensure time continuity

            sorted\_chunks \= sorted(video.chunks, key=lambda c: c.chunk\_index)

            total\_chunks \= len(sorted\_chunks)

            

            for i, chunk in enumerate(sorted\_chunks):

                if chunk.status \!= ProcessingStatus.APPROVED:

                    continue \# Skip unverified chunks

                

                input\_audio \= os.path.join(DATA\_ROOT, chunk.audio\_path)

                

                \# 3\. Iterate Segments

                for segment in chunk.segments:

                    if not segment.is\_verified:

                        continue

                        

                    \# \--- THE STITCHING LOGIC \---

                    \# Drop overlap unless it's the last chunk

                    if i \< (total\_chunks \- 1) and segment.start\_time\_relative \>= 300.0:

                        continue 

                    

                    \# 4\. Cut the Clip (Physical Generation)

                    \# We cut directly from the Chunk file using relative times.

                    clip\_filename \= f"{video.id}\_{chunk.chunk\_index}\_{segment.id}.wav"

                    clip\_path \= os.path.join(clips\_dir, clip\_filename)

                    

                    \# FFmpeg: Extract specific region without re-encoding if possible

                    \# But for safety/precision, we re-encode to ensuring perfect headers

                    cmd \= \[

                        "ffmpeg", "-y", "-i", input\_audio,

                        "-ss", str(segment.start\_time\_relative),

                        "-to", str(segment.end\_time\_relative),

                        "-ac", "1", "-ar", "16000",

                        clip\_path

                    \]

                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                    

                    \# 5\. Write to Manifest

                    duration \= segment.end\_time\_relative \- segment.start\_time\_relative

                    writer.writerow(\[

                        os.path.abspath(clip\_path), \# Absolute system path

                        segment.transcript,

                        segment.translation,

                        f"{duration:.2f}"

                    \])

                    

    print(f"Export Complete. Manifest at: {manifest\_path}")

### **6.3 Separation of Concerns Summary**

* **Frontend:** Sees 05:01.  
* **Database:** Stores 05:01.  
* **Export Script:** Sees 05:01 \-\> Recognizes it is \> 05:00 \-\> **Drops it** to avoid duplication with the next chunk.

---

Completion:

This concludes the Technical Specification Document.

We have defined the Architecture, Database, Ingestion, API, Frontend, and Operations.
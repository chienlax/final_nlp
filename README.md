# Vietnamese-English Code-Switching Speech Translation Pipeline

Full-stack annotation system for creating a 150+ hour code-switching speech translation dataset.

## Architecture

| Layer | Technology | Description |
|-------|------------|-------------|
| Frontend | React + Vite + Wavesurfer.js | Waveform editing workbench |
| Backend | FastAPI + SQLModel | REST API with PostgreSQL |
| Processing | FFmpeg + Gemini AI | Chunking and transcription |
| Storage | PostgreSQL | Metadata and transcriptions |

## Quick Start

### 1. Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL 15+
- FFmpeg

### 2. Database Setup
```sql
CREATE DATABASE speech_translation_db;
```

### 3. Environment
```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials and Gemini API keys
```

### 4. Start Development
```powershell
# Run the setup script
.\scripts\start_dev.ps1

# Or manually:
# Terminal 1 - Backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/init_db.py
uvicorn backend.main:app --reload --port 8000

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

### 5. Access
- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

## Project Structure
```
├── backend/
│   ├── db/           # SQLModel models, engine
│   ├── routers/      # FastAPI endpoints
│   ├── processing/   # FFmpeg, Gemini workers
│   └── auth/         # X-User-ID auth deps
├── frontend/
│   └── src/
│       ├── components/  # WaveformViewer, SegmentTable
│       └── pages/       # WorkbenchPage
├── scripts/
│   └── init_db.py    # Database initialization
└── data/
    ├── raw/          # Original .m4a downloads
    └── chunks/       # 5-min WAV segments
```

## Workflow

1. **Ingest**: Download YouTube audio via `ingest_gui.py`
2. **Chunk**: FFmpeg splits into 5-min segments with 5s overlap
3. **Transcribe**: Gemini AI generates Vietnamese transcription
4. **Review**: Annotators verify/edit in React workbench
5. **Export**: Generate `manifest.tsv` for model training

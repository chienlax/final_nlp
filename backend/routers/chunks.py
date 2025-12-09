"""
Chunks Router - Work queue, locking, and denoise flagging.
"""

import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, or_
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import Chunk, User, Video, ProcessingStatus, DenoiseStatus
from backend.auth.deps import get_current_user


router = APIRouter()


# =============================================================================
# CONSTANTS (from environment)
# =============================================================================

LOCK_DURATION_MINUTES = int(os.getenv("LOCK_DURATION_MINUTES", "30"))


# =============================================================================
# SCHEMAS
# =============================================================================

class ChunkResponse(BaseModel):
    """Chunk response schema."""
    id: int
    video_id: int
    chunk_index: int
    audio_path: str
    status: ProcessingStatus
    denoise_status: DenoiseStatus
    locked_by_user_id: Optional[int]
    lock_expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ChunkDetailResponse(ChunkResponse):
    """Chunk with video info."""
    video_title: str
    total_chunks: int


class LockResponse(BaseModel):
    """Lock acquisition response."""
    success: bool
    chunk_id: int
    locked_by_user_id: int
    lock_expires_at: datetime
    message: str


class FlagNoiseResponse(BaseModel):
    """Denoise flag response."""
    chunk_id: int
    denoise_status: DenoiseStatus
    message: str


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_lock_expired(chunk: Chunk) -> bool:
    """Check if a chunk's lock has expired."""
    if chunk.locked_by_user_id is None:
        return True
    if chunk.lock_expires_at is None:
        return True
    return chunk.lock_expires_at < datetime.utcnow()


def clear_expired_lock(chunk: Chunk) -> None:
    """Clear expired lock from chunk."""
    if is_lock_expired(chunk):
        chunk.locked_by_user_id = None
        chunk.lock_expires_at = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/chunks", response_model=List[ChunkResponse])
def list_chunks(
    video_id: Optional[int] = Query(None),
    status: Optional[ProcessingStatus] = Query(None),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_session)
):
    """
    List chunks, optionally filtered by video or status.
    """
    stmt = select(Chunk).order_by(Chunk.video_id, Chunk.chunk_index).limit(limit)
    
    if video_id:
        stmt = stmt.where(Chunk.video_id == video_id)
    if status:
        stmt = stmt.where(Chunk.status == status)
    
    chunks = session.exec(stmt).all()
    return chunks


@router.get("/chunks/next", response_model=Optional[ChunkDetailResponse])
def get_next_chunk(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get the next available chunk for annotation.
    
    Priority:
    1. Return user's currently locked chunk (resume work)
    2. Return first unlocked REVIEW_READY chunk
    
    Ghost Lock: Treats expired locks as NULL.
    """
    now = datetime.utcnow()
    
    # 1. Check if user has an existing lock (unfinished work)
    existing = session.exec(
        select(Chunk).where(
            Chunk.locked_by_user_id == current_user.id,
            Chunk.lock_expires_at > now
        )
    ).first()
    
    if existing:
        video = session.get(Video, existing.video_id)
        total = session.exec(
            select(Chunk).where(Chunk.video_id == existing.video_id)
        ).all()
        
        return ChunkDetailResponse(
            **existing.model_dump(),
            video_title=video.title if video else "Unknown",
            total_chunks=len(total)
        )
    
    # 2. Find next available chunk
    # Status is REVIEW_READY, and Lock is NULL (or expired)
    stmt = (
        select(Chunk)
        .where(Chunk.status == ProcessingStatus.REVIEW_READY)
        .where(
            or_(
                Chunk.locked_by_user_id == None,
                Chunk.lock_expires_at < now
            )
        )
        .order_by(Chunk.video_id, Chunk.chunk_index)
    )
    
    chunk = session.exec(stmt).first()
    
    if not chunk:
        return None
    
    video = session.get(Video, chunk.video_id)
    total = session.exec(
        select(Chunk).where(Chunk.video_id == chunk.video_id)
    ).all()
    
    return ChunkDetailResponse(
        **chunk.model_dump(),
        video_title=video.title if video else "Unknown",
        total_chunks=len(total)
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkDetailResponse)
def get_chunk(chunk_id: int, session: Session = Depends(get_session)):
    """Get a specific chunk by ID with video info."""
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    video = session.get(Video, chunk.video_id)
    total = session.exec(
        select(Chunk).where(Chunk.video_id == chunk.video_id)
    ).all()
    
    return ChunkDetailResponse(
        **chunk.model_dump(),
        video_title=video.title if video else "Unknown",
        total_chunks=len(total)
    )


@router.post("/chunks/{chunk_id}/lock", response_model=LockResponse)
def lock_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Acquire lock on a chunk for editing.
    
    Concurrency Control:
    - If unlocked or lock expired: Grant lock
    - If locked by same user: Refresh lock
    - If locked by other user: Return 409 Conflict
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    now = datetime.utcnow()
    
    # Clear expired locks
    clear_expired_lock(chunk)
    
    # Check current lock state
    if chunk.locked_by_user_id is not None and chunk.locked_by_user_id != current_user.id:
        # Locked by another user
        locker = session.get(User, chunk.locked_by_user_id)
        locker_name = locker.username if locker else f"User {chunk.locked_by_user_id}"
        raise HTTPException(
            status_code=409,
            detail=f"Chunk is locked by {locker_name} until {chunk.lock_expires_at}"
        )
    
    # Grant or refresh lock
    chunk.locked_by_user_id = current_user.id
    chunk.lock_expires_at = now + timedelta(minutes=LOCK_DURATION_MINUTES)
    chunk.status = ProcessingStatus.IN_REVIEW
    
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    
    return LockResponse(
        success=True,
        chunk_id=chunk.id,
        locked_by_user_id=current_user.id,
        lock_expires_at=chunk.lock_expires_at,
        message="Lock acquired successfully"
    )


@router.post("/chunks/{chunk_id}/unlock")
def unlock_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Release lock on a chunk.
    
    Only the lock owner can release.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You don't own the lock on this chunk"
        )
    
    chunk.locked_by_user_id = None
    chunk.lock_expires_at = None
    chunk.status = ProcessingStatus.REVIEW_READY
    
    session.add(chunk)
    session.commit()
    
    return {"message": "Lock released"}


@router.post("/chunks/{chunk_id}/flag-noise", response_model=FlagNoiseResponse)
def flag_chunk_for_denoise(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark a chunk for denoising by the night shift.
    
    Sets denoise_status to FLAGGED.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    chunk.denoise_status = DenoiseStatus.FLAGGED
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    
    return FlagNoiseResponse(
        chunk_id=chunk.id,
        denoise_status=chunk.denoise_status,
        message="Chunk flagged for denoising"
    )


@router.post("/chunks/{chunk_id}/approve")
def approve_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark a chunk as approved (ready for export).
    
    Releases lock and sets status to APPROVED.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    # Must own the lock
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You must lock the chunk before approving"
        )
    
    chunk.status = ProcessingStatus.APPROVED
    chunk.locked_by_user_id = None
    chunk.lock_expires_at = None
    
    session.add(chunk)
    session.commit()
    
    return {"message": "Chunk approved", "status": ProcessingStatus.APPROVED}

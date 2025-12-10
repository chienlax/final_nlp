"""
Users Router - List and manage annotators.
Channels Router - CRUD for YouTube source channels.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import User, UserRole, Channel


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class UserResponse(BaseModel):
    """User response schema."""
    id: int
    username: str
    role: UserRole
    
    class Config:
        from_attributes = True


class ChannelResponse(BaseModel):
    """Channel response schema."""
    id: int
    name: str
    url: str
    
    class Config:
        from_attributes = True


class ChannelCreate(BaseModel):
    """Schema for creating a new channel."""
    name: str
    url: str


# =============================================================================
# USER ENDPOINTS
# =============================================================================

@router.get("/users", response_model=List[UserResponse])
def list_users(session: Session = Depends(get_session)):
    """
    List all annotator users.
    
    Used by ingestion GUI dropdown and frontend user selector.
    """
    users = session.exec(select(User).order_by(User.username)).all()
    return users


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, session: Session = Depends(get_session)):
    """Get a specific user by ID."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# =============================================================================
# CHANNEL ENDPOINTS
# =============================================================================

@router.get("/channels", response_model=List[ChannelResponse])
def list_channels(session: Session = Depends(get_session)):
    """
    List all YouTube source channels.
    
    Used by ingestion GUI dropdown for channel selection.
    """
    channels = session.exec(select(Channel).order_by(Channel.name)).all()
    return channels


@router.get("/channels/by-url", response_model=ChannelResponse)
def get_channel_by_url(
    url: str = Query(..., description="YouTube channel URL"),
    session: Session = Depends(get_session)
):
    """
    Find a channel by its YouTube URL.
    
    Used by ingestion GUI to check if a channel already exists before creating.
    
    Returns:
        Channel if found
        
    Raises:
        404 if channel URL not found
    """
    # Normalize URL (strip whitespace)
    url = url.strip()
    
    channel = session.exec(
        select(Channel).where(Channel.url == url)
    ).first()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return channel


@router.post("/channels", response_model=ChannelResponse, status_code=201)
def create_channel(
    data: ChannelCreate,
    session: Session = Depends(get_session)
):
    """
    Create a new YouTube source channel.
    
    Used by ingestion GUI for auto-channel-creation when downloading
    from a new channel.
    
    Args:
        name: Display name for the channel
        url: YouTube channel URL (must be unique)
        
    Returns:
        Created channel with ID
        
    Raises:
        409 if channel URL already exists
    """
    # Normalize URL
    url = data.url.strip()
    name = data.name.strip()
    
    # Check for duplicate URL
    existing = session.exec(
        select(Channel).where(Channel.url == url)
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Channel with URL already exists (ID: {existing.id}, Name: {existing.name})"
        )
    
    # Create channel
    channel = Channel(name=name, url=url)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    
    return channel


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
def get_channel(channel_id: int, session: Session = Depends(get_session)):
    """Get a specific channel by ID."""
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel

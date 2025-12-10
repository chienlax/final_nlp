"""
Users Router - List and manage annotators.
"""

from typing import List

from fastapi import APIRouter, Depends
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
    
    class Config:
        from_attributes = True


# =============================================================================
# ENDPOINTS
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/channels", response_model=List[ChannelResponse])
def list_channels(session: Session = Depends(get_session)):
    """
    List all YouTube source channels.
    
    Used by ingestion GUI dropdown for channel selection.
    """
    channels = session.exec(select(Channel).order_by(Channel.name)).all()
    return channels

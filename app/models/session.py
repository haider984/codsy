from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .base import PyObjectId, common_config # Assuming base.py exists

class SessionBase(BaseModel):
    uid: PyObjectId
    pid: PyObjectId
    channel: Optional[str] = None
    status: str # e.g., "active", "inactive", "completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SessionCreate(SessionBase):
    pass

class SessionInDB(SessionBase):
    id: PyObjectId = Field(alias="_id") # Maps to session-id (_id)
    model_config = common_config

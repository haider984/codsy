from __future__ import annotations

from pydantic import BaseModel, Field
from .base import PyObjectId, common_config # Assuming base.py exists

class SessionBase(BaseModel):
    uid: PyObjectId
    pid: PyObjectId

class SessionCreate(SessionBase):
    pass

class SessionInDB(SessionBase):
    sid: PyObjectId = Field(alias="_id") # Maps to session-id (_id)
    model_config = common_config

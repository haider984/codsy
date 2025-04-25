from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from .base import PyObjectId, common_config

class GitTaskBase(BaseModel):
    session_id: PyObjectId # Link to the Session
    uid: Optional[PyObjectId] = None # Reference to the User (_id) who created it
    status: str
    description: Optional[str] = None
    url: Optional[HttpUrl] = None # Validate as URL

class GitTaskCreate(GitTaskBase):
    pass

class GitTaskInDB(GitTaskBase):
    id: PyObjectId = Field(alias="_id") # Maps to gtid (_id)
    model_config = common_config

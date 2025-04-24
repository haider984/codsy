from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from .base import PyObjectId, common_config

class JiraTaskBase(BaseModel):
    session_id: PyObjectId # Link to the Session
    status: str
    description: Optional[str] = None
    url: Optional[HttpUrl] = None # Validate as URL

class JiraTaskCreate(JiraTaskBase):
    pass

class JiraTaskInDB(JiraTaskBase):
    id: PyObjectId = Field(alias="_id") # Maps to jtid (_id)
    model_config = common_config

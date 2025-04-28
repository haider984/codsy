from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .base import PyObjectId, common_config

class GitHubTaskBase(BaseModel):
    mid: PyObjectId # Foreign key to Message
    title: str # Added field
    description: str # Made mandatory
    status: str # e.g., "pending", "in_progress", "completed", etc.
    creation_date: datetime = Field(default_factory=datetime.utcnow) # Added field with default
    completion_date: Optional[datetime] = None # Added optional field

class GitHubTaskCreate(GitHubTaskBase):
    pass

class GitHubTaskInDB(GitHubTaskBase):
    git_task_id: PyObjectId = Field(alias="_id") # Renamed from id, kept alias
    model_config = common_config

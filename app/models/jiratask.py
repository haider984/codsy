from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime # Import datetime
from .base import PyObjectId, common_config

# Define the new Jira task structure
class JiraTaskBase(BaseModel):
    mid: PyObjectId # Foreign key to Message
    title: str # Added field
    description: str # Made mandatory
    status: str # e.g., "pending", "in_progress", "completed", etc.
    creation_date: datetime = Field(default_factory=datetime.utcnow) # Added field with default
    completion_date: Optional[datetime] = None # Added optional field

    # Removed session_id, uid, url

# Create model for the Jira task structure
class JiraTaskCreate(JiraTaskBase):
    pass

# DB model for the Jira task structure
class JiraTaskInDB(JiraTaskBase):
    jira_task_id: PyObjectId = Field(alias="_id") # Renamed from id, kept alias
    model_config = common_config

# Keep the old models commented out or remove them if no longer needed anywhere
# class JiraTaskBase(BaseModel):
#     session_id: PyObjectId # Link to the Session
#     uid: PyObjectId # Reference to the User (_id) who created it
#     status: str
#     description: Optional[str] = None
#     url: Optional[HttpUrl] = None # Validate as URL
#
# class JiraTaskCreate(JiraTaskBase):
#     pass
#
# class JiraTaskInDB(JiraTaskBase):
#     id: PyObjectId = Field(alias="_id") # Maps to jtid (_id)
#     model_config = common_config

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional # Import List and Optional

# Import task models - adjust paths if necessary
from .base import PyObjectId, common_config
from .jiratask import JiraTaskInDB
from .gittask import GitHubTaskInDB

# Keep StatusBase and StatusInDB if they represent stored data,
# even if not directly returned by the new endpoint.
class StatusBase(BaseModel):
    pid: PyObjectId # Foreign key to Project
    start_date: datetime
    end_date: datetime

# StatusCreate is no longer needed as we removed the POST endpoint
# class StatusCreate(StatusBase):
#     pass

class StatusInDB(StatusBase):
    status_id: PyObjectId = Field(alias="_id") # Primary key
    model_config = common_config

# StatusIdResponse is no longer needed
# class StatusIdResponse(BaseModel):
#     status_id: PyObjectId

# New Response Model for the combined status details endpoint
class ProjectStatusDetails(BaseModel):
    jira_tasks: List[JiraTaskInDB]
    git_tasks: List[GitHubTaskInDB]
    model_config = common_config # Use common config for ObjectId serialization etc.

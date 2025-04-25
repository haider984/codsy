from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from enum import Enum # Import Enum
from .base import PyObjectId, common_config # Assuming base.py exists
from datetime import datetime # Import if any user fields need it later

# Define the allowed functionalities using an Enum
class Functionality(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    GITHUB = "github"
    JIRA = "jira"
    WHATSAPP = "whatsapp"
    GITLAB = "gitlab"
    MICROSOFT_TEAMS = "microsoft meams"
    VISUAL_STUDIO = "visual studio"

class AgentBase(BaseModel):
    name: str
    email: EmailStr # Use EmailStr for email validation
    phone: Optional[str] = None
    # Rename agent_post to role
    role: List[str] = Field(default_factory=list) # Renamed from agent_post
    # Add the new allowed_functionalities field using the Enum
    allowed_functionalities: List[Functionality] = Field(default_factory=list)

class AgentCreate(AgentBase):
    # Add any fields required only on creation, if any
    pass

class AgentInDB(AgentBase):
    id: PyObjectId = Field(alias="_id") # Maps to MongoDB's _id
    model_config = common_config

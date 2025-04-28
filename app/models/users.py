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
    MICROSOFT_TEAMS = "microsoft teams"
    VISUAL_STUDIO = "visual studio"

# Renamed from AgentBase
class UserBase(BaseModel):
    email: EmailStr # Kept EmailStr
    name: str
    phone_number: Optional[str] = None # Renamed from phone
    # Changed role to single string
    role: str
    # Renamed allowed_functionalities to allowed_functionality
    allowed_functionality: List[Functionality] = Field(default_factory=list) # Kept List[Functionality]

# Renamed from AgentCreate
class UserCreate(UserBase):
    pass

# Renamed from AgentInDB
class UserInDB(UserBase):
    uid: PyObjectId = Field(alias="_id") # Changed id to uid, kept alias
    model_config = common_config

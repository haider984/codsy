from pydantic import BaseModel, Field
from typing import Optional
from .base import PyObjectId, common_config # Assuming base.py exists

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    info: Optional[str] = None
    uid: PyObjectId # Reference to the User (_id) who owns/created it

class ProjectCreate(ProjectBase):
    pass

class ProjectInDB(ProjectBase):
    id: PyObjectId = Field(alias="_id") # Maps to pid (_id)
    model_config = common_config

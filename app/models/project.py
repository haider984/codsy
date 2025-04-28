from pydantic import BaseModel, Field
from .base import PyObjectId, common_config # Assuming base.py exists

class ProjectBase(BaseModel):
    name: str
    description: str # Made mandatory

class ProjectCreate(ProjectBase):
    pass

class ProjectInDB(ProjectBase):
    pid: PyObjectId = Field(alias="_id") # Renamed from id to pid, kept alias
    model_config = common_config

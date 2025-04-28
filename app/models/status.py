from pydantic import BaseModel, Field
from datetime import datetime
from .base import PyObjectId, common_config

class StatusBase(BaseModel):
    pid: PyObjectId # Foreign key to Project
    start_date: datetime
    end_date: datetime

class StatusCreate(StatusBase):
    pass

class StatusInDB(StatusBase):
    status_id: PyObjectId = Field(alias="_id") # Primary key
    model_config = common_config

# Optional: Model to return only the ID on creation
class StatusIdResponse(BaseModel):
    status_id: PyObjectId

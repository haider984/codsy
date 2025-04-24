from pydantic import BaseModel, Field
from typing import Optional
from .base import PyObjectId, common_config

class TranscriptBase(BaseModel):
    session_id: PyObjectId
    uid: PyObjectId # User involved
    pid: PyObjectId # Project involved
    transcript: str # The actual transcript text

class TranscriptCreate(TranscriptBase):
    pass

class TranscriptInDB(TranscriptBase):
    # Assuming one transcript per session_id, maybe _id is same as session_id?
    # Or it could have its own unique _id. Assuming unique _id:
    id: PyObjectId = Field(alias="_id")
    model_config = common_config

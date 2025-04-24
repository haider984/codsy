from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import Optional
from datetime import datetime
from .base import PyObjectId, common_config

class MeetingBase(BaseModel):
    session_id: PyObjectId
    uid: PyObjectId # Often the host or creator
    pid: PyObjectId
    email: EmailStr
    meeting_url: HttpUrl
    meeting_ID: str
    passcode: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None

class MeetingCreate(MeetingBase):
    pass

class MeetingInDB(MeetingBase):
    # Assuming meetings have their own ID, though session_id is primary link
    id: PyObjectId = Field(alias="_id")
    model_config = common_config

from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from .base import PyObjectId, common_config
from bson import ObjectId as BsonObjectId

class MeetingBase(BaseModel):
    email: EmailStr
    meeting_url: str
    meeting_ID: str
    passcode: str
    start_time: datetime
    end_time: datetime

class MeetingCreate(MeetingBase):
    pass

class MeetingInDB(MeetingBase):
    meeting_id: PyObjectId = Field(alias="_id")
    mid: PyObjectId
    model_config = common_config

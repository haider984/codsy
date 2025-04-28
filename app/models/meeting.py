from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from .base import PyObjectId, common_config
# Import ObjectId for generation in the router
from bson import ObjectId as BsonObjectId

# Base model contains only fields provided during creation
class MeetingBase(BaseModel):
    mid: PyObjectId # ADDED: mid is now expected during creation
    email: EmailStr
    meeting_url: str
    meeting_ID: str
    passcode: str
    start_time: datetime
    end_time: datetime

# Create model inherits base
class MeetingCreate(MeetingBase): # Inherits the requirement for mid
    pass

# DB model has both meet_id (PK) and mid (FK)
class MeetingInDB(MeetingBase):
    meet_id: PyObjectId = Field(alias="_id") # meet_id is the primary key, maps to _id
    mid: PyObjectId # mid is the foreign key to Message
    model_config = common_config

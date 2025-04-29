from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .base import PyObjectId, common_config

class MessageBase(BaseModel):
    sid: PyObjectId # Foreign key to Session
    uid: PyObjectId # Foreign key to User
    pid: PyObjectId # Foreign key to Project
    content: str
    message_datetime: datetime = Field(default_factory=datetime.utcnow) # Use default factory
    source: str # "email" or "slack"

    # Email-specific fields
    msg_id: Optional[str] = None # For email threading/reply

    # Slack-specific fields
    channel: str # Made compulsory again
    channel_id: Optional[str] = None # New optional field
    thread_ts: Optional[str] = None

    # Classification info
    message_type: str # "generic", "meeting_invite", ...

    # Processing status
    processed: bool = False # Default to False
    status: str # "pending", "processing", ...

class MessageCreate(MessageBase):
    # Allow overriding defaults if needed, but generally they should be set by the system
    pass

class MessageInDB(MessageBase):
    mid: PyObjectId = Field(alias="_id") # Primary key
    model_config = common_config

# New response model for returning only the MID
class MessageMidResponse(BaseModel):
    mid: PyObjectId
    # model_config = common_config # Optional, probably not needed just for mid

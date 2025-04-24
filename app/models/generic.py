from pydantic import BaseModel, Field
from typing import List, Dict, Any # Or define a specific message structure
from .base import PyObjectId, common_config
from datetime import datetime

# Example specific message structure
class Message(BaseModel):
    sender: str # e.g., "user", "ai", "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class GenericBase(BaseModel):
    session_id: PyObjectId
    # Using a list of structured messages is often better than just "messages"
    messages: List[Message] = Field(default_factory=list)
    # Or if it's truly unstructured:
    # data: Dict[str, Any] = Field(default_factory=dict)

class GenericCreate(GenericBase):
    pass

class GenericInDB(GenericBase):
    # Assuming one document per session_id, maybe _id is same as session_id?
    # Or it could have its own unique _id. Assuming unique _id:
    id: PyObjectId = Field(alias="_id")
    model_config = common_config

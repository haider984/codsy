from pydantic import BaseModel, Field
from .base import PyObjectId, common_config
from typing import Optional # Add fields as needed

class FeedbackBase(BaseModel):
    session_id: PyObjectId
    # Add other feedback fields here, e.g.:
    rating: Optional[int] = None
    comment: Optional[str] = None

class FeedbackCreate(FeedbackBase):
    pass

class FeedbackInDB(FeedbackBase):
    # Feedbacks might not need their own separate _id if always
    # accessed via session_id, or they might. Assuming they do:
    id: PyObjectId = Field(alias="_id")
    model_config = common_config

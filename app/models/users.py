from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from .base import PyObjectId, common_config # Assuming base.py exists
from datetime import datetime # Import if any user fields need it later

class UserBase(BaseModel):
    name: str
    email: EmailStr # Use EmailStr for email validation
    phone: Optional[str] = None
    # Assuming user_post is a list of strings for now.
    # This could also be a list of ObjectIds linking to a Post collection,
    # or even embedded post documents. Adjust if needed.
    user_post: List[str] = Field(default_factory=list)

class UserCreate(UserBase):
    # Add any fields required only on creation, if any
    pass

class UserInDB(UserBase):
    id: PyObjectId = Field(alias="_id") # Maps to MongoDB's _id
    model_config = common_config

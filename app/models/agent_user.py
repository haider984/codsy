from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, EmailStr

class UserStatus(str, Enum):
    ALLOWED = "allowed"
    NOT_ALLOWED = "not_allowed"

class AgentUserBase(BaseModel):
    uid: str = Field(..., description="User ID from the user table")
    email: EmailStr = Field(..., description="User's email address")
    status: UserStatus = Field(..., description="Status: allowed or not_allowed")
    groq_api: Optional[str] = Field(None, description="GROQ API key")

class AgentUserCreate(AgentUserBase):
    pass

class AgentUserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None, description="User's email address")
    status: Optional[UserStatus] = Field(None, description="Status: allowed or not_allowed")
    groq_api: Optional[str] = Field(None, description="GROQ API key")

class AgentUserInDB(AgentUserBase):
    id: str = Field(..., description="MongoDB document ID")

    class Config:
        from_attributes = True
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "60d5ec49f5c9e6f8e4b1c2a3",
                "uid": "user123",
                "email": "user@example.com",
                "status": "allowed",
                "groq_api": "your_groq_api_key_here"
            }
        }

class AgentUserResponse(AgentUserBase):
    id: str

    class Config:
        from_attributes = True
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "60d5ec49f5c9e6f8e4b1c2a3",
                "uid": "user123",
                "email": "user@example.com",
                "status": "allowed",
                "groq_api": "your_groq_api_key_here"
            }
        }

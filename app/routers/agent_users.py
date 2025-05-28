from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
# bson imports are not strictly needed here if all ObjectId handling is in services
# from bson import ObjectId 
# from bson.son import SON

# Models will now have .email and .status
from app.models.agent_user import AgentUserCreate, AgentUserUpdate, AgentUserResponse, UserStatus,AgentUserGroqApiUpdate
from app.services.agent_user import (
    create_agent_user,
    get_agent_user_by_id,
    get_agent_user_by_uid,
    get_all_agent_users,
    update_agent_user,
    delete_agent_user,
    get_agent_user_status_by_email,
    get_agent_user_by_email,
    update_agent_user_groq_api,
    get_db # Re-using the get_db from services
)
from pydantic import EmailStr # For email validation in path parameter

router = APIRouter()

@router.post("/", response_model=AgentUserResponse, status_code=status.HTTP_201_CREATED)
async def add_agent_user(
    agent_user_data: AgentUserCreate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Create a new agent user.
    - **uid**: User ID from the main user table.
    - **email**: User's email address.
    - **status**: 'allowed' or 'not_allowed'.
    - **groq_api**: Optional GROQ API key.
    """
    existing_agent_user = await get_agent_user_by_uid(agent_user_data.uid, db)
    if existing_agent_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"AgentUser with UID '{agent_user_data.uid}' already exists."
        )
    # If there's a unique constraint on email as well, check here
    # existing_agent_user_by_email = await db[COLLECTION_NAME].find_one({"email": agent_user_data.email})
    # if existing_agent_user_by_email:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail=f"AgentUser with email '{agent_user_data.email}' already exists."
    #     )
    created_user = await create_agent_user(agent_user_data, db)
    # model_validate is Pydantic V2
    return AgentUserResponse.model_validate(created_user)

@router.get("/{email}")
async def get_user_id_by_email(
    email: EmailStr,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get the user ID (MongoDB document ID) for a given email.
    """
    user = await get_agent_user_by_email(email, db)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with email '{email}' not found.")
    return {"id": user.uid}

@router.get("/groq/{email}")
async def get_user_id_by_email(
    email: EmailStr,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get the user ID (MongoDB document ID) for a given email.
    """
    user = await get_agent_user_by_email(email, db)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with email '{email}' not found.")
    return {"id": user.groq_api}


@router.get("/{agent_user_id}", response_model=AgentUserResponse)
async def read_agent_user_by_id(
    agent_user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get a specific agent user by their document ID.
    """
    agent_user = await get_agent_user_by_id(agent_user_id, db)
    if not agent_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent user not found")
    return AgentUserResponse.model_validate(agent_user)

@router.get("/uid/{uid}", response_model=AgentUserResponse)
async def read_agent_user_by_uid_route(
    uid: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get a specific agent user by their UID.
    """
    agent_user = await get_agent_user_by_uid(uid, db)
    if not agent_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent user with UID '{uid}' not found")
    return AgentUserResponse.model_validate(agent_user)


@router.get("/", response_model=List[AgentUserResponse])
async def read_all_agent_users(
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get a list of all agent users with pagination.
    """
    agent_users = await get_all_agent_users(db)
    return [AgentUserResponse.model_validate(au) for au in agent_users]

async def get_all_agent_users(db: AsyncIOMotorDatabase):
    cursor = db["agent_users"].find({})
    users = await cursor.to_list(length=None)

    # Convert MongoDB _id to string id
    for user in users:
        user["id"] = str(user["_id"])
        del user["_id"]
    return users

@router.get("/status/email/{email}", response_model=UserStatus)
async def read_agent_user_status_by_email(
    email: EmailStr,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Check if a user is allowed or not_allowed based on their email.
    Returns the user's status.
    """
    user = await get_agent_user_by_email(email, db)
    user_status = user.status if user else None

    if user_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent user with email '{email}' not found."
        )
    return user_status

@router.put("/{agent_user_id}/groq_api", response_model=AgentUserResponse)
async def update_agent_user_groq_api_endpoint(
    agent_user_id: str,
    groq_api_update_data: AgentUserGroqApiUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Update only the groq_api fields for an existing agent user by their document ID.
    """
    updated_user = await update_agent_user_groq_api(agent_user_id, groq_api_update_data, db)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent user not found")
    return AgentUserResponse.model_validate(updated_user)


@router.put("/{agent_user_id}", response_model=AgentUserResponse)
async def update_existing_agent_user(
    agent_user_id: str,
    agent_user_update_data: AgentUserUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Update an existing agent user by their document ID.
    Allows partial updates for email, status, and groq_api.
    """
    updated_user = await update_agent_user(agent_user_id, agent_user_update_data, db)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent user not found")
    return AgentUserResponse.model_validate(updated_user)


@router.delete("/{agent_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent_user(
    agent_user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Delete an agent user by their document ID.
    """
    deleted = await delete_agent_user(agent_user_id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent user not found")
    return None

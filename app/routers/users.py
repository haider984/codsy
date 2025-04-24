from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.users import UserCreate, UserInDB#, UserUpdate # Import UserUpdate if you create it
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id # Assuming a helper for ID conversion

router = APIRouter()

async def get_user_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'users' collection."""
    return db.get_collection("users")

@router.post("/", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate, # Body parameter
    collection = Depends(get_user_collection) # Dependency
):
    """Creates a new user."""
    try:
        user_dict = user.model_dump()
        insert_result = await collection.insert_one(user_dict)
        # Retrieve the newly created document using the inserted_id
        created_user = await collection.find_one({"_id": insert_result.inserted_id})
        if created_user:
            return UserInDB(**created_user)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User could not be created")
    except Exception as e: # Consider catching specific pymongo errors like DuplicateKeyError
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating user: {e}")

@router.get("/", response_model=List[UserInDB])
async def read_users(
    skip: int = 0, # Query param (default)
    limit: int = 100, # Query param (default)
    collection = Depends(get_user_collection) # Dependency (default)
):
    """Retrieves a list of users with pagination."""
    users_cursor = collection.find().skip(skip).limit(limit)
    users = await users_cursor.to_list(length=limit)
    return [UserInDB(**user) for user in users]

@router.get("/{user_id}", response_model=UserInDB)
async def read_user(
    user_id: ObjectId = Depends(get_object_id), # Path param with Depends (default)
    collection = Depends(get_user_collection) # Dependency (default)
):
    """Retrieves a specific user by ID."""
    user = await collection.find_one({"_id": user_id})
    if user:
        return UserInDB(**user)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found")

@router.put("/{user_id}", response_model=UserInDB)
async def update_user(
    user_update: UserCreate, # Body parameter (Moved first)
    user_id: ObjectId = Depends(get_object_id), # Path param with Depends
    collection = Depends(get_user_collection) # Dependency
):
    """Updates an existing user."""
    # It's often better practice to have a separate UserUpdate model
    # that makes all fields Optional, so users don't have to send all fields.
    user_dict = user_update.model_dump(exclude_unset=True) # Only update provided fields
    if not user_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_user = await collection.find_one_and_update(
        {"_id": user_id},
        {"$set": user_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_user:
        return UserInDB(**updated_user)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found for update")

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: ObjectId = Depends(get_object_id), # Path param with Depends
    collection = Depends(get_user_collection) # Dependency
):
    """Deletes a user."""
    delete_result = await collection.delete_one({"_id": user_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found for deletion")
    return # Return None with 204 status

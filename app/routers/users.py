from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.users import UserCreate, UserInDB, UserUidResponse
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_user_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'users' collection."""
    return db.get_collection("users")

@router.post("/", response_model=UserUidResponse, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_user(
    user: UserCreate,
    collection = Depends(get_user_collection)
):
    """Creates a new user and returns only their uid."""
    try:
        user_dict = user.model_dump()
        insert_result = await collection.insert_one(user_dict)
        if insert_result.inserted_id:
            return UserUidResponse(uid=insert_result.inserted_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User could not be created or ID not retrieved")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating user: {e}")

@router.get("/", response_model=List[UserInDB], response_model_by_alias=False)
async def read_all_users(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_user_collection)
):
    """Retrieves a list of users with pagination."""
    users_cursor = collection.find().skip(skip).limit(limit)
    users = await users_cursor.to_list(length=limit)
    return [UserInDB(**user) for user in users]

@router.get("/{user_id}", response_model=UserInDB, response_model_by_alias=False)
async def read_user_by_id(
    user_id: str = Path(..., description="The BSON ObjectId of the user as a string"),
    collection = Depends(get_user_collection)
):
    """Retrieves a specific user by ID."""
    validated_user_oid = validate_object_id_sync(user_id)
    user = await collection.find_one({"_id": validated_user_oid})
    if user:
        return UserInDB(**user)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found")

@router.put("/{user_id}", response_model=UserInDB, response_model_by_alias=False)
async def update_user(
    user_update: UserCreate,
    user_id: str = Path(..., description="The BSON ObjectId of the user as a string"),
    collection = Depends(get_user_collection)
):
    """Updates an existing user."""
    validated_user_oid = validate_object_id_sync(user_id)

    user_dict = user_update.model_dump(exclude_unset=True)
    if not user_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_user = await collection.find_one_and_update(
        {"_id": validated_user_oid},
        {"$set": user_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_user:
        return UserInDB(**updated_user)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found for update")

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str = Path(..., description="The BSON ObjectId of the user as a string"),
    collection = Depends(get_user_collection)
):
    """Deletes a user."""
    validated_user_oid = validate_object_id_sync(user_id)
    delete_result = await collection.delete_one({"_id": validated_user_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found for deletion")
    return

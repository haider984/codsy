from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.gittask import GitTaskCreate, GitTaskInDB # Import GitTask models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_gittask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'gittasks' collection."""
    return db.get_collection("gittasks")

@router.post("/", response_model=GitTaskInDB, status_code=status.HTTP_201_CREATED)
async def create_gittask(
    gittask: GitTaskCreate,
    collection = Depends(get_gittask_collection)
):
    """Creates a new git task."""
    try:
        gittask_dict = gittask.model_dump(mode="json") # Use mode="json" for HttpUrl etc.
        insert_result = await collection.insert_one(gittask_dict)
        created_gittask = await collection.find_one({"_id": insert_result.inserted_id})
        if created_gittask:
            return GitTaskInDB(**created_gittask)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Git task could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating git task: {e}")

@router.get("/", response_model=List[GitTaskInDB])
async def read_gittasks(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_gittask_collection)
):
    """Retrieves a list of git tasks with pagination."""
    gittasks_cursor = collection.find().skip(skip).limit(limit)
    gittasks = await gittasks_cursor.to_list(length=limit)
    return [GitTaskInDB(**gt) for gt in gittasks]

@router.get("/{gittask_id}", response_model=GitTaskInDB)
async def read_gittask(
    gittask_id: ObjectId = Depends(get_object_id), # Maps to gtid (_id)
    collection = Depends(get_gittask_collection)
):
    """Retrieves a specific git task by ID."""
    gittask = await collection.find_one({"_id": gittask_id})
    if gittask:
        return GitTaskInDB(**gittask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Git task with id {gittask_id} not found")

@router.put("/{gittask_id}", response_model=GitTaskInDB)
async def update_gittask(
    gittask_update: GitTaskCreate, # Consider a GitTaskUpdate model
    gittask_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_gittask_collection)
):
    """Updates an existing git task."""
    gittask_dict = gittask_update.model_dump(mode="json", exclude_unset=True)
    if not gittask_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_gittask = await collection.find_one_and_update(
        {"_id": gittask_id},
        {"$set": gittask_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_gittask:
        return GitTaskInDB(**updated_gittask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Git task with id {gittask_id} not found for update")

@router.delete("/{gittask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gittask(
    gittask_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_gittask_collection)
):
    """Deletes a git task."""
    delete_result = await collection.delete_one({"_id": gittask_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Git task with id {gittask_id} not found for deletion")
    return

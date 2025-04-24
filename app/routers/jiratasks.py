from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.jiratask import JiraTaskCreate, JiraTaskInDB # Import JiraTask models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_jiratask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'jiratasks' collection."""
    return db.get_collection("jiratasks")

@router.post("/", response_model=JiraTaskInDB, status_code=status.HTTP_201_CREATED)
async def create_jiratask(
    jiratask: JiraTaskCreate,
    collection = Depends(get_jiratask_collection)
):
    """Creates a new jira task."""
    try:
        jiratask_dict = jiratask.model_dump(mode="json") # Use mode="json" for HttpUrl etc.
        insert_result = await collection.insert_one(jiratask_dict)
        created_jiratask = await collection.find_one({"_id": insert_result.inserted_id})
        if created_jiratask:
            return JiraTaskInDB(**created_jiratask)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Jira task could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating jira task: {e}")

@router.get("/", response_model=List[JiraTaskInDB])
async def read_jiratasks(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_jiratask_collection)
):
    """Retrieves a list of jira tasks with pagination."""
    jiratasks_cursor = collection.find().skip(skip).limit(limit)
    jiratasks = await jiratasks_cursor.to_list(length=limit)
    return [JiraTaskInDB(**jt) for jt in jiratasks]

@router.get("/{jiratask_id}", response_model=JiraTaskInDB)
async def read_jiratask(
    jiratask_id: ObjectId = Depends(get_object_id), # Maps to jtid (_id)
    collection = Depends(get_jiratask_collection)
):
    """Retrieves a specific jira task by ID."""
    jiratask = await collection.find_one({"_id": jiratask_id})
    if jiratask:
        return JiraTaskInDB(**jiratask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jiratask_id} not found")

@router.put("/{jiratask_id}", response_model=JiraTaskInDB)
async def update_jiratask(
    jiratask_update: JiraTaskCreate, # Consider a JiraTaskUpdate model
    jiratask_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_jiratask_collection)
):
    """Updates an existing jira task."""
    jiratask_dict = jiratask_update.model_dump(mode="json", exclude_unset=True)
    if not jiratask_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_jiratask = await collection.find_one_and_update(
        {"_id": jiratask_id},
        {"$set": jiratask_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_jiratask:
        return JiraTaskInDB(**updated_jiratask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jiratask_id} not found for update")

@router.delete("/{jiratask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_jiratask(
    jiratask_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_jiratask_collection)
):
    """Deletes a jira task."""
    delete_result = await collection.delete_one({"_id": jiratask_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jiratask_id} not found for deletion")
    return

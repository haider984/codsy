from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.jiratask import JiraTaskCreate, JiraTaskInDB
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_jiratask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'jira_tasks' collection."""
    return db.get_collection("jira_tasks")

@router.post("/", response_model=JiraTaskInDB, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_jiratask(
    jira_task: JiraTaskCreate,
    collection = Depends(get_jiratask_collection)
):
    """Creates a new Jira task."""
    try:
        jira_task_dict = jira_task.model_dump()
        insert_result = await collection.insert_one(jira_task_dict)
        created_jira_task = await collection.find_one({"_id": insert_result.inserted_id})
        if created_jira_task:
            return JiraTaskInDB(**created_jira_task)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Jira task could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating Jira task: {e}")

@router.get("/", response_model=List[JiraTaskInDB], response_model_by_alias=False)
async def read_all_jiratasks(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_jiratask_collection)
):
    """Retrieves a list of Jira tasks with pagination."""
    jiratasks_cursor = collection.find().skip(skip).limit(limit)
    jiratasks = await jiratasks_cursor.to_list(length=limit)
    return [JiraTaskInDB(**jt) for jt in jiratasks]

@router.get("/{jira_task_id}", response_model=JiraTaskInDB, response_model_by_alias=False)
async def read_jiratask_by_id(
    jira_task_id: str = Path(..., description="The BSON ObjectId of the Jira task as a string"),
    collection = Depends(get_jiratask_collection)
):
    """Retrieves a specific Jira task by ID."""
    validated_jiratask_oid = validate_object_id_sync(jira_task_id)
    jiratask = await collection.find_one({"_id": validated_jiratask_oid})
    if jiratask:
        return JiraTaskInDB(**jiratask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jira_task_id} not found")

@router.put("/{jira_task_id}", response_model=JiraTaskInDB, response_model_by_alias=False)
async def update_jiratask(
    jira_task_update: JiraTaskCreate,
    jira_task_id: str = Path(..., description="The BSON ObjectId of the Jira task as a string"),
    collection = Depends(get_jiratask_collection)
):
    """Updates an existing Jira task."""
    validated_jiratask_oid = validate_object_id_sync(jira_task_id)
    jiratask_dict = jira_task_update.model_dump(exclude_unset=True)
    if not jiratask_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_jiratask = await collection.find_one_and_update(
        {"_id": validated_jiratask_oid},
        {"$set": jiratask_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_jiratask:
        return JiraTaskInDB(**updated_jiratask)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jira_task_id} not found for update")

@router.delete("/{jira_task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_jiratask(
    jira_task_id: str = Path(..., description="The BSON ObjectId of the Jira task as a string"),
    collection = Depends(get_jiratask_collection)
):
    """Deletes a Jira task."""
    validated_jiratask_oid = validate_object_id_sync(jira_task_id)
    delete_result = await collection.delete_one({"_id": validated_jiratask_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Jira task with id {jira_task_id} not found for deletion")
    return

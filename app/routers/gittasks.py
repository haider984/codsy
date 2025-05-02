from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.gittask import GitHubTaskCreate, GitHubTaskInDB
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_gittask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'github_tasks' collection."""
    return db.get_collection("github_tasks")

@router.post("/", response_model=GitHubTaskInDB, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_gittask(
    github_task: GitHubTaskCreate,
    collection = Depends(get_gittask_collection)
):
    """Creates a new GitHub task."""
    try:
        github_task_dict = github_task.model_dump()
        insert_result = await collection.insert_one(github_task_dict)
        created_github_task = await collection.find_one({"_id": insert_result.inserted_id})
        if created_github_task:
            return GitHubTaskInDB(**created_github_task)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="GitHub task could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating GitHub task: {e}")

@router.get("/", response_model=List[GitHubTaskInDB], response_model_by_alias=False)
async def read__all_gittasks(
    collection = Depends(get_gittask_collection)
):
    """Retrieves all GitHub tasks."""
    github_tasks_cursor = collection.find()
    github_tasks = await github_tasks_cursor.to_list(length=None)  # Fetch all GitHub tasks
    return [GitHubTaskInDB(**gt) for gt in github_tasks]

@router.get("/{git_task_id}", response_model=GitHubTaskInDB, response_model_by_alias=False)
async def read_gittask_by_id(
    git_task_id: str = Path(..., description="The BSON ObjectId of the GitHub task as a string"),
    collection = Depends(get_gittask_collection)
):
    """Retrieves a specific GitHub task by ID."""
    validated_github_task_oid = validate_object_id_sync(git_task_id)
    github_task = await collection.find_one({"_id": validated_github_task_oid})
    if github_task:
        return GitHubTaskInDB(**github_task)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"GitHub task with id {git_task_id} not found")

@router.get("/by_status/{status}", response_model=List[GitHubTaskInDB], response_model_by_alias=False)
async def read_gittasks_by_status(
    status: str = Path(..., description="The status of the GitHub tasks to retrieve (e.g., 'pending', 'precessed')"),
    collection = Depends(get_gittask_collection)
):
    """Retrieves all GitHub tasks by their status."""
   
    try:
        # Query the database for tasks with the given status
        query = {"status": status}
        tasks_cursor = collection.find(query)
        tasks_list = await tasks_cursor.to_list(length=None)  # Fetch all tasks with the specified status
        # Return the list of tasks
        return [GitHubTaskInDB(**task) for task in tasks_list]

    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while retrieving tasks with status '{status}': {e}"
        )
    
@router.put("/{git_task_id}", response_model=GitHubTaskInDB, response_model_by_alias=False)
async def update_gittask(
    github_task_update: GitHubTaskCreate,
    git_task_id: str = Path(..., description="The BSON ObjectId of the GitHub task as a string"),
    collection = Depends(get_gittask_collection)
):
    """Updates an existing GitHub task."""
    validated_github_task_oid = validate_object_id_sync(git_task_id)
    github_task_dict = github_task_update.model_dump(exclude_unset=True)
    if not github_task_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_github_task = await collection.find_one_and_update(
        {"_id": validated_github_task_oid},
        {"$set": github_task_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_github_task:
        return GitHubTaskInDB(**updated_github_task)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"GitHub task with id {git_task_id} not found for update")

@router.delete("/{git_task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gittask(
    git_task_id: str = Path(..., description="The BSON ObjectId of the GitHub task as a string"),
    collection = Depends(get_gittask_collection)
):
    """Deletes a GitHub task."""
    validated_github_task_oid = validate_object_id_sync(git_task_id)
    delete_result = await collection.delete_one({"_id": validated_github_task_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"GitHub task with id {git_task_id} not found for deletion")
    return

@router.get("/by_message/{mid}", response_model=List[GitHubTaskInDB], response_model_by_alias=False)
async def read_gittasks_by_message_id(
    mid: str = Path(..., description="The string representation of the message ID (mid)"),
    collection = Depends(get_gittask_collection)
):
    """Retrieves all GitHub tasks associated with a specific message ID (mid) stored as a string."""
    # validated_message_oid = validate_object_id_sync(mid) # REMOVE or comment out

    # Query by the 'mid' field as a STRING
    query = {"mid": mid} # Use the input string directly
    tasks_cursor = collection.find(query)
    tasks_list = await tasks_cursor.to_list(length=None) # Fetch all

    # Basic validation - consider more robust error handling if needed
    try:
        # The tasks retrieved should still conform to GitHubTaskInDB for the response
        return [GitHubTaskInDB(**task) for task in tasks_list]
    except Exception as e:
        # Handle potential validation errors if DB data doesn't match model
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating GitHub task data for message {mid}: {e}"
        )

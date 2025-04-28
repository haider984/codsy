from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.project import ProjectCreate, ProjectInDB # Import Project models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_project_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'projects' collection."""
    return db.get_collection("projects") # Collection name changed

@router.post("/", response_model=ProjectInDB, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_project(
    project: ProjectCreate,
    collection = Depends(get_project_collection)
):
    """Creates a new project."""
    try:
        project_dict = project.model_dump()
        insert_result = await collection.insert_one(project_dict)
        created_project = await collection.find_one({"_id": insert_result.inserted_id})
        if created_project:
            return ProjectInDB(**created_project)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Project could not be created")
    except Exception as e: # Be more specific with exception handling if possible
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating project: {e}")

@router.get("/", response_model=List[ProjectInDB], response_model_by_alias=False)
async def read_projects(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_project_collection)
):
    """Retrieves a list of projects with pagination."""
    projects_cursor = collection.find().skip(skip).limit(limit)
    projects = await projects_cursor.to_list(length=limit)
    return [ProjectInDB(**p) for p in projects]

@router.get("/{pid}", response_model=ProjectInDB, response_model_by_alias=False)
async def read_project(
    pid: str = Path(..., description="The BSON ObjectId of the project (pid) as a string"),
    collection = Depends(get_project_collection)
):
    """Retrieves a specific project by ID (pid)."""
    validated_project_oid = validate_object_id_sync(pid)
    project = await collection.find_one({"_id": validated_project_oid})
    if project:
        return ProjectInDB(**project)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with pid {pid} not found")

@router.put("/{pid}", response_model=ProjectInDB, response_model_by_alias=False)
async def update_project(
    project_update: ProjectCreate,
    pid: str = Path(..., description="The BSON ObjectId of the project (pid) as a string"),
    collection = Depends(get_project_collection)
):
    """Updates an existing project."""
    validated_project_oid = validate_object_id_sync(pid)
    project_dict = project_update.model_dump(exclude_unset=True)
    if not project_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_project = await collection.find_one_and_update(
        {"_id": validated_project_oid},
        {"$set": project_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_project:
        return ProjectInDB(**updated_project)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with pid {pid} not found for update")

@router.delete("/{pid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    pid: str = Path(..., description="The BSON ObjectId of the project (pid) as a string"),
    collection = Depends(get_project_collection)
):
    """Deletes a project."""
    validated_project_oid = validate_object_id_sync(pid)
    delete_result = await collection.delete_one({"_id": validated_project_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with pid {pid} not found for deletion")
    return

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

@router.post("/", response_model=ProjectInDB, status_code=status.HTTP_201_CREATED)
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

@router.get("/{project_id}", response_model=ProjectInDB)
async def read_project(
    project_id: str = Path(..., description="The BSON ObjectId of the project as a string"),
    collection = Depends(get_project_collection)
):
    """Retrieves a specific project by ID."""
    validated_project_oid = validate_object_id_sync(project_id)
    project = await collection.find_one({"_id": validated_project_oid})
    if project:
        return ProjectInDB(**project)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with id {project_id} not found")

# ... (Implement POST, GET /, PUT, DELETE similarly) ...

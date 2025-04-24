from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.project import ProjectCreate, ProjectInDB # Import Project models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_project_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'projects' collection."""
    return db.get_collection("projects") # Collection name changed

@router.get("/{project_id}", response_model=ProjectInDB)
async def read_project(
    project_id: ObjectId = Depends(get_object_id), # Use the validator
    collection = Depends(get_project_collection)
):
    """Retrieves a specific project by ID."""
    project = await collection.find_one({"_id": project_id}) # Query using _id
    if project:
        return ProjectInDB(**project)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with id {project_id} not found")

# ... (Implement POST, GET /, PUT, DELETE similarly) ...

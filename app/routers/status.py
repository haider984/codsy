from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.status import StatusCreate, StatusInDB, StatusIdResponse # Import Status models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_status_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'status' collection."""
    # Ensure the collection name matches your desired DB collection name
    return db.get_collection("status")

# Endpoint to create status - returning full object for now
@router.post("/", response_model=StatusInDB, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_status(
    status_data: StatusCreate,
    collection = Depends(get_status_collection)
):
    """Creates a new status record."""
    try:
        status_dict = status_data.model_dump()
        insert_result = await collection.insert_one(status_dict)
        created_status = await collection.find_one({"_id": insert_result.inserted_id})
        if created_status:
            return StatusInDB(**created_status)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Status record could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating status record: {e}")

# Endpoint to get all status records (consider adding filters, e.g., by pid)
@router.get("/", response_model=List[StatusInDB], response_model_by_alias=False)
async def read_all_status(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_status_collection)
):
    """Retrieves a list of status records with pagination."""
    status_cursor = collection.find().skip(skip).limit(limit)
    status_list = await status_cursor.to_list(length=limit)
    return [StatusInDB(**s) for s in status_list]

# Endpoint to get a specific status record by its ID
@router.get("/{status_id}", response_model=StatusInDB, response_model_by_alias=False)
async def read_status_by_id(
    status_id: str = Path(..., description="The BSON ObjectId of the status record"),
    collection = Depends(get_status_collection)
):
    """Retrieves a specific status record by ID."""
    validated_status_oid = validate_object_id_sync(status_id)
    status_record = await collection.find_one({"_id": validated_status_oid})
    if status_record:
        return StatusInDB(**status_record)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Status record with ID {status_id} not found")

# Endpoint to update a status record
@router.put("/{status_id}", response_model=StatusInDB, response_model_by_alias=False)
async def update_status(
    status_update: StatusCreate, # Use StatusCreate to update pid, start_date, end_date
    status_id: str = Path(..., description="The BSON ObjectId of the status record to update"),
    collection = Depends(get_status_collection)
):
    """Updates an existing status record."""
    validated_status_oid = validate_object_id_sync(status_id)
    status_dict = status_update.model_dump(exclude_unset=True)
    if not status_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_status = await collection.find_one_and_update(
        {"_id": validated_status_oid},
        {"$set": status_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_status:
        return StatusInDB(**updated_status)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Status record with ID {status_id} not found for update")

# Endpoint to delete a status record
@router.delete("/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_status(
    status_id: str = Path(..., description="The BSON ObjectId of the status record to delete"),
    collection = Depends(get_status_collection)
):
    """Deletes a status record."""
    validated_status_oid = validate_object_id_sync(status_id)
    delete_result = await collection.delete_one({"_id": validated_status_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Status record with ID {status_id} not found for deletion")
    return

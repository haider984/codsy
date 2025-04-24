from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.generic import GenericCreate, GenericInDB, Message # Import Generic models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id

router = APIRouter()

async def get_generic_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'generic' collection."""
    return db.get_collection("generic")

@router.post("/", response_model=GenericInDB, status_code=status.HTTP_201_CREATED)
async def create_generic_entry(
    generic_entry: GenericCreate,
    collection = Depends(get_generic_collection)
):
    """Creates a new generic entry (e.g., message log for a session)."""
    try:
        generic_dict = generic_entry.model_dump(mode="json")
        insert_result = await collection.insert_one(generic_dict)
        created_generic = await collection.find_one({"_id": insert_result.inserted_id})
        if created_generic:
            return GenericInDB(**created_generic)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Generic entry could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating generic entry: {e}")

# Endpoint to add a message to an existing generic entry (log)
@router.post("/{generic_id}/messages", response_model=GenericInDB)
async def add_message_to_generic(
    message: Message,
    generic_id: ObjectId = Depends(validate_object_id),
    collection = Depends(get_generic_collection)
):
    """Adds a message to the messages list of a specific generic entry."""
    message_dict = message.model_dump(mode="json")
    updated_generic = await collection.find_one_and_update(
        {"_id": generic_id},
        {"$push": {"messages": message_dict}}, # Use $push to add to the array
        return_document=ReturnDocument.AFTER
    )
    if updated_generic:
        return GenericInDB(**updated_generic)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Generic entry with id {generic_id} not found")


@router.get("/", response_model=List[GenericInDB])
async def read_generic_entries(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_generic_collection)
):
    """Retrieves a list of generic entries with pagination."""
    generic_cursor = collection.find().skip(skip).limit(limit)
    generics = await generic_cursor.to_list(length=limit)
    return [GenericInDB(**gen) for gen in generics]

@router.get("/{generic_id}", response_model=GenericInDB)
async def read_generic_entry(
    generic_id: ObjectId = Depends(validate_object_id),
    collection = Depends(get_generic_collection)
):
    """Retrieves a specific generic entry by ID."""
    generic = await collection.find_one({"_id": generic_id})
    if generic:
        return GenericInDB(**generic)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Generic entry with id {generic_id} not found")

# PUT might replace the entire entry, including messages. Be cautious.
@router.put("/{generic_id}", response_model=GenericInDB)
async def update_generic_entry(
    generic_update: GenericCreate, # Or a GenericUpdate model
    generic_id: ObjectId = Depends(validate_object_id),
    collection = Depends(get_generic_collection)
):
    """Updates an existing generic entry (potentially overwriting messages)."""
    generic_dict = generic_update.model_dump(mode="json", exclude_unset=True)
    if not generic_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_generic = await collection.find_one_and_update(
        {"_id": generic_id},
        {"$set": generic_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_generic:
        return GenericInDB(**updated_generic)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Generic entry with id {generic_id} not found for update")

@router.delete("/{generic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generic_entry(
    generic_id: ObjectId = Depends(validate_object_id),
    collection = Depends(get_generic_collection)
):
    """Deletes a generic entry."""
    delete_result = await collection.delete_one({"_id": generic_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Generic entry with id {generic_id} not found for deletion")
    return

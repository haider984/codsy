from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.message import MessageCreate, MessageInDB, MessageMidResponse # Import Message models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_message_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'messages' collection."""
    return db.get_collection("messages")

@router.post("/", response_model=MessageMidResponse, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_message(
    message: MessageCreate,
    collection = Depends(get_message_collection)
):
    """Creates a new message and returns only its mid."""
    try:
        message_dict = message.model_dump()
        insert_result = await collection.insert_one(message_dict)
        if insert_result.inserted_id:
            return MessageMidResponse(mid=insert_result.inserted_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Message could not be created or ID not retrieved")
    except Exception as e:
        # Consider more specific error handling based on validation etc.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating message: {e}")

@router.get("/", response_model=List[MessageInDB], response_model_by_alias=False)
async def read_all_messages(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_message_collection)
):
    """Retrieves a list of messages with pagination."""
    messages_cursor = collection.find().skip(skip).limit(limit)
    messages = await messages_cursor.to_list(length=limit)
    return [MessageInDB(**msg) for msg in messages]

@router.get("/{mid}", response_model=MessageInDB, response_model_by_alias=False)
async def read_message_by_id(
    mid: str = Path(..., description="The BSON ObjectId of the message (mid) as a string"),
    collection = Depends(get_message_collection)
):
    """Retrieves a specific message by ID (mid)."""
    validated_message_oid = validate_object_id_sync(mid)
    message = await collection.find_one({"_id": validated_message_oid})
    if message:
        return MessageInDB(**message)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message with mid {mid} not found")

@router.put("/{mid}", response_model=MessageInDB, response_model_by_alias=False)
async def update_message(
    message_update: MessageCreate, # Using MessageCreate allows updating most fields
    mid: str = Path(..., description="The BSON ObjectId of the message (mid) as a string"),
    collection = Depends(get_message_collection)
):
    """Updates an existing message."""
    validated_message_oid = validate_object_id_sync(mid)
    # Exclude unset fields to allow partial updates
    message_dict = message_update.model_dump(exclude_unset=True)
    if not message_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_message = await collection.find_one_and_update(
        {"_id": validated_message_oid},
        {"$set": message_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_message:
        return MessageInDB(**updated_message)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message with mid {mid} not found for update")

@router.delete("/{mid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    mid: str = Path(..., description="The BSON ObjectId of the message (mid) as a string"),
    collection = Depends(get_message_collection)
):
    """Deletes a message."""
    validated_message_oid = validate_object_id_sync(mid)
    delete_result = await collection.delete_one({"_id": validated_message_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message with mid {mid} not found for deletion")
    return

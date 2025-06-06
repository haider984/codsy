from fastapi import APIRouter, HTTPException, Depends, status, Path, Query
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.message import MessageCreate, MessageInDB, MessageMidResponse, MessageContentReply # Import Message models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync
from ..models.base import PyObjectId # Import PyObjectId for response model

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

# @router.get("/", response_model=List[MessageContentReply], response_model_by_alias=False)
# async def read_all_messages(
#     collection = Depends(get_message_collection)
# ):
#     """Retrieves content and reply for all messages."""
#     projection = {
#     "content": 1,
#     "reply": 1,
#     "username": 1,
#     "message_datetime": 1,
#     "channel": 1,
#     "_id": 0
#     }

#     messages_cursor = collection.find({}, projection)
#     messages_data = await messages_cursor.to_list(length=None)
#     return [MessageContentReply(**msg) for msg in messages_data]


@router.get("/", response_model=List[MessageContentReply], response_model_by_alias=False)
async def read_messages_by_uid(
    uid: str = Query(None, description="User ID to filter messages"),
    collection = Depends(get_message_collection)
):
    """Retrieves messages by UID if provided; otherwise returns all messages."""
    
    projection = {
        "content": 1,
        "reply": 1,
        "uid": 1,  # Include UID in the response

    }

    query_filter = {"uid": uid} if uid else {}

    messages_cursor = collection.find(query_filter, projection)
    messages_data = await messages_cursor.to_list(length=None)
    return [MessageContentReply(**msg) for msg in messages_data]

# New endpoint to get messages by status
@router.get("/by_status/", response_model=List[MessageMidResponse], response_model_by_alias=False)
async def read_messages_by_status(
    status: str = Query(..., description="The status value to filter messages by (e.g., 'pending', 'processing')"),
    collection = Depends(get_message_collection)
):
    """Retrieves a list of message IDs filtered by status."""
    query = {"status": status}
    messages_cursor = collection.find(query, {"_id": 1})  # Only fetch the '_id' field
    messages = await messages_cursor.to_list(length=None)  # Fetch all matching messages
    try: 
        return [MessageMidResponse(mid=msg["_id"]) for msg in messages]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating message data from DB: {e}"
        )

# Endpoint to get messages by PID
@router.get("/by_pid/", response_model=List[PyObjectId], response_model_by_alias=False)
async def read_message_ids_by_pid(
    pid: str = Query(..., description="The string representation of the project ID (pid) to filter messages by"),
    collection = Depends(get_message_collection)
):
    """Retrieves a list of message IDs (mid) for a given project ID (pid) stored as a string."""
    # validated_pid = validate_object_id_sync(pid) # REMOVE or comment out this line

    # Query only for the _id field, matching pid as a STRING
    query = {"pid": pid} # Use the input string directly in the query
    projection = {"_id": 1}
    messages_cursor = collection.find(query, projection)

    # Extract the _id values
    # Note: The response model is List[PyObjectId], so the _id values themselves
    # should still be ObjectIds, which is correct.
    message_ids = [doc["_id"] async for doc in messages_cursor]

    return message_ids

@router.get("/by_processed_status/", response_model=List[MessageInDB], response_model_by_alias=False)
async def read_messages_by_processed_status(
    processed_status: bool = Query(..., description="Filter messages by their 'processed' status (true or false)"),
    collection = Depends(get_message_collection)
):
    """Retrieves a list of all messages filtered by the provided 'processed' status."""
    # Use the boolean value from the query parameter
    query = {"processed": processed_status}
    messages_cursor = collection.find(query)
    filtered_messages = await messages_cursor.to_list(length=None) # Fetch all
    try:
        return [MessageInDB(**msg) for msg in filtered_messages]
    except Exception as e:
         raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating message data from DB: {e}"
        )

@router.get("/{mid}", response_model=MessageInDB, response_model_by_alias=False)
async def read_message_by_id(
    mid: str = Path(..., description="The BSON ObjectId of the message (mid) as a string"),
    collection = Depends(get_message_collection)
):
    """Retrieves a specific message by ID (mid)."""
    validated_message_oid = validate_object_id_sync(mid)
    message = await collection.find_one({"_id": validated_message_oid})
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message with mid {mid} not found")
    # Need to handle potential validation errors if data in DB doesn't match model
    try:
        return MessageInDB(**message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating message data from DB for mid {mid}: {e}"
        )

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
    if not updated_message:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message with mid {mid} not found for update")
    # Need to handle potential validation errors if data in DB doesn't match model
    try:
        return MessageInDB(**updated_message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating updated message data from DB for mid {mid}: {e}"
        )

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
    # No return needed for 204
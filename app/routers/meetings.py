from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.meeting import MeetingCreate, MeetingInDB # Import Meeting models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_meeting_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'meetings' collection."""
    return db.get_collection("meetings")

@router.post("/", response_model=MeetingInDB, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting: MeetingCreate,
    collection = Depends(get_meeting_collection)
):
    """Creates a new meeting."""
    try:
        # Use mode="json" for HttpUrl and handle datetime serialization if needed
        meeting_dict = meeting.model_dump(mode="json")
        insert_result = await collection.insert_one(meeting_dict)
        created_meeting = await collection.find_one({"_id": insert_result.inserted_id})
        if created_meeting:
            return MeetingInDB(**created_meeting)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Meeting could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating meeting: {e}")

@router.get("/", response_model=List[MeetingInDB])
async def read_meetings(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_meeting_collection)
):
    """Retrieves a list of meetings with pagination."""
    meetings_cursor = collection.find().skip(skip).limit(limit)
    meetings = await meetings_cursor.to_list(length=limit)
    return [MeetingInDB(**meeting) for meeting in meetings]

@router.get("/{meeting_id}", response_model=MeetingInDB)
async def read_meeting(
    meeting_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_meeting_collection)
):
    """Retrieves a specific meeting by ID."""
    meeting = await collection.find_one({"_id": meeting_id})
    if meeting:
        return MeetingInDB(**meeting)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting with id {meeting_id} not found")

@router.put("/{meeting_id}", response_model=MeetingInDB)
async def update_meeting(
    meeting_update: MeetingCreate, # Consider a MeetingUpdate model
    meeting_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_meeting_collection)
):
    """Updates an existing meeting."""
    meeting_dict = meeting_update.model_dump(mode="json", exclude_unset=True)
    if not meeting_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_meeting = await collection.find_one_and_update(
        {"_id": meeting_id},
        {"$set": meeting_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_meeting:
        return MeetingInDB(**updated_meeting)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting with id {meeting_id} not found for update")

@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_meeting_collection)
):
    """Deletes a meeting."""
    delete_result = await collection.delete_one({"_id": meeting_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting with id {meeting_id} not found for deletion")
    return

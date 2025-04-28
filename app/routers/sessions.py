from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.session import SessionCreate, SessionInDB # Import Session models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_session_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'sessions' collection."""
    return db.get_collection("sessions")

@router.post("/", response_model=SessionInDB, status_code=status.HTTP_201_CREATED, response_model_by_alias=False)
async def create_session(
    session: SessionCreate,
    collection = Depends(get_session_collection)
):
    """Creates a new session."""
    try:
        session_dict = session.model_dump()
        insert_result = await collection.insert_one(session_dict)
        created_session = await collection.find_one({"_id": insert_result.inserted_id})
        if created_session:
            return SessionInDB(**created_session)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating session: {e}")

@router.get("/", response_model=List[SessionInDB], response_model_by_alias=False)
async def read_sessions(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_session_collection)
):
    """Retrieves a list of sessions with pagination."""
    sessions_cursor = collection.find().skip(skip).limit(limit)
    sessions = await sessions_cursor.to_list(length=limit)
    return [SessionInDB(**session) for session in sessions]

@router.get("/{session_id}", response_model=SessionInDB, response_model_by_alias=False)
async def read_session(
    session_id: str = Path(..., description="The BSON ObjectId of the session as a string"),
    collection = Depends(get_session_collection)
):
    """Retrieves a specific session by ID."""
    validated_session_oid = validate_object_id_sync(session_id)
    session = await collection.find_one({"_id": validated_session_oid})
    if session:
        return SessionInDB(**session)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session with id {session_id} not found")

@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str = Path(..., description="The BSON ObjectId of the session as a string"),
    collection = Depends(get_session_collection)
):
    """Deletes a session."""
    validated_session_oid = validate_object_id_sync(session_id)
    delete_result = await collection.delete_one({"_id": validated_session_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session with id {session_id} not found for deletion")
    return

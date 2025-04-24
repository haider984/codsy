from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.transcript import TranscriptCreate, TranscriptInDB # Import Transcript models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_transcript_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'transcripts' collection."""
    return db.get_collection("transcripts")

@router.post("/", response_model=TranscriptInDB, status_code=status.HTTP_201_CREATED)
async def create_transcript(
    transcript: TranscriptCreate,
    collection = Depends(get_transcript_collection)
):
    """Creates a new transcript."""
    try:
        transcript_dict = transcript.model_dump()
        insert_result = await collection.insert_one(transcript_dict)
        created_transcript = await collection.find_one({"_id": insert_result.inserted_id})
        if created_transcript:
            return TranscriptInDB(**created_transcript)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transcript could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating transcript: {e}")

@router.get("/", response_model=List[TranscriptInDB])
async def read_transcripts(
    session_id: str | None = None, # Allow filtering by session_id
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_transcript_collection)
):
    """Retrieves a list of transcripts with pagination, optionally filtered by session_id."""
    query = {}
    if session_id:
        try:
            query["session_id"] = ObjectId(session_id)
        except Exception:
             raise HTTPException(status_code=400, detail=f"Invalid session_id format: {session_id}")

    transcripts_cursor = collection.find(query).skip(skip).limit(limit)
    transcripts = await transcripts_cursor.to_list(length=limit)
    return [TranscriptInDB(**tr) for tr in transcripts]

@router.get("/{transcript_id}", response_model=TranscriptInDB)
async def read_transcript(
    transcript_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_transcript_collection)
):
    """Retrieves a specific transcript by ID."""
    transcript = await collection.find_one({"_id": transcript_id})
    if transcript:
        return TranscriptInDB(**transcript)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transcript with id {transcript_id} not found")

@router.put("/{transcript_id}", response_model=TranscriptInDB)
async def update_transcript(
    transcript_update: TranscriptCreate, # Consider a TranscriptUpdate model
    transcript_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_transcript_collection)
):
    """Updates an existing transcript."""
    transcript_dict = transcript_update.model_dump(exclude_unset=True)
    if not transcript_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_transcript = await collection.find_one_and_update(
        {"_id": transcript_id},
        {"$set": transcript_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_transcript:
        return TranscriptInDB(**updated_transcript)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transcript with id {transcript_id} not found for update")

@router.delete("/{transcript_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transcript(
    transcript_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_transcript_collection)
):
    """Deletes a transcript."""
    delete_result = await collection.delete_one({"_id": transcript_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transcript with id {transcript_id} not found for deletion")
    return

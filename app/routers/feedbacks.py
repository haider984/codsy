from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.feedback import FeedbackCreate, FeedbackInDB # Import Feedback models
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import get_object_id

router = APIRouter()

async def get_feedback_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'feedbacks' collection."""
    return db.get_collection("feedbacks")

@router.post("/", response_model=FeedbackInDB, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback: FeedbackCreate,
    collection = Depends(get_feedback_collection)
):
    """Creates new feedback."""
    try:
        feedback_dict = feedback.model_dump()
        insert_result = await collection.insert_one(feedback_dict)
        created_feedback = await collection.find_one({"_id": insert_result.inserted_id})
        if created_feedback:
            return FeedbackInDB(**created_feedback)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Feedback could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating feedback: {e}")

@router.get("/", response_model=List[FeedbackInDB])
async def read_feedbacks(
    session_id: str | None = None, # Allow filtering by session_id
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_feedback_collection)
):
    """Retrieves a list of feedbacks with pagination, optionally filtered by session_id."""
    query = {}
    if session_id:
        try:
            query["session_id"] = ObjectId(session_id)
        except Exception:
             raise HTTPException(status_code=400, detail=f"Invalid session_id format: {session_id}")

    feedbacks_cursor = collection.find(query).skip(skip).limit(limit)
    feedbacks = await feedbacks_cursor.to_list(length=limit)
    return [FeedbackInDB(**fb) for fb in feedbacks]

@router.get("/{feedback_id}", response_model=FeedbackInDB)
async def read_feedback(
    feedback_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_feedback_collection)
):
    """Retrieves specific feedback by its ID."""
    feedback = await collection.find_one({"_id": feedback_id})
    if feedback:
        return FeedbackInDB(**feedback)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feedback with id {feedback_id} not found")

@router.put("/{feedback_id}", response_model=FeedbackInDB)
async def update_feedback(
    feedback_update: FeedbackCreate, # Consider a FeedbackUpdate model
    feedback_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_feedback_collection)
):
    """Updates existing feedback."""
    feedback_dict = feedback_update.model_dump(exclude_unset=True)
    if not feedback_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_feedback = await collection.find_one_and_update(
        {"_id": feedback_id},
        {"$set": feedback_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_feedback:
        return FeedbackInDB(**updated_feedback)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feedback with id {feedback_id} not found for update")

@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: ObjectId = Depends(get_object_id),
    collection = Depends(get_feedback_collection)
):
    """Deletes feedback."""
    delete_result = await collection.delete_one({"_id": feedback_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feedback with id {feedback_id} not found for deletion")
    return

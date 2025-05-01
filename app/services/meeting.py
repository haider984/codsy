# app/services/meeting_service.py
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection
import logging

from ..db.mongodb import get_database, get_collection
from ..models.meeting import MeetingCreate, MeetingInDB # Import necessary models

logger = logging.getLogger(__name__)

async def add_meeting(meeting_data: MeetingCreate) -> MeetingInDB | None:
    """
    Inserts a meeting document into the database via the service layer.

    Args:
        meeting_data: A MeetingCreate Pydantic model instance.

    Returns:
        A MeetingInDB instance of the created meeting, or None if creation fails.
    """
    try:
        db: AsyncIOMotorDatabase = await get_database()
        collection: AsyncIOMotorCollection = get_collection(db, "meetings")
        meeting_dict = meeting_data.model_dump(by_alias=True)

        insert_result = await collection.insert_one(meeting_dict)
        if insert_result.inserted_id:
            # Fetch the newly created document to return it fully populated
            created_meeting_doc = await collection.find_one({"_id": insert_result.inserted_id})
            if created_meeting_doc:
                logger.info(f"Service inserted meeting linked to mid: {meeting_data.mid}, meet_id: {insert_result.inserted_id}")
                # Validate and return using the DB model
                return MeetingInDB(**created_meeting_doc)
            else:
                 logger.error(f"Service meeting insertion succeeded (meet_id: {insert_result.inserted_id}), but failed to fetch the created document.")
                 return None
        else:
            logger.error(f"Service meeting insertion failed for mid: {meeting_data.mid}, no ID returned.")
            return None
    except Exception as e:
        logger.error(f"Error during service meeting insertion for mid {meeting_data.mid}: {e}", exc_info=True)
        return None

# Add other meeting-related service functions here later
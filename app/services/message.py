# app/services/message_service.py
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection
import logging

from ..db.mongodb import get_database, get_collection  # Import DB accessors
from ..models.message import MessageCreate # Import the Pydantic model

logger = logging.getLogger(__name__)

async def add_message(message_data: MessageCreate) -> ObjectId | None:
    """
    Inserts a message document into the database via the service layer.

    Args:
        message_data: A MessageCreate Pydantic model instance.

    Returns:
        The ObjectId of the inserted message, or None if insertion fails.
    """
    try:
        db: AsyncIOMotorDatabase = await get_database() # Get DB connection
        collection: AsyncIOMotorCollection = get_collection(db, "messages") # Get collection
        message_dict = message_data.model_dump(by_alias=True) # Use by_alias if your model uses them

        insert_result = await collection.insert_one(message_dict)
        if insert_result.inserted_id:
            logger.info(f"Service inserted message, received mid: {insert_result.inserted_id}")
            return insert_result.inserted_id
        else:
            logger.error("Service message insertion failed, no ID returned.")
            return None
    except Exception as e:
        logger.error(f"Error during service message insertion: {e}", exc_info=True)
        return None

# You can add other message-related service functions here later
# e.g., get_message_by_id, update_message_status, etc.
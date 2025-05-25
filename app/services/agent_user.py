from typing import List, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import os
import requests
import logging

from app.models.agent_user import AgentUserCreate, AgentUserUpdate, AgentUserInDB, UserStatus
from app.db.mongodb import get_database

# DATABASE_NAME = "codsy" # This is not used by the corrected get_db function below
COLLECTION_NAME = "agent_users"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_db() -> AsyncIOMotorDatabase:
    # Call get_database without arguments, as it's defined in app.db.mongodb
    return await get_database()

async def create_agent_user(agent_user_data: AgentUserCreate, db: AsyncIOMotorDatabase) -> AgentUserInDB:
    agent_user_dict = agent_user_data.model_dump()
    result = await db[COLLECTION_NAME].insert_one(agent_user_dict)
    created_agent_user = await db[COLLECTION_NAME].find_one({"_id": result.inserted_id})
    created_agent_user["id"] = str(created_agent_user["_id"])
    return AgentUserInDB.model_validate(created_agent_user)

async def get_agent_user_by_id(agent_user_id: str, db: AsyncIOMotorDatabase) -> Optional[AgentUserInDB]:
    if not ObjectId.is_valid(agent_user_id):
        return None
    agent_user = await db[COLLECTION_NAME].find_one({"_id": ObjectId(agent_user_id)})
    if agent_user:
        agent_user["id"] = str(agent_user["_id"])
        return AgentUserInDB.model_validate(agent_user)
    return None

async def get_agent_user_by_uid(uid: str, db: AsyncIOMotorDatabase) -> Optional[AgentUserInDB]:
    agent_user = await db[COLLECTION_NAME].find_one({"uid": uid})
    if agent_user:
        agent_user["id"] = str(agent_user["_id"])
        return AgentUserInDB.model_validate(agent_user)
    return None

async def get_all_agent_users(db: AsyncIOMotorDatabase):
    """
    Fetch all agent users from the MongoDB 'agent_users' collection.
    Ensures each document has an 'id' field instead of '_id'.
    """
    try:
        cursor = db["agent_users"].find({})
        users = await cursor.to_list(length=None)

        for user in users:
            user["id"] = str(user["_id"])
            user.pop("_id", None)  # Remove _id to avoid Pydantic issues
        return users

    except Exception as e:
        print(f"Error in get_all_agent_users: {e}")
        raise


async def update_agent_user(agent_user_id: str, agent_user_update_data: AgentUserUpdate, db: AsyncIOMotorDatabase) -> Optional[AgentUserInDB]:
    if not ObjectId.is_valid(agent_user_id):
        return None
    
    update_data = agent_user_update_data.model_dump(exclude_unset=True)

    if not update_data:
        # Return current state if no update data is provided
        return await get_agent_user_by_id(agent_user_id, db)

    await db[COLLECTION_NAME].update_one(
        {"_id": ObjectId(agent_user_id)},
        {"$set": update_data}
    )
    updated_agent_user = await get_agent_user_by_id(agent_user_id, db)
    return updated_agent_user

async def get_agent_user_by_email(email: str, db: AsyncIOMotorDatabase) -> Optional[AgentUserInDB]:
    agent_user = await db[COLLECTION_NAME].find_one({"email": email})
    if agent_user:
        agent_user["id"] = str(agent_user["_id"])
        return AgentUserInDB.model_validate(agent_user)
    return None

async def get_agent_user_status_by_email(email: str, db: AsyncIOMotorDatabase) -> Optional[UserStatus]:
    """
    Retrieves the status of an agent user by their email.
    """
    agent_user = await db[COLLECTION_NAME].find_one({"email": email}, {"status": 1}) # Only fetch the status field
    if agent_user:
        return UserStatus(agent_user["status"]) # Cast to UserStatus Enum
    return None

async def delete_agent_user(agent_user_id: str, db: AsyncIOMotorDatabase) -> bool:
    if not ObjectId.is_valid(agent_user_id):
        return False
    result = await db[COLLECTION_NAME].delete_one({"_id": ObjectId(agent_user_id)})
    return result.deleted_count > 0

# Add new function to fetch GROQ API key by email
# async def get_groq_api_key(email: str, db: Optional[AsyncIOMotorDatabase] = None) -> Tuple[bool, str]:
#     """
#     Fetch the GROQ API key for a user by their email.
    
#     Args:
#         email: The user's email address
#         db: Optional database connection, will be created if not provided
        
#     Returns:
#         Tuple of (is_allowed, api_key):
#         - is_allowed: True if the user is allowed to use the service
#         - api_key: The user's GROQ API key if allowed, empty string otherwise
#     """
#     try:
#         if not email or "@" not in email:
#             logger.warning(f"Invalid email format for GROQ API key lookup: {email}")
#             return False, ""
            
#         # Get database connection if not provided
#         if db is None:
#             db = await get_db()
            
#         # Query the database for the user
#         agent_user = await db[COLLECTION_NAME].find_one({"email": email})
        
#         if not agent_user:
#             logger.warning(f"User not found for email: {email}")
#             return False, ""
            
#         # Check if user is allowed
#         if agent_user.get("status") != "allowed":
#             logger.warning(f"User {email} is not allowed to use the service")
#             return False, ""
            
#         # Get the API key
#         api_key = agent_user.get("groq_api", "")
#         if not api_key:
#             logger.warning(f"No GROQ API key found for user {email}")
#             return True, ""  # User is allowed but no API key
            
#         return True, api_key
        
#     except Exception as e:
#         logger.error(f"Error fetching GROQ API key for {email}: {e}")
#         return False, ""

# Synchronous version for contexts where async isn't supported
def get_groq_api_key_sync(email: str, base_api_url: str) -> Tuple[bool, str]:
    """
    Synchronous version to fetch the GROQ API key using the REST API endpoint.
    
    Args:
        email: The user's email address
        base_api_url: The base URL for the API
        
    Returns:
        Tuple of (is_allowed, api_key)
    """
    if not email or "@" not in email:
        logger.warning(f"Invalid email format for GROQ API key lookup: {email}")
        return False, ""
        
    try:
        # First check if user is allowed
        status_url = f"{base_api_url}/api/v1/agent_users/status/email/{email}"
        status_response = requests.get(status_url, timeout=10)
        
        if status_response.status_code != 200 or status_response.json() != "allowed":
            logger.warning(f"User {email} is not allowed to use the service")
            return False, ""
            
        # Now get the full user data to extract the API key
        user_url = f"{base_api_url}/api/v1/agent_users/{email}"
        user_response = requests.get(user_url, timeout=10)
        
        if user_response.status_code != 200:
            logger.warning(f"Failed to fetch user data for {email}")
            return True, ""  # User is allowed but we couldn't get the API key
            
        user_data = user_response.json()
        api_key = user_data.get("groq_api", "")
        
        if not api_key:
            logger.warning(f"No GROQ API key found for user {email}")
            return True, ""
            
        return True, api_key
        
    except Exception as e:
        logger.error(f"Error fetching GROQ API key for {email}: {e}")
        return False, ""

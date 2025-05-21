from typing import List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.agent_user import AgentUserCreate, AgentUserUpdate, AgentUserInDB, UserStatus
from app.db.mongodb import get_database

# DATABASE_NAME = "codsy" # This is not used by the corrected get_db function below
COLLECTION_NAME = "agent_users"

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

async def get_all_agent_users(db: AsyncIOMotorDatabase) -> List[AgentUserInDB]:
    agent_users = []
    cursor = db[COLLECTION_NAME].find().skip(skip).limit(limit)
    async for agent_user_doc in cursor:
        agent_user_doc["id"] = str(agent_user_doc["_id"])
        agent_users.append(AgentUserInDB.model_validate(agent_user_doc))
    return agent_users

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

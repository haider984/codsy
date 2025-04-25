from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.agents import AgentCreate, AgentInDB
from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

router = APIRouter()

async def get_agent_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'agents' collection."""
    return db.get_collection("agents")

@router.post("/", response_model=AgentInDB, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    collection = Depends(get_agent_collection)
):
    """Creates a new agent."""
    try:
        agent_dict = agent.model_dump()
        insert_result = await collection.insert_one(agent_dict)
        created_agent = await collection.find_one({"_id": insert_result.inserted_id})
        if created_agent:
            return AgentInDB(**created_agent)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Agent could not be created")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error creating agent: {e}")

@router.get("/", response_model=List[AgentInDB])
async def read_agents(
    skip: int = 0,
    limit: int = 100,
    collection = Depends(get_agent_collection)
):
    """Retrieves a list of agents with pagination."""
    agents_cursor = collection.find().skip(skip).limit(limit)
    agents = await agents_cursor.to_list(length=limit)
    return [AgentInDB(**agent) for agent in agents]

@router.get("/{agent_id}", response_model=AgentInDB)
async def read_agent(
    agent_id: str = Path(..., description="The BSON ObjectId of the agent as a string"),
    collection = Depends(get_agent_collection)
):
    """Retrieves a specific agent by ID."""
    validated_agent_oid = validate_object_id_sync(agent_id)
    agent = await collection.find_one({"_id": validated_agent_oid})
    if agent:
        return AgentInDB(**agent)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with id {agent_id} not found")

@router.put("/{agent_id}", response_model=AgentInDB)
async def update_agent(
    agent_update: AgentCreate,
    agent_id: str = Path(..., description="The BSON ObjectId of the agent as a string"),
    collection = Depends(get_agent_collection)
):
    """Updates an existing agent."""
    validated_agent_oid = validate_object_id_sync(agent_id)

    agent_dict = agent_update.model_dump(exclude_unset=True)
    if not agent_dict:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

    updated_agent = await collection.find_one_and_update(
        {"_id": validated_agent_oid},
        {"$set": agent_dict},
        return_document=ReturnDocument.AFTER
    )
    if updated_agent:
        return AgentInDB(**updated_agent)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with id {agent_id} not found for update")

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str = Path(..., description="The BSON ObjectId of the agent as a string"),
    collection = Depends(get_agent_collection)
):
    """Deletes an agent."""
    validated_agent_oid = validate_object_id_sync(agent_id)
    delete_result = await collection.delete_one({"_id": validated_agent_oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with id {agent_id} not found for deletion")
    return

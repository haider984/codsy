from fastapi import APIRouter, HTTPException, Depends, status, Path, Query
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from pymongo import ReturnDocument

from ..models.status import ProjectStatusDetails
from ..models.jiratask import JiraTaskInDB
from ..models.gittask import GitHubTaskInDB
from ..models.base import PyObjectId

from ..db.mongodb import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..utils.dependencies import validate_object_id_sync

# --- Add Logging ---
import logging
logging.basicConfig(level=logging.INFO) # Configure basic logging (adjust level as needed, e.g., logging.DEBUG)
logger = logging.getLogger(__name__)
# --- End Logging Setup ---

router = APIRouter()

async def get_status_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Dependency to get the 'status' collection."""
    # Ensure the collection name matches your desired DB collection name
    return db.get_collection("status")

async def get_message_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    # Ensure this collection name EXACTLY matches your MongoDB collection
    collection_name = "messages"
    logger.debug(f"Accessing Messages collection: {collection_name}")
    return db.get_collection(collection_name)

async def get_jiratask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    # Ensure this collection name EXACTLY matches your MongoDB collection
    collection_name = "jira_tasks"
    logger.debug(f"Accessing Jira task collection: {collection_name}")
    return db.get_collection(collection_name) # Verify this name!

async def get_gittask_collection(db: AsyncIOMotorDatabase = Depends(get_database)):
    # Ensure this collection name EXACTLY matches your MongoDB collection
    collection_name = "github_tasks"
    logger.debug(f"Accessing Git task collection: {collection_name}")
    return db.get_collection(collection_name) # Verify this name!

@router.get(
    "/{pid}",
    response_model=ProjectStatusDetails,
    response_model_by_alias=False,
    summary="Get Jira and Git tasks for a project via associated messages, optionally filtered by date"
)
async def get_project_status_details(
    pid: str = Path(..., description="The string representation of the project ID (pid)"),
    start_date: Optional[datetime] = Query(None, description="Optional start date (ISO format) to filter tasks"),
    end_date: Optional[datetime] = Query(None, description="Optional end date (ISO format) to filter tasks"),
    message_collection = Depends(get_message_collection),
    jira_collection = Depends(get_jiratask_collection),
    git_collection = Depends(get_gittask_collection)
):
    """
    Retrieves Jira and GitHub tasks associated with a specific project ID (pid)
    by first finding messages linked to the project (using string pid),
    then tasks linked to those messages (using string mid).
    Tasks can be filtered by their update/creation timestamp using optional date query parameters.
    """
    logger.info(f"Attempting to get status details for pid string: {pid}")

    # --- Step 1: Get Message IDs (mids) for the Project ID (pid) ---
    message_query = {"pid": pid}
    message_projection = {"_id": 1}
    logger.info(f"Querying messages collection with STRING pid: {message_query}")
    try:
        message_cursor = message_collection.find(message_query, message_projection)
        message_ids_objectid: List[ObjectId] = [doc["_id"] async for doc in message_cursor]
        logger.info(f"Found {len(message_ids_objectid)} message IDs for string pid '{pid}'.")
        logger.debug(f"Message ObjectIDs found: {message_ids_objectid}")
    except Exception as e:
        logger.error(f"Error querying message IDs for string pid '{pid}': {e}")
        raise HTTPException(status_code=500, detail="Error fetching message IDs")

    if not message_ids_objectid:
        logger.warning(f"No messages found for string pid '{pid}'. Returning empty task lists.")
        return ProjectStatusDetails(jira_tasks=[], git_tasks=[])

    # --- Step 2 & 3: Get Jira and Git tasks by Message IDs (mids) ---
    message_ids_str: List[str] = [str(mid) for mid in message_ids_objectid]
    logger.info(f"Converted message IDs to strings for task query: {message_ids_str}")

    # --- Debugging Query Construction ---
    task_query = {}
    if len(message_ids_str) == 1:
        # Simplify query for the single ID case for debugging
        task_query = {"mid": message_ids_str[0]}
        logger.info(f"Querying task collections with single STRING 'mid': {task_query}")
    elif len(message_ids_str) > 1:
        task_query = {"mid": {"$in": message_ids_str}}
        logger.info(f"Querying task collections with STRING 'mid' in {len(message_ids_str)} IDs using $in.")
    else:
        # Should be caught above, but defensive check
        logger.warning("Logical error: No message IDs but proceeded to task query.")
        return ProjectStatusDetails(jira_tasks=[], git_tasks=[]) # Return empty

    logger.debug(f"Effective Task query being used: {task_query}")
    # --- End Debugging Query Construction ---

    try:
        # Use the constructed task_query
        jira_tasks_cursor = jira_collection.find(task_query)
        git_tasks_cursor = git_collection.find(task_query)

        jira_tasks_list_raw = await jira_tasks_cursor.to_list(length=None)
        git_tasks_list_raw = await git_tasks_cursor.to_list(length=None)
        logger.info(f"Found {len(jira_tasks_list_raw)} raw Jira tasks and {len(git_tasks_list_raw)} raw Git tasks.")

    except Exception as e:
        logger.error(f"Error querying tasks by message IDs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while fetching tasks by message IDs: {e}"
        )

    # --- Step 4 & 5: Filter tasks by date and Validate ---
    logger.info(f"Filtering tasks between {start_date} and {end_date} (if specified).")
    validated_jira_tasks = []
    skipped_jira_count = 0
    for task in jira_tasks_list_raw:
        try:
            # Pydantic models expect ObjectId for mid, but data has string.
            # Temporarily convert mid back to ObjectId for validation IF NEEDED by model.
            # It's better to fix data or adjust model permanently.
            # For now, let's assume the model validation handles the string->ObjectId conversion via PyObjectId
            # If validation fails here, the model needs adjustment or data needs fixing.
            jira_task = JiraTaskInDB(**task)
            task_date = getattr(jira_task, "updated_date", None) # Assumes 'updated_date'
            date_match = True
            if task_date:
                 if start_date and task_date < start_date:
                     date_match = False
                 if end_date and task_date > end_date:
                     date_match = False
            else:
                 if start_date or end_date:
                      logger.debug(f"Jira task {getattr(jira_task, 'jira_task_id', 'UNKNOWN')} missing date field for filtering.")
                      # date_match = False # Exclude if filtering is on and date is missing

            if date_match:
                validated_jira_tasks.append(jira_task)
            else:
                 skipped_jira_count += 1
        except Exception as e:
             skipped_jira_count += 1
             logger.warning(f"Skipping Jira task due to validation/processing error: {e}. Task data: {task}")
             continue
    logger.info(f"Validated {len(validated_jira_tasks)} Jira tasks. Skipped {skipped_jira_count} due to date filter or validation errors.")

    validated_git_tasks = []
    skipped_git_count = 0
    for task in git_tasks_list_raw:
        try:
            # Similar potential issue with mid type during validation
            git_task = GitHubTaskInDB(**task)
            task_date = getattr(git_task, "creation_date", None) # Assumes 'creation_date'
            date_match = True
            if task_date:
                if start_date and task_date < start_date:
                    date_match = False
                if end_date and task_date > end_date:
                    date_match = False
            else:
                 if start_date or end_date:
                      logger.debug(f"Git task {getattr(git_task, 'git_task_id', 'UNKNOWN')} missing date field for filtering.")
                      # date_match = False # Exclude if filtering is on and date is missing

            if date_match:
                validated_git_tasks.append(git_task)
            else:
                 skipped_git_count += 1
        except Exception as e:
            skipped_git_count += 1
            logger.warning(f"Skipping GitHub task due to validation/processing error: {e}. Task data: {task}")
            continue
    logger.info(f"Validated {len(validated_git_tasks)} Git tasks. Skipped {skipped_git_count} due to date filter or validation errors.")

    # --- Step 6: Return Combined Result ---
    logger.info("Returning final task lists.")
    return ProjectStatusDetails(
        jira_tasks=validated_jira_tasks,
        git_tasks=validated_git_tasks
    )

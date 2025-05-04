import os
import time
import logging
import requests
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from ..services.git_app import process_query
from ..services.jira_app import process_query_jira
from ..celery_app import celery_app

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL", "http://web:8000")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

class TaskProcessor:
    def __init__(self):
        pass

    def fetch_pending_tasks(self, task_type):
        """Fetch all pending tasks of a specific type (git or jira)"""
        try:
            endpoint = f"{BASE_API_URL}/api/v1/{task_type}tasks/?status=pending"
            response = requests.get(endpoint)
            response.raise_for_status()
            tasks = response.json()
            logger.info(f"Found {len(tasks)} pending {task_type} tasks")
            return tasks
        except Exception as e:
            logger.error(f"Error fetching pending {task_type} tasks: {e}")
            return []

    def process_git_task(self, title, description):
        """Process GitHub task by calling your existing GitHub process function"""
        try:
            # Combine title and description as requested
            combined_input = f"{title}: {description}"
            logger.info(f"Processing GitHub task: {combined_input}")
            
            # Call your existing GitHub process function
            response = process_query(combined_input)
            logger.debug(f"Git task response: {response}")
            return response
        
        except Exception as e:
            logger.error(f"Error processing GitHub task: {e}")
            error_response = {
                "status": "error",
                "message": f"Failed to process GitHub task: {str(e)}",
                "error": str(e)
            }
            return json.dumps(error_response)

    def process_jira_task(self, title, description):
        """Process Jira task by calling your existing Jira process function"""
        try:
            # Combine title and description as requested
            combined_input = f"{title}: {description}"
            logger.info(f"Processing Jira task: {combined_input}")
            
            # Call your existing Jira process function
            response = process_query_jira(combined_input)
            logger.debug(f"Jira task response: {response}")
            return response
        
        except Exception as e:
            logger.error(f"Error processing Jira task: {e}")
            error_response = {
                "status": "error",
                "message": f"Failed to process Jira task: {str(e)}",
                "error": str(e)
            }
            return json.dumps(error_response)

    def analyze_response(self, task_type, response_text):
        """Analyze the response from the API call using LLM to determine status"""
        global client
        if not client:
            client = Groq(api_key=GROQ_API_KEY)

        try:
            prompt = f"""
            Analyze the following {task_type} API response and determine if the operation was successful or resulted in an error.
            
            Response: {response_text}
            
            Return ONLY one of the following status values:
            - "completed" if the operation was successful
            - "failed" if there was an error
            - "pending" if the status is unclear
            
            Status:
            """
            
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10
            )
            
            analysis_result = response.choices[0].message.content.strip().lower()
            
            # Normalize the result
            if "completed" in analysis_result or "success" in analysis_result:
                return "successful"
            elif "failed" in analysis_result or "error" in analysis_result:
                return "failed"
            else:
                logger.warning(f"LLM analysis returned unclear status: {analysis_result}. Defaulting to 'pending'.")
                return "pending"
                
        except Exception as e:
            logger.error(f"Error analyzing response with LLM: {e}")
            return "pending"  # Default to pending if analysis fails

    def update_task_status(self, task_type, task_id, status, reply):
        """Update the task status in the database"""
        try:
            endpoint = f"{BASE_API_URL}/api/v1/{task_type}tasks/{task_id}"
            
            # Get current task data
            current_task_response = requests.get(endpoint)
            current_task_response.raise_for_status()
            current_task = current_task_response.json()
            
            # Update task fields without checking for existing values
            current_task["status"] = status
            current_task["reply"] = reply  # Set the reply regardless of previous value
            current_task["completion_date"] = datetime.now(timezone.utc).isoformat()

            # Log the task before updating
            logger.info(f"Updating {task_type} task {task_id} with status: {status}")

            # Send update request
            update_response = requests.put(endpoint, json=current_task)
            update_response.raise_for_status()

            logger.info(f"Successfully updated {task_type} task {task_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating {task_type} task {task_id} to status {status}: {e}")
            logger.debug(f"Update payload for task {task_id}: {current_task}")
            return False

    def process_all_tasks(self):
        """Process all pending Git and Jira tasks"""
        # Process Git tasks
        git_tasks = self.fetch_pending_tasks("git")
        for task in git_tasks:
            task_id = task.get("git_task_id")
            if not task_id:
                logger.warning(f"Skipping Git task with missing ID: {task}")
                continue
            title = task.get("title", "")
            description = task.get("description", "")
            
            # Process the Git task
            response = self.process_git_task(title, description)
            
            # Analyze the response
            status = self.analyze_response("git", response)
            
            # Update task status
            self.update_task_status("git", task_id, status, response)
        
        # Process Jira tasks
        jira_tasks = self.fetch_pending_tasks("jira")
        for task in jira_tasks:
            task_id = task.get("jira_task_id")
            if not task_id:
                logger.warning(f"Skipping Jira task with missing ID: {task}")
                continue
            title = task.get("title", "")
            description = task.get("description", "")
            
            # Process the Jira task
            response = self.process_jira_task(title, description)
            
            # Analyze the response
            status = self.analyze_response("jira", response)
            
            # Update task status
            self.update_task_status("jira", task_id, status, response)


@celery_app.task(name='app.listeners.git_jira.process_git_jira_tasks')
def process_git_jira_tasks():
    """Celery task to process pending Git and Jira tasks."""
    logger.info("Running Git/Jira task processor task...")
    try:
        processor = TaskProcessor()
        processor.process_all_tasks()
        logger.info("Git/Jira task processing finished.")
    except Exception as e:
        logger.error(f"Unhandled error in process_git_jira_tasks: {e}", exc_info=True)
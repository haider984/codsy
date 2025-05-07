import os
import logging
import requests
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from app.services.git_app import process_query
from app.services.jira_app import process_query_jira
from app.celery_app import celery_app  # Import the Celery app

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TaskProcessor")


class TaskProcessor:
    def __init__(self):
        self.check_interval = 10  # seconds

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
            print(response)          
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
            print(response)
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
        """
        Use a ChatGroq LLM to Analyze the response to determine status
        """
        if not os.getenv("GROQ_API_KEY"):
            logger.error("GROQ_API_KEY environment variable not set. Please configure it in the .env file.")
            return "analyze_error"

        try:
            llm = ChatGroq(model="llama-3.3-70b-versatile",temperature=0.5)
            analysis_prompt = PromptTemplate(
                template="""
                    Analyze the following {task_type} API response and determine if the operation was successful or resulted in an error.
                    
                    Response: {response}
                    
                    Return ONLY one of the following status values:
                    - "completed" if the operation was successful
                    - "failed" if there was an error
                    - "pending" if the status is unclear
                    
                    Status:""",
                input_variables=["task_type", "response"],
            )
                
            formatted_prompt = analysis_prompt.format(
                task_type=task_type,
                response=response_text
            )
            
            response = llm.invoke(formatted_prompt)
            status = response.content.strip().lower()
            
            # Validate the response matches expected values
            valid_statuses = {"completed", "failed", "pending"}
            if status not in valid_statuses:
                logger.warning(f"Unexpected status '{status}' from LLM, defaulting to 'pending'")
                return "pending"
                
            # Map "completed" to "successful" for consistency with existing code
            if status == "completed":
                return "processed"
                
            return status

        except Exception as e:
            logger.error(f"Error analyzing response with LLM: {e}", exc_info=True)
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
            logger.info(f"Updating task {task_id} with status: {status}")

            # Send update request
            update_response = requests.put(endpoint, json=current_task)
            update_response.raise_for_status()

            logger.info(f"Successfully updated {task_type} task {task_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating {task_type} task {task_id}: {e}")
            return False

    def process_all_tasks(self):
        """Process all pending Git and Jira tasks"""
        processed_count = 0
        
        # Process Git tasks
        git_tasks = self.fetch_pending_tasks("git")
        for task in git_tasks:
            task_id = task.get("git_task_id")
            title = task.get("title", "")
            description = task.get("description", "")
            
            # Process the Git task
            response = self.process_git_task(title, description)
            
            # Analyze the response
            status = self.analyze_response("git", response)
            
            # Update task status
            if self.update_task_status("git", task_id, status, response):
                processed_count += 1
        
        # Process Jira tasks
        jira_tasks = self.fetch_pending_tasks("jira")
        for task in jira_tasks:
            task_id = task.get("jira_task_id")
            title = task.get("title", "")
            description = task.get("description", "")
            
            # Process the Jira task
            response = self.process_jira_task(title, description)
            
            # Analyze the response
            status = self.analyze_response("jira", response)
            
            # Update task status
            if self.update_task_status("jira", task_id, status, response):
                processed_count += 1
        
        return processed_count

# Create an instance of the task processor
processor = TaskProcessor()

# Create the Celery task
@celery_app.task(name='app.listeners.git_jira.process_git_jira_tasks')
def process_git_jira_tasks():
    """Celery task that processes all pending Git and Jira tasks"""
    try:
        processed_count = processor.process_all_tasks()
        logger.info(f"Processed {processed_count} tasks")
        return f"Processed {processed_count} Git/Jira tasks"
    except Exception as e:
        logger.error(f"Error in process_git_jira_tasks: {e}")
        return f"Error processing Git/Jira tasks: {e}"

# For direct script execution
def main():
    """Main function when running the script directly"""
    logger.info("Starting Task Processor")
    
    while True:
        try:
            process_git_jira_tasks()
        except Exception as e:
            logger.error(f"Error in main processing loop: {e}")
        
        # Sleep before checking again (for direct script execution only)
        import time
        time.sleep(processor.check_interval)
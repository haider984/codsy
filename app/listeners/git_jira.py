import os
import logging
import requests
import json
import sys
import subprocess
import redis
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from app.services.git_app import process_query
from app.services.jira_app import process_query_jira
from app.celery_app import celery_app  # Import the Celery app
from app.services.agent_user import get_groq_api_key_sync  # Add this import

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TaskProcessor")

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback
BASE_API_URL = os.getenv("BASE_API_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

# Verify GitHub credentials are available - this is critical
if not GITHUB_TOKEN or not GITHUB_USERNAME:
    logger.error("GitHub credentials missing. Set GITHUB_TOKEN and GITHUB_USERNAME in .env file.")
    # Exit early or set a flag to disable GitHub operations
    GITHUB_ENABLED = False
else:
    GITHUB_ENABLED = True
    logger.info(f"GitHub authentication configured for user: {GITHUB_USERNAME}")

# Set GitHub credentials as environment variables so subprocess calls can access them
os.environ["GITHUB_TOKEN"] = GITHUB_TOKEN or ""
os.environ["GITHUB_USERNAME"] = GITHUB_USERNAME or ""

# Set up Git credentials globally for the container
try:
    # Configure Git to store credentials in memory
    subprocess.run(["git", "config", "--global", "credential.helper", "store"], check=True)
    
    # Create .git-credentials file with the token
    home_dir = os.path.expanduser("~")
    with open(f"{home_dir}/.git-credentials", "w") as f:
        f.write(f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com\n")
    
    # Set Git identity for commits
    subprocess.run(["git", "config", "--global", "user.name", GITHUB_USERNAME], check=True)
    subprocess.run(["git", "config", "--global", "user.email", f"{GITHUB_USERNAME}@github.com"], check=True)
    
    logger.info("Git credentials configured successfully")
except Exception as e:
    logger.error(f"Failed to configure Git credentials: {e}")
    GITHUB_ENABLED = False

# Initialize Redis connection for task locking
try:
    redis_client = redis.from_url(REDIS_URL)
    REDIS_AVAILABLE = True
    logger.info("Redis connection established for task locking")
except Exception as e:
    logger.error(f"Failed to connect to Redis: {e}")
    REDIS_AVAILABLE = False


class TaskProcessor:
    def __init__(self):
        self.check_interval = 10  # seconds
        self.repo_paths = {}  # Store repo paths for logging
        self.github_enabled = GITHUB_ENABLED
        self.redis_available = REDIS_AVAILABLE
        self.lock_expire_time = 300  # seconds (5 minutes)

    def acquire_lock(self, task_id, task_type):
        """Try to acquire a lock for the task to prevent race conditions"""
        if not self.redis_available:
            return True  # If Redis not available, proceed without locking
            
        lock_key = f"lock:{task_type}:{task_id}"
        worker_id = os.environ.get("HOSTNAME", "unknown")
        
        # Try to set the lock with NX (only set if not exists)
        locked = redis_client.set(
            lock_key, 
            worker_id, 
            ex=self.lock_expire_time,  # Expiry time in seconds
            nx=True
        )
        
        if locked:
            logger.info(f"Acquired lock for {task_type} task {task_id}")
            return True
        else:
            # Check who has the lock
            owner = redis_client.get(lock_key)
            logger.info(f"Task {task_id} already being processed by {owner}")
            return False
            
    def release_lock(self, task_id, task_type):
        """Release the task lock"""
        if not self.redis_available:
            return
            
        lock_key = f"lock:{task_type}:{task_id}"
        redis_client.delete(lock_key)
        logger.info(f"Released lock for {task_type} task {task_id}")

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
        if not self.github_enabled:
            logger.error("GitHub processing disabled due to missing credentials")
            return json.dumps({
                "status": "error",
                "message": "GitHub processing is disabled - missing authentication credentials"
            })
            
        try:
            # Combine title and description as requested
            combined_input = f"{title}: {description}"
            logger.info(f"Processing GitHub task: {combined_input}")
            
            # Log GitHub credentials status
            logger.info(f"Using GitHub credentials for user: {GITHUB_USERNAME}")
            
            # Call your existing GitHub process function
            response = process_query(combined_input)
            
            # Try to extract repository information from the response
            try:
                if isinstance(response, str):
                    response_json = json.loads(response)
                else:
                    response_json = response
                
                if isinstance(response_json, dict) and 'local_path' in response_json:
                    repo_path = response_json['local_path']
                    abs_path = os.path.abspath(repo_path)
                    logger.info(f"🔵 REPOSITORY PATH: {abs_path}")
                    print(f"\n🔵 CLONED REPOSITORY PATH: {abs_path}\n")
                    self.repo_paths[title] = abs_path
                    
                # Check if the response contains a repo_url
                if isinstance(response_json, dict) and 'repo_url' in response_json:
                    logger.info(f"🔵 REPOSITORY URL: {response_json['repo_url']}")
                    print(f"\n🔵 REPOSITORY URL: {response_json['repo_url']}\n")
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                logger.warning(f"Could not extract repository info: {e}")
                
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
        # Get email from the task if available, default to environment variable
        # In this context we don't have a specific user email, so we'll use a default service account
        service_email = os.getenv("SERVICE_EMAIL", "service@codsy.ai")
        
        # Get API key for this service account
        is_allowed, api_key = get_groq_api_key_sync(service_email, BASE_API_URL)
        
        # If no API key from DB or not allowed, fall back to environment variable
        if not is_allowed or not api_key:
            if not GROQ_API_KEY:
                logger.error("No GROQ API key available. Cannot analyze response.")
                return "pending"  # Default to pending if no key available
            api_key = GROQ_API_KEY
            logger.warning(f"Using fallback GROQ API key for analyzing response.")

        try:
            # Use the obtained API key
            llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.5, api_key=api_key)
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
            
            # Skip task if we can't acquire a lock
            if not self.acquire_lock(task_id, "git"):
                continue
                
            try:
                title = task.get("title", "")
                description = task.get("description", "")
                
                # Process the Git task
                response = self.process_git_task(title, description)
                
                # Analyze the response
                status = self.analyze_response("git", response)
                
                # Update task status
                if self.update_task_status("git", task_id, status, response):
                    processed_count += 1
            finally:
                # Always release the lock when done
                self.release_lock(task_id, "git")
        
        # Process Jira tasks
        jira_tasks = self.fetch_pending_tasks("jira")
        for task in jira_tasks:
            task_id = task.get("jira_task_id")
            
            # Skip task if we can't acquire a lock
            if not self.acquire_lock(task_id, "jira"):
                continue
                
            try:
                title = task.get("title", "")
                description = task.get("description", "")
                
                # Process the Jira task
                response = self.process_jira_task(title, description)
                
                # Analyze the response
                status = self.analyze_response("jira", response)
                
                # Update task status
                if self.update_task_status("jira", task_id, status, response):
                    processed_count += 1
            finally:
                # Always release the lock when done
                self.release_lock(task_id, "jira")
        
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
        time.sleep(processor.check_interval)
import os
import time
import logging
import requests
import json # Import json for potential use
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from ..celery_app import celery_app # Import the Celery app instance

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Use INTERNAL_BASE_API_URL for worker-to-web communication inside Docker
BASE_API_URL = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Use __name__ which is standard practice for module loggers
logger = logging.getLogger(__name__)

# Initialize Groq client - consider initializing inside task if needed
# or ensure thread/process safety if global
try:
    client = Groq(api_key=GROQ_API_KEY)
    logger.info("Groq client initialized successfully at module level.")
except Exception as e:
    logger.error(f"Failed to initialize Groq client at module level: {e}")
    client = None # Set to None to handle potential init failure

class MidMessageProcessor:
    def __init__(self):
        self.check_interval = 10  # seconds

    def fetch_messages_to_process(self):
        """Fetch messages with status 'processed'."""
        try:
            # Use the internal API URL
            url = f"{BASE_API_URL}/api/v1/messages/by_status/?status=processed"
            response = requests.get(url)
            response.raise_for_status()
            messages = response.json()
            logger.info(f"Fetched {len(messages)} messages with 'processed' status.")
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages with status 'processed': {e}")
            return []

    def fetch_git_tasks_for_mid(self, mid):
        """Fetch Git tasks associated with a message ID."""
        try:
            url = f"{BASE_API_URL}/api/v1/gittasks/by_message/{mid}"
            response = requests.get(url)
            response.raise_for_status()
            print(f"Fetched {len(response.json())} git tasks for message ID {mid}")
            return response.json()
        
        except Exception as e:
            logger.error(f"Error fetching git tasks for message ID {mid}: {e}")
            return []

    def fetch_jira_tasks_for_mid(self, mid):
        try:
            url = f"{BASE_API_URL}/api/v1/jiratasks/by_message/{mid}"
            response = requests.get(url)
            response.raise_for_status()
            print(f"Fetched {len(response.json())} jira tasks for message ID {mid}")
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching jira tasks for message ID {mid}: {e}")
            return []

    def wait_for_all_task_replies(self, mid, max_wait=300, check_interval=5):
        """Wait until all related tasks for a message ID have non-empty replies."""
        waited = 0
        while waited < max_wait:
            git_tasks = self.fetch_git_tasks_for_mid(mid)
            jira_tasks = self.fetch_jira_tasks_for_mid(mid)
            all_tasks = git_tasks + jira_tasks

            if all_tasks and all(task.get("reply") for task in all_tasks):
                logger.info(f"All replies ready for message ID {mid}")
                return all_tasks

            logger.info(f"Waiting for all replies... {waited}/{max_wait} seconds elapsed for MID {mid}")
            time.sleep(check_interval)
            waited += check_interval

        logger.warning(f"Timeout reached while waiting for task replies for MID {mid}")
        return None

    def generate_summary_for_message(self, mid, tasks):
        if not tasks:
            return "No tasks were found associated with this message."

        task_details = []
        for task in tasks:
            title = task.get('title', 'Untitled Task')
            reply = task.get('reply', 'No response available')
            task_details.append(f"Title: {title}\nReply: {reply}")

        combined_details = "\n\n".join(task_details)

        prompt = f"""
        You are an assistant generating a final user-facing response. Use ONLY the tasks listed below and their replies to create a well-structured summary.

        Instructions:
        - DO NOT include or repeat the task titles.
        - Summarize the results naturally as if informing the user of completed work.
        - Include all relevant links and names exactly as provided.
        - Use a clear, friendly, and professional tone.
        - Do not add any information not found in the input.
        - start msg from i have complete your task you assign me 
        Tasks and responses for message ID {mid}:
        {combined_details}

        Final response to the user:
        """


        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=1024
            )
            response = completion.choices[0].message.content.strip()
            logger.info(f"Generated summary for message {mid}.")
            logger.debug(f"Summary for MID {mid}: {response}")
            return response
        except Exception as e:
            logger.error(f"Error generating summary with LLM for message {mid}: {e}")
            return "An error occurred while generating the final response summary."

    def update_message_with_reply(self, mid, reply):
        try:
            url = f"{BASE_API_URL}/api/v1/messages/{mid}"
            get_response = requests.get(url)
            get_response.raise_for_status()
            message_data = get_response.json()

            message_data["reply"] = reply
            message_data["status"] = "processed"
            message_data["completion_date"] = datetime.now(timezone.utc).isoformat()

            update_response = requests.put(url, json=message_data)
            update_response.raise_for_status()
            logger.info(f"Successfully updated message {mid} with reply and marked as completed")
            return True
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False

    def process_messages(self):
        messages = self.fetch_messages_to_process()
        if not messages:
            logger.info("No messages to process")
            return

        for message in messages:
            mid = message.get("mid")
            if not mid:
                logger.warning("Found message without MID, skipping")
                continue

            logger.info(f"===== Processing message ID: {mid} =====")

            try:
                # Wait for all task replies to be available
                all_tasks = self.wait_for_all_task_replies(mid)
                if not all_tasks:
                    logger.warning(f"Skipping MID {mid} due to incomplete task replies.")
                    continue

                # Generate the summary reply using LLM
                print(all_tasks)
                reply = self.generate_summary_for_message(mid, all_tasks)

                # Update the message with the final reply
                success = self.update_message_with_reply(mid, reply)
                if success:
                    logger.info(f"Successfully processed message {mid}")
                else:
                    logger.error(f"Failed to update message {mid}")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error processing message {mid}: {e}")

# Define the Celery task
@celery_app.task(name='app.listeners.reply_git_jira.process_messages_for_reply')
def process_messages_for_reply():
    """Celery task to process messages awaiting final reply."""
    logger.info("Running reply_git_jira task...")
    try:
        processor = MidMessageProcessor()
        processor.process_messages()
        logger.info("reply_git_jira task finished.")
    except Exception as e:
        logger.error(f"Unhandled error in process_messages_for_reply task: {e}", exc_info=True)


# Remove the old execution block:
# def run(self): ...
# if __name__ == "__main__": ...

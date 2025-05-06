import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from groq import Groq
from app.celery_app import celery_app  # Import Celery app

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MidMessageProcessor")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)


class MidMessageProcessor:
    def __init__(self):
        self.check_interval = 10  # seconds
        logger.info(f"MidMessageProcessor initialized with API URL: {BASE_API_URL}")

    def fetch_messages_to_process(self):
        try:
            response = requests.get(f"{BASE_API_URL}/api/v1/messages/by_status/?status=processed")
            response.raise_for_status()
            messages = response.json()
            logger.info(f"Fetched {len(messages)} messages with 'processed' status.")
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages to process: {e}")
            return []

    def fetch_git_tasks_for_mid(self, mid):
        try:
            url = f"{BASE_API_URL}/api/v1/gittasks/by_message/{mid}"
            response = requests.get(url)
            response.raise_for_status()
            tasks = response.json()
            logger.warning(f"Fetched {len(tasks)} git tasks for message ID {mid}")
            return tasks
        
        except Exception as e:
            logger.error(f"Error fetching git tasks for message ID {mid}: {e}")
            return []

    def fetch_jira_tasks_for_mid(self, mid):
        try:
            url = f"{BASE_API_URL}/api/v1/jiratasks/by_message/{mid}"
            response = requests.get(url)
            response.raise_for_status()
            tasks = response.json()
            logger.warning(f"Fetched {len(tasks)} jira tasks for message ID {mid}")
            return tasks
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
            logger.info(f"Generated summary for message {mid}: {response[:100]}...")
            return response
        except Exception as e:
            logger.error(f"Error generating summary with LLM for message {mid}: {e}")
            return "An error occurred while generating a response for your message."

    def try_claim_message(self, mid):
        """Attempt to atomically claim a message for processing"""
        try:
            url = f"{BASE_API_URL}/api/v1/messages/{mid}"
            get_response = requests.get(url)
            get_response.raise_for_status()
            message_data = get_response.json()
            
            # Don't process if already claimed or completed
            if message_data.get("status") in ["claiming", "handling", "successful"]:
                logger.info(f"Message {mid} already has status {message_data.get('status')}, skipping")
                return None
                
            # First, mark it as "claiming" to prevent other workers from claiming it
            claim_data = message_data.copy()
            claim_data["status"] = "claiming"
            claim_data["claimed_at"] = datetime.now(timezone.utc).isoformat()
            
            # Try to update the status atomically
            update_response = requests.put(url, json=claim_data)
            update_response.raise_for_status()
            
            # Double check we actually got it
            check_response = requests.get(url)
            check_response.raise_for_status()
            current_status = check_response.json().get("status")
            
            if current_status == "claiming":
                logger.info(f"Successfully claimed message {mid} for processing")
                return message_data
            else:
                logger.warning(f"Failed to claim message {mid}, current status: {current_status}")
                return None
                
        except Exception as e:
            logger.error(f"Error claiming message {mid}: {e}")
            return None

    def update_message_with_reply(self, mid, reply, original_data):
        try:
            url = f"{BASE_API_URL}/api/v1/messages/{mid}"
            
            # Before updating, verify current status matches what we expect
            get_response = requests.get(url)
            get_response.raise_for_status()
            current_data = get_response.json()
            
            # If someone else modified the message while we were processing, don't update
            if current_data.get("status") != "claiming":
                logger.warning(f"Message {mid} status changed from claiming to {current_data.get('status')}, aborting update")
                return False
            
            # Create update with original data to prevent overwriting other fields
            message_data = original_data.copy()
            message_data["reply"] = reply
            message_data["status"] = "processed"  # Keep as "processed" for reply.py to handle
            message_data["completion_date"] = datetime.now(timezone.utc).isoformat()

            update_response = requests.put(url, json=message_data)
            update_response.raise_for_status()
            logger.info(f"Successfully updated message {mid} with reply and marked as processed")
            return True
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False

    def process_messages(self):
        messages = self.fetch_messages_to_process()
        processed_count = 0
        
        if not messages:
            logger.info("No messages to process")
            return f"Processed {processed_count} messages"

        for message in messages:
            mid = message.get("mid")
            if not mid:
                logger.warning("Found message without MID, skipping")
                continue
            
            # Skip messages that already have replies
            if message.get("reply"):
                logger.info(f"Message {mid} already has a reply, skipping")
                continue

            logger.info(f"===== Processing message ID: {mid} =====")

            try:
                # Check if there are any Git or Jira tasks for this message
                git_tasks = self.fetch_git_tasks_for_mid(mid)
                jira_tasks = self.fetch_jira_tasks_for_mid(mid)
                
                # If no tasks found, skip this message
                if not git_tasks and not jira_tasks:
                    logger.info(f"No Git/Jira tasks found for message {mid}, skipping")
                    continue
                
                # Try to claim this message for processing
                claimed_message = self.try_claim_message(mid)
                if not claimed_message:
                    logger.info(f"Could not claim message {mid}, skipping")
                    continue
                    
                # Wait for all task replies to be available
                all_tasks = self.wait_for_all_task_replies(mid)
                if not all_tasks:
                    logger.warning(f"Skipping MID {mid} due to incomplete task replies.")
                    continue

                # Generate the summary reply using LLM
                reply = self.generate_summary_for_message(mid, all_tasks)

                # Update the message with the final reply
                success = self.update_message_with_reply(mid, reply, claimed_message)
                if success:
                    logger.info(f"Successfully processed message {mid}")
                    processed_count += 1
                else:
                    logger.error(f"Failed to update message {mid}")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error processing message {mid}: {e}")

        return f"Processed {processed_count} messages"

    def run(self):
        logger.info("Starting MidMessageProcessor...")
        while True:
            try:
                self.process_messages()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in main processing loop: {e}")
                time.sleep(self.check_interval)


# Create a Celery task to process Git and Jira task replies
@celery_app.task(name='app.listeners.reply_git_jira.process_messages_for_reply')
def process_messages_for_reply():
    """Celery task to process messages and generate replies from Git/Jira task results"""
    processor = MidMessageProcessor()
    return processor.process_messages()
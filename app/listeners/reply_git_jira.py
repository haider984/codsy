import os
import time
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from app.celery_app import celery_app  # Import the Celery app
from app.services.agent_user import get_groq_api_key_sync  # Add this import

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback
BASE_API_URL = os.getenv("BASE_API_URL")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MidMessageProcessor")

# Initialize Groq client will be done when needed instead of globally

class MidMessageProcessor:
    def __init__(self):
        self.check_interval = 10  # seconds
        self.groq_clients = {}  # Store client instances by email

    def get_groq_client(self, email="service@codsy.ai"):
        """Get a Groq client for the specified email, with fallback to environment variable"""
        if email in self.groq_clients:
            return self.groq_clients[email]
            
        # Try to get API key from database
        is_allowed, api_key = get_groq_api_key_sync(email, BASE_API_URL)
        
        # Fall back to environment variable if needed
        if not is_allowed or not api_key:
            if GROQ_API_KEY:
                api_key = GROQ_API_KEY
                logger.warning(f"Using fallback GROQ API key for {email}")
            else:
                logger.error(f"No GROQ API key available for {email}")
                return None
                
        # Create and cache client
        try:
            client = Groq(api_key=api_key)
            self.groq_clients[email] = client
            return client
        except Exception as e:
            logger.error(f"Error creating Groq client: {e}")
            return None

    def fetch_messages_to_process(self):
        try:
            response = requests.get(f"{BASE_API_URL}/api/v1/messages/by_status/?status=processed")
            response.raise_for_status()
            messages = response.json()
            
            # Filter out messages that already have replies to avoid reprocessing
            messages_without_replies = [msg for msg in messages if not msg.get("reply")]
            
            logger.info(f"Fetched {len(messages)} messages with 'processed' status, {len(messages_without_replies)} need replies.")
            return messages_without_replies
        except Exception as e:
            logger.error(f"Error fetching messages to process: {e}")
            return []

    def fetch_git_tasks_for_mid(self, mid):
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
                
                # Update task statuses directly here instead of calling update_task_status
                for task in git_tasks:
                    try:
                        task_id = task.get("git_task_id")
                        url = f"{BASE_API_URL}/api/v1/gittasks/{task_id}"
                        
                        # Get current task data
                        get_response = requests.get(url)
                        get_response.raise_for_status()
                        task_data = get_response.json()
                        
                        # Update status
                        task_data["status"] = "successful"
                        
                        # Update task
                        update_response = requests.put(url, json=task_data)
                        update_response.raise_for_status()
                        logger.info(f"Successfully updated git task {task_id} to successful")
                    except Exception as e:
                        logger.error(f"Error updating git task {task_id}: {e}")
                
                for task in jira_tasks:
                    try:
                        task_id = task.get("jira_task_id")
                        url = f"{BASE_API_URL}/api/v1/jiratasks/{task_id}"
                        
                        # Get current task data
                        get_response = requests.get(url)
                        get_response.raise_for_status()
                        task_data = get_response.json()
                        
                        # Update status
                        task_data["status"] = "successful"
                        
                        # Update task
                        update_response = requests.put(url, json=task_data)
                        update_response.raise_for_status()
                        logger.info(f"Successfully updated jira task {task_id} to successful")
                    except Exception as e:
                        logger.error(f"Error updating jira task {task_id}: {e}")
                
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
            # Get client (for service account or from task owner if available)
            task_owner = tasks[0].get('owner_email', 'service@codsy.ai') if tasks else 'service@codsy.ai'
            client = self.get_groq_client(task_owner)
            
            if not client:
                return "I couldn't generate a summary due to API configuration issues."
                
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

    def update_message_with_reply(self, mid, reply):
        try:
            url = f"{BASE_API_URL}/api/v1/messages/{mid}"
            get_response = requests.get(url)
            get_response.raise_for_status()
            message_data = get_response.json()

            # # Check if the status is already "successful" and preserve it
            # if message_data.get("status") != "successful":
            #     message_data["status"] = "successful"
            
            message_data["reply"] = reply
            message_data["completion_date"] = datetime.now(timezone.utc).isoformat()

            update_response = requests.put(url, json=message_data)
            update_response.raise_for_status()
            logger.info(f"Message {mid} updated with reply")
            return True
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False

    # def update_task_status(self, task, platform):
    #     try:
    #         task_id = task.get("id")
    #         if platform == "git":
    #             url = f"{BASE_API_URL}/api/v1/gittasks/{task_id}"
    #         else:  # platform == "jira"
    #             url = f"{BASE_API_URL}/api/v1/jiratasks/{task_id}"

    #         print("task_id",task_id)
                
    #         # Get current task data
    #         get_response = requests.get(url)
    #         get_response.raise_for_status()
    #         task_data = get_response.json()
            
    #         # Update status
    #         task_data["status"] = "successful"
            
    #         # Update task
    #         update_response = requests.put(url, json=task_data)
    #         update_response.raise_for_status()
    #         logger.info(f"Successfully updated {platform} task {task_id} to successful")
    #         return True
    #     except Exception as e:
    #         logger.error(f"Error updating {platform} task {task_id}: {e}")
    #         return False

    def process_messages(self):
        messages = self.fetch_messages_to_process()
        processed_count = 0
        
        if not messages:
            logger.info("No messages to process")
            return processed_count

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
                if reply is None:
                    reply = "Sorry, I can't help with that right now — but I'm happy to answer another question!"
                logger.info(f"Generated reply for message {mid}: {reply[:100]}...")

                # Update the message with the final reply
                success = self.update_message_with_reply(mid, reply)
                if success:
                    logger.info(f"Successfully processed message {mid}")
                    processed_count += 1
                else:
                    logger.error(f"Failed to update message {mid}")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error processing message {mid}: {e}")
                
        return processed_count

    def run(self):
        logger.info("Starting MidMessageProcessor...")
        while True:
            try:
                self.process_messages()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in main processing loop: {e}")
                time.sleep(self.check_interval)


# Create an instance of the processor
processor = MidMessageProcessor()

# Create the Celery task
@celery_app.task(name='app.listeners.reply_git_jira.process_messages_for_reply')
def process_messages_for_reply():
    """Celery task to process messages and generate replies from Git/Jira tasks"""
    try:
        processed_count = processor.process_messages()
        logger.info(f"Processed {processed_count} messages")
        return f"Processed {processed_count} messages for reply generation"
    except Exception as e:
        logger.error(f"Error in process_messages_for_reply task: {e}")
        return f"Error processing messages for reply: {e}"
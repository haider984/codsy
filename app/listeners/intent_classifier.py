import os
import logging
import requests
from app.services.generic_bot import GenericMessageHandler
from app.services.task_analyzer import process_message_for_tasks
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from openai import OpenAI
from datetime import datetime, timezone
from app.celery_app import celery_app  # Import the Celery app

generic_handler = GenericMessageHandler()

# --- CONFIGURATION ---
load_dotenv()
BASE_API_URL = os.getenv("BASE_API_URL")
openai_api_key = os.getenv("INTENT_OPENAI_API_KEY")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))  # seconds
MAX_RETRIES = 3  # Maximum number of retries for failed operations

# --- LOGGER SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- OPENAI CLIENT SETUP ---
openai_client = OpenAI(api_key=openai_api_key)

# --- PROMPT TEMPLATES ---
classification_prompt = PromptTemplate(
    template="""
    You are an AI email classification assistant. Classify the email content (HTML stripped) into EXACTLY ONE of the following categories:
    "meeting" — Any content primarily focused on organizing or referencing a meeting:
        - Meeting invitations with date/time details
        - Messages containing video conferencing links (Zoom, Teams, Google Meet, etc.)
        - Discussions about scheduling or rescheduling meetings
        - References to upcoming meetings with clear intent to organize attendance
    "transcript" — Content that captures actual conversation dialogue, especially about GitHub or Jira:
        MUST have a dialogue format with named speakers followed by their statements
        Often contains back-and-forth exchanges between multiple participants
        May include technical discussions about GitHub repositories or Jira tickets
        Can include meeting summaries that explicitly reference spoken exchanges
        Dialogue Examples:
            John: "Hi, Guyz, How are you?"
            Sarah: "I am good, thanks."
            Mike: "I am great. What about you?"
            John: "I am good as well."
            John: "ok guyz, We need to streamline GitHub and Jira workflows."
            Sarah: "I'll create the repo and share it."
            Mike: "Let's use the automation script John built."
        Summary Example: "The meeting covered GitHub repo setup and automation testing with a custom script."
    "instructions" — Clear action items or task directives related to GitHub or Jira:
        Direct commands or requests to perform specific technical actions
        NOT in a transcript/dialogue format
        Focus on the tasks themselves rather than discussions about the tasks
        GitHub Examples:
            "Please create a new GitHub repository for XYZ project"
            "Update index.html in the Dev repository"
            "Add dashboard component to the main branch"
            "List git repos"
        Jira Examples:
            "Create a new Jira board for the XYZ project"
            "Add a ticket for the dashboard implementation"
            "Update the story points on DEV-123"
            "List Jira projects"
        Combined Tasks:
            "Setup GitHub repo for XYZ and create matching Jira board"
            "After merging PR, update the Jira ticket status"
    "greeting" — Any content that doesn't clearly fit into the above categories:
        Simple greetings without technical instructions ("Hi", "Hello", "Good morning")
        General questions about wellbeing ("How are you?", "What's going on?")
        Casual conversations without specific tasks or meeting details
        Brief acknowledgments or thank you messages
        Any content that lacks the specific characteristics of the other three categories
    CLASSIFICATION DECISION PROCESS:
        First, determine if the content explicitly mentions scheduling a meeting or contains meeting links → "meeting"
        If not, check if it follows a dialogue format with named speakers or directly summarizes a conversation → "transcript"
        If not, check if it contains specific GitHub/Jira tasks or technical instructions → "instructions"
        If none of the above criteria are met → "greeting"
    IMPORTANT RULES:
        Always select EXACTLY ONE category that best represents the primary purpose of the message
        For mixed content, prioritize based on the main intent (e.g., a message with both a greeting and GitHub instructions should be classified as "instructions")
        Context matters - look at the overall structure and intent of the message
        The presence of named speakers with quotations strongly indicates "transcript"
        Simple mentions of GitHub/Jira without specific tasks do not qualify as "instructions"
        When in doubt between "greeting" and another category, choose the more specific category


    Email content:
{body}

Return exactly one word from the list above. If uncertain, choose "greeting".
""",
    input_variables=["body"]
)

# --- HELPER FUNCTIONS ---
def get_unprocessed_messages():
    """Fetch all unprocessed messages from the API using the correct endpoint"""
    try:
        url = f"{BASE_API_URL}/api/v1/messages/by_processed_status/?processed_status=false"
        logger.info(f"Fetching: {url}")
        response = requests.get(url)
        response.raise_for_status()
        messages = response.json()
        logger.info(f"Fetched {len(messages)} unprocessed messages")
        return messages
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return []

def get_message_by_id(mid):
    """Fetch a specific message by ID"""
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/messages/{mid}")
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch message {mid}: {response.status_code} {response.text}")
            # If not found, we'll return the original message as is
            return None
    except Exception as e:
        logger.error(f"Error fetching message {mid}: {e}")
        return None

def update_message_type(mid, message_type, original_message):
    """Update the message type and mark as processed"""
    try:
        # Build payload from existing message and add classification fields
        payload = {
            "sid": original_message["sid"],
            "uid": original_message["uid"],
            "pid": original_message["pid"],
            "username": original_message["username"],
            "content": original_message["content"],
            "message_datetime": original_message.get("message_datetime", datetime.now(timezone.utc).isoformat()),
            "source": original_message["source"],
            "msg_id": original_message.get("msg_id", ""),
            "channel": original_message.get("channel", ""),
            "thread_ts": original_message.get("thread_ts", ""),
            "message_type": message_type,
            "processed": True,
            "status": "processed"
        }

        logger.info(f"Updating message {mid} with payload: {payload}")
        response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)

        if response.status_code == 200:
            logger.info(f"Successfully updated message {mid}")
            return True
        else:
            logger.error(f"Failed to update message {mid}: {response.status_code} {response.text}")
            return False
    except Exception as e:
        logger.error(f"Exception while updating message {mid}: {e}")
        return False


def classify_message_content(content):
    """Use OpenAI LLM to classify message content"""
    try:
        prompt = classification_prompt.format(body=content)
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        classification = response.choices[0].message.content.strip().lower()
        logger.debug(f"[Classifier Task] OpenAI raw response: '{classification}'")
        
        # Check if the response contains any of our categories
        valid_types = ["meeting", "transcript", "instructions", "greeting"]
        
        # Find if any valid type is in the response
        found_type = None
        for valid_type in valid_types:
            if valid_type in classification:
                found_type = valid_type
                break
        
        # If a valid type was found in the response, use it
        if found_type:
            logger.info(f"Found classification: {found_type} in response: {classification}")
            return found_type
        
        # If no valid type was found, default to greeting
        logger.warning(f"No valid classification found in response: '{classification}', defaulting to 'greeting'")
        return "greeting"
    except Exception as e:
        logger.error(f"Error classifying message: {e}")
        return "greeting"  # Default to greeting on error

def route_message(message, message_type):
    """Route the message to the appropriate handler"""
    try:
        # Get the message ID
        mid = message.get("mid")
        
        if not mid:
            logger.error("Message has no mid field, cannot route")
            return False
            
        # Different handling based on message type
        if message_type == "meeting":
            logger.info(f"Routing meeting message {mid} to meeting handler")
            # Call meeting handler here
            # meeting_handler.process(message)
            return True
            
        elif message_type == "transcript":
            logger.info(f"Routing transcript message {mid} to transcript handler")
            # Call transcript handler here
            process_message_for_tasks(mid)
            return True
            
        elif message_type == "instructions":
            logger.info(f"Routing instructions message {mid} to instructions handler")
            # Call instructions handler here
            process_message_for_tasks(mid)
            return True
            
        elif message_type == "greeting":
            logger.info(f"Routing greeting message {mid} to greeting handler")
            # Call greeting handler here
            return generic_handler.process_message(message,message_type)
            
        else:
            logger.warning(f"Unknown message type {message_type} for message {mid}")
            return False
    except Exception as e:
        logger.error(f"Error routing message: {e}")
        return False

# --- CELERY TASK FUNCTION ---
@celery_app.task(name='app.listeners.intent_classifier.process_unprocessed_messages_task')
def process_unprocessed_messages_task():
    """Celery task to process unprocessed messages"""
    logger.info("Checking for unprocessed messages...")
    
    # Get all unprocessed messages
    messages = get_unprocessed_messages()
    logger.info(f"Found {len(messages)} unprocessed messages")
    
    processed_count = 0
    for msg in messages:
        try:
            mid = msg.get("mid")
            
            if not mid:
                logger.warning("Message has no ID, skipping")
                continue
                
            # Use the message object we already have
            message = msg
            
            # Log the message structure for debugging
            logger.info(f"Processing message with mid: {mid}")
            
            # Extract content from the message
            content = message.get("content", "")
            
            if not content:
                logger.warning(f"Message {mid} has no content, skipping")
                update_message_type(mid, "greeting", message)  # Mark as processed with default type
                continue
                
            # Classify the message
            message_type = classify_message_content(content)
            logger.info(f"Classified message {mid} as: {message_type}")
            
            # Update the message with its type
            if update_message_type(mid, message_type, message):
                # Route to appropriate handler
                route_message(message, message_type)
                processed_count += 1
            else:
                logger.error(f"Failed to update message {mid}, not routing")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    return f"Processed {processed_count} out of {len(messages)} messages"

# --- MAIN FUNCTION FOR DIRECT EXECUTION ---
def main():
    """Main loop to periodically check for and process messages"""
    logger.info("Starting Intent Classifier service...")
    
    while True:
        try:
            process_unprocessed_messages_task()
        except Exception as e:
            logger.error(f"Error in main processing loop: {e}")
            
        # Sleep for the configured interval
        logger.info(f"Sleeping for {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)
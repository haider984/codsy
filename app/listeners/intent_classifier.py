import os
import logging
import requests
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
import groq
from datetime import datetime, timezone
import json # Ensure json is imported

# Import Celery app instance
from ..celery_app import celery_app

# --- CORRECTED IMPORTS ---
# Use '..' to go up from 'listeners' to 'app', then into 'services'
from ..services.generic_bot import GenericMessageHandler
from ..services.task_analyzer import process_message_for_tasks
# --- END CORRECTED IMPORTS ---

# (Optional but recommended) Basic import check
try:
    assert GenericMessageHandler is not None
    assert process_message_for_tasks is not None
    # Initialize logger after basic imports succeed to ensure logging works if imports fail later
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s")
    logger = logging.getLogger(__name__)
    logger.info("Successfully imported handlers from app.services")
except (ImportError, AssertionError, NameError) as e:
    # Log critical error if imports fail
    logging.basicConfig(level=logging.CRITICAL, format="%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s")
    logging.critical(f"CRITICAL ERROR: Failed to import required services: {e}", exc_info=True)
    # Re-raise the exception to prevent the application from continuing in a broken state
    raise ImportError(f"Could not import required services from app.services: {e}") from e

# Instantiate handler only after successful import check
generic_handler = GenericMessageHandler()

# --- CONFIGURATION ---
load_dotenv()
# BASE_API_URL is needed by the *worker* executing the task
INTERNAL_BASE_API_URL = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000") # Use internal URL
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# CHECK_INTERVAL is no longer needed here, scheduling is handled by Celery Beat

# --- GROQ CLIENT SETUP ---
groq_client = None
if GROQ_API_KEY:
    try:
        groq_client = groq.Client(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized in intent_classifier.")
    except Exception as e:
         logger.error(f"Failed to initialize Groq client in intent_classifier: {e}")
else:
    logger.warning("GROQ_API_KEY missing in intent_classifier, classification may fail.")

# --- PROMPT TEMPLATES ---
classification_prompt = PromptTemplate(
    template="""
You are an AI email classification assistant.
Classify the **email content** (HTML stripped) into exactly one of the following categories:

  "meeting"     — a meeting invitation or link
**"transcript"** — A transcript of a meeting or call, discussing GitHub or Jira tasks. Typically includes spoken dialogue or summaries.
   - *Dialogue Example*:
     - John: "We need to streamline GitHub and Jira workflows."
     - Sarah: "I'll create the repo and share it."
     - Mike: "Let's use the automation script John built."
   - *Summary Example*: "The meeting covered GitHub repo setup and automation testing with a custom script."

**"instructions"** — Clear action items or steps related to GitHub or Jira, without being a transcript.
   - *Example*: "Please create a new GitHub repo for XYZ and update the Jira board with the new ticket. or now update index.html in repo Dev to he dashboard should be a single HTML file"

  "greeting"    — everything else (e.g. casual messages, greetings, or anything that doesn't clearly fit above)

Email content:
{body}

Return exactly one word from the list above. If uncertain, choose "greeting".
""",
    input_variables=["body"]
)

# --- HELPER FUNCTIONS (Now called within the Celery task) ---
def get_unprocessed_messages():
    """Fetch all unprocessed messages from the API using the correct internal endpoint"""
    try:
        # Use INTERNAL_BASE_API_URL set for the worker environment
        url = f"{INTERNAL_BASE_API_URL}/api/v1/messages/by_processed_status/?processed_status=false"
        logger.debug(f"[Classifier Task] Fetching: {url}")
        response = requests.get(url)
        response.raise_for_status()
        messages = response.json()
        logger.info(f"[Classifier Task] Fetched {len(messages)} unprocessed messages")
        return messages
    except requests.exceptions.RequestException as e:
        logger.error(f"[Classifier Task] Fetch error contacting {INTERNAL_BASE_API_URL}: {e}")
        return []
    except Exception as e:
        logger.error(f"[Classifier Task] Generic fetch error: {e}")
        return []


def update_message_type(mid, message_type, original_message):
    """Update the message type and mark as processed"""
    try:
        # Use INTERNAL_BASE_API_URL
        api_endpoint = f"{INTERNAL_BASE_API_URL}/api/v1/messages/{mid}"
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

        # Remove keys with None values if the API expects them omitted
        payload = {k: v for k, v in payload.items() if v is not None}

        logger.debug(f"[Classifier Task] Updating message {mid} via PUT {api_endpoint} with payload: {payload}")
        response = requests.put(api_endpoint, json=payload)

        if response.status_code == 200:
            logger.info(f"[Classifier Task] Successfully updated message {mid} with type {message_type}")
            return True
        else:
            logger.error(f"[Classifier Task] Failed to update message {mid}: {response.status_code} {response.text}. Payload: {json.dumps(payload)}")
            return False
    except Exception as e:
        logger.error(f"[Classifier Task] Exception while updating message {mid}: {e}", exc_info=True)
        return False


def classify_message_content(content):
    """Use Groq LLM to classify message content"""
    if not groq_client:
        logger.error("[Classifier Task] Groq client not initialized (missing GROQ_API_KEY?)")
        return "greeting" # Default if client isn't available

    try:
        prompt = classification_prompt.format(body=content)
        logger.debug(f"[Classifier Task] Sending classification request to Groq")
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192", # Using updated model name if necessary
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=20
        )
        classification = response.choices[0].message.content.strip().lower()
        logger.debug(f"[Classifier Task] Groq raw response: '{classification}'")

        valid_types = ["meeting", "transcript", "instructions", "greeting"]
        found_type = next((vt for vt in valid_types if vt in classification.split()), "greeting")

        logger.info(f"[Classifier Task] Classified content as: {found_type}")
        return found_type
    except Exception as e:
        logger.error(f"[Classifier Task] Error during Groq classification: {e}", exc_info=True)
        return "greeting"


def route_message(message, message_type):
    """Route the message to the appropriate handler"""
    mid = message.get("mid")
    if not mid:
        logger.error("[Classifier Task] Message missing 'mid', cannot route.")
        return False

    try:
        logger.info(f"[Classifier Task] Routing message {mid} (type: {message_type})...")
        if message_type == "meeting":
            # Add call to meeting handler if exists
            logger.info(f"-> Meeting handler for {mid} (Not Implemented)")
            return True
        elif message_type in ["transcript", "instructions"]:
             logger.info(f"-> Task Analyzer for {mid}")
             process_message_for_tasks(mid) # Call imported function
             return True
        elif message_type == "greeting":
             logger.info(f"-> Generic Handler for {mid}")
             return generic_handler.process_message(message, message_type) # Use imported handler instance
        else:
            logger.warning(f"[Classifier Task] Unknown message type '{message_type}' for mid {mid}, cannot route.")
            return False
    except Exception as e:
        logger.error(f"[Classifier Task] Error routing message {mid}: {e}", exc_info=True)
        return False


# --- CELERY TASK DEFINITION ---

@celery_app.task(name="app.listeners.intent_classifier.process_unprocessed_messages_task")
def process_unprocessed_messages_task():
    """
    Celery task to fetch unprocessed messages, classify them,
    update their status/type, and route them.
    """
    task_logger = logging.getLogger(__name__ + ".task") # Specific logger for the task run
    task_logger.info("Starting message classification task run...")

    messages = get_unprocessed_messages()
    if not messages:
        task_logger.info("No unprocessed messages found this run.")
        return

    processed_count = 0
    failed_update_count = 0
    routing_failed_count = 0
    error_count = 0

    for msg in messages:
        mid = msg.get("mid")
        if not mid:
            task_logger.warning("Skipping message without 'mid'.")
            continue

        try:
            content = msg.get("content", "")
            if not content:
                task_logger.warning(f"Message {mid} has no content. Marking as 'greeting' and processed.")
                # Update with default type if content is missing but record exists
                if update_message_type(mid, "greeting", msg):
                    processed_count +=1 # Count as processed (even if defaulted)
                else:
                    failed_update_count += 1
                continue

            # Classify
            message_type = classify_message_content(content)
            task_logger.info(f"Message {mid} classified as: {message_type}")

            # Update and Route
            if update_message_type(mid, message_type, msg):
                if route_message(msg, message_type):
                    processed_count += 1
                else:
                    routing_failed_count += 1
                    task_logger.warning(f"Routing failed for message {mid} (type: {message_type}). Check handler logic.")
            else:
                # Update failed, log error, message remains unprocessed for next run
                failed_update_count += 1
                task_logger.error(f"Failed to update message {mid} after classification. It will be retried.")

        except Exception as e:
            error_count += 1
            task_logger.error(f"Unhandled error processing message {mid}: {e}", exc_info=True)
            # Decide if you want to attempt to mark as errored/processed here

    task_logger.info(f"Finished message classification task run. Processed: {processed_count}, Update Fails: {failed_update_count}, Routing Fails: {routing_failed_count}, Errors: {error_count}")


# --- REMOVE MAIN EXECUTION LOOP ---
# The 'while True' loop and 'if __name__ == "__main__":' are removed.
# Celery Beat will schedule the execution of 'process_unprocessed_messages_task'.
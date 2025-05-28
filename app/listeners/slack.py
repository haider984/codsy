import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_sdk import WebClient
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from datetime import datetime, timezone, timedelta
from app.celery_app import celery_app
from groq import Groq
import json
import asyncio
from ..services.follow_up import analyze_and_enhance_question

# ——— CONFIGURATION ———
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback

# ——— LOGGER + SLACK INIT ———
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)

client = WebClient(token=SLACK_BOT_TOKEN)
# Don't initialize Groq client globally - we'll create per-user instances

# ─── PERMISSION CHECK HELPER ───────────────────────────────────────────────────
def check_user_permission(email: str, base_api_url: str) -> bool:
    """Checks if a user is allowed by querying the agent_users status endpoint."""
    if not email or email == "Unknown" or "@" not in email: # Basic email validity check
        logger.warning(f"Permission check: No valid email provided ('{email}'). Denying permission.")
        return False
    if not base_api_url: # Check if BASE_API_URL is configured
        logger.error("Permission check: BASE_API_URL not configured. Denying permission.")
        return False
    try:
        response = requests.get(f"{base_api_url}/api/v1/agent_users/status/email/{email}", timeout=10)
        if response.status_code == 200:
            status = response.json()
            if status == "allowed":
                logger.info(f"Permission check for {email}: ALLOWED")
                return True
            else:
                logger.info(f"Permission check for {email}: NOT ALLOWED (status: {status})")

                return False
        elif response.status_code == 404:
            logger.warning(f"Permission check for {email}: User not found (404). Denying permission.")
            return False
        else:
            logger.error(f"Permission check for {email}: Error checking status ({response.status_code} {response.text}). Denying permission.")
            return False
    except requests.Timeout:
        logger.error(f"Permission check for {email}: Request timed out. Denying permission.")
        return False
    except requests.RequestException as e:
        logger.error(f"Permission check for {email}: Request failed ({e}). Denying permission.")
        return False
    except ValueError as e: # Handles JSON decoding errors
        logger.error(f"Permission check for {email}: Failed to decode JSON response ({e}). Denying permission.")
        return False
def get_groq_api_key(sender_email):
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/agent_users/groq/{sender_email}", timeout=10)

        if response.status_code == 200:
            data = response.json()
            api_key = data.get("id")
            if api_key:
                return api_key
            else:
                logger.error(f"No API key found in response for {sender_email}")
                return None
        else:
            logger.error(f"Failed to get API key for {sender_email}, status code: {response.status_code}")
            return None

    except Exception as e:
        logger.exception(f"Exception occurred while fetching Groq API key for {sender_email}: {e}")
        return None

class ContextAwareSlackHandler:
    def __init__(self):
        self.history_window = timedelta(hours=48)  # Look back 48 hours for context
        self.groq_clients = {}  # Cache of Groq clients by user email

    def get_groq_client(self, email: str):
        """
        Get a Groq client for the specified user email.
        Uses cached client if available, otherwise creates a new one.
        Falls back to environment variable if user key not available.
        """
        # Return cached client if available
        if email in self.groq_clients:
            return self.groq_clients[email]
            
        # Get API key for this user
        api_key = get_groq_api_key(email)
        
        # If user is not allowed or no key available, fall back to environment variable
        if not api_key:
            if GROQ_API_KEY:
                api_key = GROQ_API_KEY
                logger.warning(f"Using fallback GROQ API key for {email}")
            else:
                logger.error(f"No GROQ API key available for {email} and no fallback configured")
                return None
                
        # Create and cache the client
        try:
            client = Groq(api_key=api_key)
            self.groq_clients[email] = client
            return client
        except Exception as e:
            logger.error(f"Failed to create Groq client for {email}: {e}")
            return None


    def update_message_with_reply(self, mid, message):
        """
        Update a message in the database with the generated reply and any context enhancements
        """
        try:
            # Include any enhanced content flags and extracted information
            context_metadata = {}
            if message.get("context_enhanced", False):
                context_metadata = {
                    "original_content": message.get("original_content", ""),
                    "context_enhanced": True,
                    "context_quality": message.get("context_quality", 0.0)
                }
            
            # Add extracted information to metadata
            if message.get("extracted_info"):
                if not context_metadata:
                    context_metadata = {}
                context_metadata["extracted_info"] = message.get("extracted_info")
            
            payload = {
                "content": message.get("content", ""),
                "reply": message.get("reply", ""),
                "message_type": message.get("message_type", "user_message"),
                "processed": False,
                "status": "pending",
                "username": message.get("username", ""),
                "message_datetime": message.get("message_datetime", datetime.now(timezone.utc).isoformat()),
                "sid": message.get("sid", ""),
                "uid": message.get("uid", ""),
                "pid": message.get("pid", ""),
                "source": message.get("source", "slack"),
                "msg_id": message.get("msg_id", ""),
                "channel": message.get("channel", "slack"),
                "channel_id": message.get("channel_id", ""),
                "thread_ts": message.get("thread_ts", ""),
                "metadata": context_metadata if context_metadata else message.get("metadata", {})
            }

            response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)
            if response.status_code == 200:
                logger.info(f"Updated message {mid} with reply and context data")
                return True
            else:
                logger.error(f"Update failed: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False
            
    def process_new_message(self, message):
        """
        Process a new message with context awareness:
        1. Analyze if message needs context
        2. Enhance message with context if needed
        3. Generate a response using the enhanced message
        4. Update the database with the enhanced message and reply
        """
        mid = message.get("mid")
        if not mid:
            logger.warning("Message missing 'mid', skipping")
            return False
            
        channel_id = message.get("channel_id")
        username = message.get("username")
        
        success = self.update_message_with_reply(mid, message)
        
        return success

# Create a global instance of the handler
slack_handler = ContextAwareSlackHandler()

def create_message_in_db(username, text, msg_ts, channel_id,uid):
    """
    Create a new message in the database.
    The user_email_for_context is not directly saved but used for context if needed by process_new_message.
    """
    sid = "680f69cc5c250a63d068bbec"  # Static for now
    pid = "60c72b2f9b1e8a3f4c8a1b2c"

    payload = {
        "sid": sid,
        "uid": uid,
        "pid": pid,
        "username": username,
        "content": text,
        "reply": "",
        "message_datetime": datetime.utcnow().isoformat() + "Z",
        "source": "slack",
        "msg_id": "",
        "channel": "slack",
        "channel_id": channel_id,
        "thread_ts": msg_ts,
        "message_type": "user_message",
        "processed": False,
        "status": "pending"
    }

    try:
        resp = requests.post(f"{BASE_API_URL}/api/v1/messages/", json=payload)
        if resp.status_code in (200, 201):
            logger.info(f"Message saved to DB: {msg_ts}")
            # Get the message ID from the response
            message_id = resp.json().get("mid") if resp.headers.get("content-type") == "application/json" else resp.text
            
            # Create the message object with the returned ID
            message = payload.copy()
            message["mid"] = message_id
            
            # Process the message with context awareness
            slack_handler.process_new_message(message)
            return message_id
        else:
            logger.error(f"Failed to save message {msg_ts}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Error posting message to DB: {e}")
        return None

@app.event("message")
def handle_message_events(event, say):
    user_id = event.get("user") # Renamed from 'user' to 'user_id' for clarity
    text = event.get("text", "").strip()
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel_id = event.get("channel")
    ts = event.get("ts")
    uid=""
    if subtype or not user_id or not text:
        return

    if channel_type in ("im", "mpim"):  # Direct Message
        try:
            user_info_response = app.client.users_info(user=user_id)
            user_profile = user_info_response["user"]["profile"]
            username = user_profile.get("real_name") or user_profile.get("display_name") or user_id
            email = user_profile.get("email")

            if not email:
                logger.warning(f"Could not retrieve email for user {username} ({user_id}). Cannot check permissions.")
                say("I couldn't verify your permissions because your email is not available. Please check your Slack profile.")
                return

            logger.info(f"DM from {username} ({email}): {text}")

            # === PERMISSION CHECK ===
            if not check_user_permission(email, BASE_API_URL):
                logger.warning(f"User {username} ({email}) is not allowed for DM interaction.")

                say("Sorry, you are not authorized to use this feature.")
                return
            
            if email:
                try:
                    response = requests.get(f"{BASE_API_URL}/api/v1/agent_users/{email}", timeout=10)

                    if response.status_code == 200:
                        uid = response.json()["id"]
                    else:
                        print(f"Warning: Failed to fetch UID for email {email}: {response.status_code}")
                except Exception as e:
                    print(f"Error fetching UID for email {email}: {e}")
            
            enhanced_question = analyze_and_enhance_question(text, uid)
            # Save message to DB and process with context awareness
            create_message_in_db(username, enhanced_question, ts, channel_id,uid)
        except Exception as e:
            logger.error(f"Error in handle_message_events for user {user_id}: {e}", exc_info=True)
            say("Sorry, an error occurred while processing your message.")

@app.event("app_mention")
def handle_app_mention(event, say):
    user_id = event.get("user") # Renamed from 'user' to 'user_id' for clarity
    text = event.get("text", "")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if not user_id or not text:
        return

    try:
        # Get user info
        user_info_response = app.client.users_info(user=user_id)
        user_profile = user_info_response["user"]["profile"]
        username = user_profile.get("real_name") or user_profile.get("display_name") or user_id
        email = user_profile.get("email")

        if not email:
            logger.warning(f"Could not retrieve email for user {username} ({user_id}) in app_mention. Cannot check permissions.")
            say("I couldn't verify your permissions because your email is not available. Please check your Slack profile or contact an admin.")
            return

        bot_id_response = app.client.auth_test()
        bot_id = bot_id_response["user_id"]
        mention = f"<@{bot_id}>"
        stripped_text = text.replace(mention, "").strip()

        logger.info(f"Mention by {username} ({email}): {stripped_text}")

        # === PERMISSION CHECK ===
        if not check_user_permission(email, BASE_API_URL):
            logger.warning(f"User {username} ({email}) is not allowed for app_mention interaction.")
            say("Sorry, you are not authorized to use this feature.")
            return
        if email:
            try:
                response = requests.get(f"{BASE_API_URL}/api/v1/agent_users/{email}", timeout=10)

                if response.status_code == 200:
                    uid = response.json()["id"]
                else:
                    print(f"Warning: Failed to fetch UID for email {email}: {response.status_code}")
            except Exception as e:
                print(f"Error fetching UID for email {email}: {e}")
        
        enhanced_question = analyze_and_enhance_question(text, uid)
        # Save message to DB and process with context awareness
        create_message_in_db(username, enhanced_question, ts, channel_id,uid)
    except Exception as e:
        logger.error(f"Error in handle_app_mention for user {user_id}: {e}", exc_info=True)
        say("Sorry, an error occurred while processing your mention.")

@celery_app.task(name='app.listeners.slack.process_pending_messages')
def process_pending_messages():
    """
    Celery task to process any pending messages in the database
    """
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/messages/?status=pending")
        if response.status_code == 200:
            pending_messages = response.json()
            logger.info(f"Found {len(pending_messages)} pending messages to process")
            
            for message in pending_messages:
                slack_handler.process_new_message(message)
    except Exception as e:
        logger.error(f"Error processing pending messages: {e}")

@celery_app.task(name='app.listeners.slack.run_slack_listener')
def run_slack_listener():
    """
    Celery task to start the Slack socket mode handler.
    This is a long-running task that will block until the connection is closed.
    """
    logger.info("Starting Context-Aware Slack Listener Bot from Celery task...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
    # This is a blocking call - the task will remain active as long as the socket connection is open

# ——— ENTRY POINT ———
if __name__ == "__main__":
    logger.info("Starting Context-Aware Slack Listener Bot directly...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
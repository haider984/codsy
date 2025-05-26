import os
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback
BASE_API_URL = os.getenv("BASE_API_URL")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GenericBot")

# Don't initialize client globally, we'll do it per request
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

class GenericMessageHandler:
    def __init__(self):
        self.clients = {}  # Cache for Groq clients

    def get_groq_client(self, username):
        """Get a Groq client for the username, with fallback to environment variable"""
        # Extract email from username if it has @ symbol
        email = username if '@' in username else f"{username}@example.com"
        
        # Return cached client if available
        if email in self.clients:
            return self.clients[email]
        
        # Try to get API key from database
        api_key = get_groq_api_key(email)
        
        # Fall back to environment variable if needed
        if not api_key:
            if GROQ_API_KEY:
                api_key = GROQ_API_KEY
                logger.warning(f"Using fallback GROQ API key for {email}")
            else:
                logger.error(f"No GROQ API key available. Cannot generate response.")
                return None
                
        # Create and cache client
        try:
            client = Groq(api_key=api_key)
            self.clients[email] = client
            return client
        except Exception as e:
            logger.error(f"Error creating Groq client: {e}")
            return None

    # def get_message_history(self):
    #     try:
    #         response = requests.get(f"{BASE_API_URL}/api/v1/messages/")
    #         response.raise_for_status()
    #         all_messages = response.json()
    #         return all_messages[-10:]  # Return only the last 10 messages
    #     except Exception as e:
    #         logger.error(f"Error fetching message history: {e}")
    #         return []

    def get_message_history(self, uid):
        try:
            if not uid:
                logger.error("UID is required to fetch message history.")
                return []

            response = requests.get(f"{BASE_API_URL}/api/v1/messages/", params={"uid": uid})
            response.raise_for_status()
            all_messages = response.json()

            message_count = len(all_messages)

            if message_count == 0:
                logger.info(f"No messages found for uid={uid}")
                return []

            if message_count <= 10:
                logger.info(f"Found {message_count} messages for uid={uid} (less than or equal to 10)")
                return all_messages
            else:
                logger.info(f"Found {message_count} messages for uid={uid} — returning last 10")
                return all_messages[-10:]
        except Exception as e:
            logger.error(f"Error fetching message history for uid={uid}: {e}")
            return []


    def generate_llm_response(self, message_content, message_history):
        try:
            # Get username from last message if available
            username = None
            if message_history:
                username = message_history[-1].get("username", "service@codsy.ai")
            
            # Get client for this user
            client = self.get_groq_client(username)
            if not client:
                return "I'm sorry, I couldn't process your request due to configuration issues."
                
            system_prompt = """
            You are a helpful assistant responding to messages from various users on different channels (like Slack or Email).
            When generating replies, be polite and refer to previous messages if needed. Try to use the user's name if available.
            """

            formatted_messages = [{"role": "system", "content": system_prompt}]

            for msg in message_history:
                username = msg.get("username", "User")
                timestamp = msg.get("message_datetime", "")
                channel = msg.get("channel", "unknown")

                user_line = f"[{username} on {channel} at {timestamp}] {msg['content']}"
                formatted_messages.append({"role": "user", "content": user_line})

                if msg.get("reply") and msg["reply"] not in [None, "", "null"]:
                    formatted_messages.append({"role": "assistant", "content": msg["reply"]})

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=formatted_messages,
                temperature=0.7,
                max_completion_tokens=200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return "Hi there! How can I help you today?"

    def update_message_with_reply(self, mid, original_message, reply):
        try:
            payload = {
                "content": original_message["content"],
                "reply": reply,
                "message_type": "greeting",
                "processed": True,
                "status": "processed",
                "username": original_message.get("username", ""),
                "message_datetime": original_message.get("message_datetime", datetime.now(timezone.utc).isoformat()),
                "sid": original_message.get("sid", ""),
                "uid": original_message.get("uid", ""),
                "pid": original_message.get("pid", ""),
                "source": original_message.get("source", ""),
                "msg_id": original_message.get("msg_id", ""),
                "channel": original_message.get("channel", ""),
                "thread_ts": original_message.get("thread_ts", "")
            }

            response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)
            if response.status_code == 200:
                logger.info(f"Updated message {mid} with reply")
                return True
            else:
                logger.error(f"Update failed: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False

    # def process_message(self, message, message_type="greeting"):
    #     mid = message.get("mid")
    #     if not mid:
    #         logger.warning("Message missing 'mid', skipping")
    #         return False

    #     logger.info(f"Handling greeting message {mid}")
    #     history = self.get_message_history()
    #     reply = self.generate_llm_response(message.get("content", ""), history)
    #     return self.update_message_with_reply(mid, message, reply)
    def process_message(self, message, message_type="greeting"):
        mid = message.get("mid")
        uid = message.get("uid")

        if not mid or not uid:
            logger.warning("Message missing 'mid' or 'uid', skipping")
            return False

        logger.info(f"Handling greeting message {mid} for uid {uid}")
        history = self.get_message_history(uid)
        reply = self.generate_llm_response(message.get("content", ""), history)
        return self.update_message_with_reply(mid, message, reply)


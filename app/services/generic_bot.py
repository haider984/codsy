import os
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Use INTERNAL_BASE_API_URL for calls made from within worker containers
INTERNAL_BASE_API_URL = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000") # Default internal URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s:%(lineno)d %(message)s', # Added name/lineno
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__) # Use __name__ for logger

# Initialize Groq client at the module level
client = None
if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized successfully at module level.")
    except Exception as e:
        logger.error(f"Failed to initialize Groq client at module level: {e}")
else:
    logger.warning("GROQ_API_KEY not found. LLM functions will be unavailable.")

class GenericMessageHandler:
    def __init__(self):
        # No need to re-initialize client here, module-level handles it.
        # The check 'if not client:' should happen in methods that USE the client.
        pass

    def get_message_history(self):
        """Fetch recent message history from the API using the internal URL."""
        url = f"{INTERNAL_BASE_API_URL}/api/v1/messages/?limit=20" # Example: limit history size
        logger.debug(f"Fetching message history from {url}")
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching message history from {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Generic error fetching message history: {e}")
            return []

    def generate_llm_response(self, message_content, message_history):
        """Generate LLM response using Groq."""
        # Check if client was initialized successfully at module level
        if not client:
             logger.error("Groq client not available for LLM generation.")
             return "Sorry, I cannot generate a response right now."
        try:
            system_prompt = """
            You are a helpful assistant responding to messages. Be polite and conversational.
            Refer to the user's name if available in the history. Keep responses concise.
            """
            # Prepare messages for LLM, potentially limiting history length
            formatted_messages = [{"role": "system", "content": system_prompt}]
            history_limit = 10 # Limit context window
            relevant_history = message_history[-history_limit:]

            for msg in relevant_history:
                role = "assistant" if msg.get("reply") else "user"
                content = msg.get("reply") if role == "assistant" else msg.get("content")
                if content: # Only add if there's content
                    formatted_messages.append({"role": role, "content": content})

            # Add the current message content
            if message_content:
                formatted_messages.append({"role": "user", "content": message_content})

            logger.debug(f"Sending {len(formatted_messages)} items to Groq LLM.")
            response = client.chat.completions.create(
                model="llama3-8b-8192", # Smaller model might be sufficient for greetings
                messages=formatted_messages,
                temperature=0.7,
                max_tokens=150 # Adjusted max tokens
            )
            llm_reply = response.choices[0].message.content.strip()
            logger.info("LLM generated reply successfully.")
            return llm_reply
        except Exception as e:
            logger.error(f"LLM generation failed: {e}", exc_info=True)
            # Fallback response
            return "I received your message. How can I assist you further?"

    def update_message_with_reply(self, mid, original_message, reply):
        """Update the original message with the generated reply using internal URL."""
        # Corrected: Use INTERNAL_BASE_API_URL
        api_endpoint = f"{INTERNAL_BASE_API_URL}/api/v1/messages/{mid}"
        try:
            # Ensure all required fields for PUT are included from original_message
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
            # Remove None values if API doesn't like them
            payload = {k: v for k, v in payload.items() if v is not None}

            logger.debug(f"Updating message {mid} via PUT {api_endpoint} with reply.")
            response = requests.put(api_endpoint, json=payload)

            if response.status_code == 200:
                logger.info(f"Successfully updated message {mid} with reply.")
                return True
            else:
                # Log detailed error
                logger.error(f"Failed to update message {mid} with reply: {response.status_code} - {response.text}. Payload: {payload}")
                return False
        except Exception as e:
            logger.error(f"Exception updating message {mid}: {e}", exc_info=True)
            return False

    def process_message(self, message, message_type="greeting"):
        """Process a message classified as 'greeting'."""
        mid = message.get("mid")
        if not mid:
            logger.warning("Message missing 'mid', cannot process.")
            return False

        logger.info(f"Processing greeting message {mid}...")
        # Fetch limited history for context
        history = self.get_message_history() # Maybe filter history by user/channel?
        # Generate reply using LLM
        reply = self.generate_llm_response(message.get("content"), history)
        # Update the message in DB with the reply
        return self.update_message_with_reply(mid, message, reply)

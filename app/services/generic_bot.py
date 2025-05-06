import os
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq

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
logger = logging.getLogger("GenericBot")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

class GenericMessageHandler:
    def __init__(self):
        pass

    def get_message_history(self):
        try:
            response = requests.get(f"{BASE_API_URL}/api/v1/messages/")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching message history: {e}")
            return []

    def generate_llm_response(self, message_content, message_history):
        try:
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

    def process_message(self, message, message_type="greeting"):
        mid = message.get("mid")
        if not mid:
            logger.warning("Message missing 'mid', skipping")
            return False

        logger.info(f"Handling greeting message {mid}")
        history = self.get_message_history()
        reply = self.generate_llm_response(message.get("content", ""), history)
        return self.update_message_with_reply(mid, message, reply)

import os
import time
import requests
import redis
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime, timezone
from app.celery_app import celery_app  # Import Celery app

# Load environment variables
load_dotenv()

# Config
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

# Initialize Redis for task locking
try:
    redis_client = redis.from_url(REDIS_URL)
    REDIS_AVAILABLE = True
    print("✅ Redis connection established for task locking")
except Exception as e:
    print(f"❌ Failed to connect to Redis: {e}")
    REDIS_AVAILABLE = False

client = WebClient(token=SLACK_BOT_TOKEN)
BASE_API_URL = os.getenv("BASE_API_URL")
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = "agent.tom@codsy.ai"
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
LOCK_EXPIRE_TIME = 300  # seconds (5 minutes)

# ─── ACCESS TOKEN ──────────────────────────────────────────────────────────────

def get_access_token():
    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    response = requests.post(AUTH_URL, data=token_data)
    token_json = response.json()
    if "access_token" in token_json:
        print("✅ Access Token Fetched")
        return token_json["access_token"]
    else:
        print("❌ Error fetching token:", token_json)
        return None

# ─── LOCK FUNCTIONS ─────────────────────────────────────────────────────────────

def acquire_lock(mid):
    """Try to acquire a lock for the message to prevent race conditions"""
    if not REDIS_AVAILABLE:
        return True  # If Redis not available, proceed without locking
        
    lock_key = f"reply_lock:message:{mid}"
    worker_id = os.environ.get("HOSTNAME", "unknown")
    
    # Try to set the lock with NX (only set if not exists)
    locked = redis_client.set(
        lock_key, 
        worker_id, 
        ex=LOCK_EXPIRE_TIME,  # Expiry time in seconds
        nx=True
    )
    
    if locked:
        print(f"✅ Acquired lock for message {mid}")
        return True
    else:
        # Check who has the lock
        owner = redis_client.get(lock_key)
        print(f"⚠️ Message {mid} already being processed by {owner}")
        return False
        
def release_lock(mid):
    """Release the message lock"""
    if not REDIS_AVAILABLE:
        return
        
    lock_key = f"reply_lock:message:{mid}"
    redis_client.delete(lock_key)
    print(f"🔓 Released lock for message {mid}")

# ─── SEND REPLY ────────────────────────────────────────────────────────────────

def reply_to_email(message_id, response_body):
    access_token = get_access_token()
    if not access_token:
        return False

    url = f"{GRAPH_API}/users/{USER_EMAIL}/messages/{message_id}/reply"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "comment": response_body
    }
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code == 202:
        print(f"📧 Replied to message {message_id}")
        return True
    else:
        print(f"❌ Failed to reply to {message_id}: {resp.status_code} | {resp.text}")
        return False

def send_slack_reply(channel_id, message_text, thread_ts=None):
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text=message_text,
            thread_ts=thread_ts
        )
        print(f"✅ Reply sent to Slack | channel: {channel_id} | thread_ts: {response['ts']}")
        return response
    except SlackApiError as e:
        print(f"❌ Slack API Error: {e.response['error']}")
        return None

def get_processed_message_ids():
    try:
        url = f"{BASE_API_URL}/api/v1/messages/by_status/?status=processed"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Failed to fetch message IDs: {e}")
        return []

def get_message_by_mid(mid):
    try:
        url = f"{BASE_API_URL}/api/v1/messages/{mid}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Failed to fetch message {mid}: {e}")
        return None

def update_status(mid, original_message):
    """Update the message status to successful in DB"""
    try:
        # Get the current message data to ensure we have all fields
        url = f"{BASE_API_URL}/api/v1/messages/{mid}"
        get_response = requests.get(url)
        get_response.raise_for_status()
        message_data = get_response.json()
        
        # Just update the status field
        message_data["status"] = "successful"
        
        # Send the update
        response = requests.put(url, json=message_data)

        if response.status_code == 200:
            print(f"✅ Successfully updated message {mid} to successful")
            return True
        else:
            print(f"❌ Failed to update message {mid}: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception while updating message {mid}: {e}")
        return False

@celery_app.task(name='app.listeners.reply.send_pending_replies_task')
def send_pending_replies_task():
    """Celery task to process messages and send replies"""
    mids = get_processed_message_ids()
    print(f"🔍 Found {len(mids)} processed messages")
    
    sent_count = 0
    for entry in mids:
        mid = entry.get("mid")
        if not mid:
            continue

        # Try to acquire a lock for this message
        if not acquire_lock(mid):
            print(f"⏭️ Skipping message {mid} - already being processed by another worker")
            continue
            
        try:
            message = get_message_by_mid(mid)
            if not message:
                continue

            channel = message.get("channel", "").lower()
            reply = message.get("reply")

            if not reply:
                print(f"⚠️ Skipping message {mid} — no reply content")
                continue

            success = False

            if channel == "email" and message.get("msg_id"):
                success = reply_to_email(
                    message_id=message["msg_id"],
                    response_body=message["reply"]
                )

            elif channel == "slack" and message.get("channel_id") and message.get("thread_ts"):
                success = send_slack_reply(
                    channel_id=message["channel_id"],
                    message_text=message["reply"],
                    thread_ts=message["thread_ts"]
                )

            else:
                print(f"⚠️ Skipping message {mid} — unsupported channel or missing fields")

            if success:
                update_status(mid, message)
                sent_count += 1
        except Exception as e:
            print(f"❌ Error processing message {mid}: {e}")
        finally:
            # Always release the lock when done
            release_lock(mid)
    
    return f"Processed {len(mids)} messages, sent {sent_count} replies"

def process_messages():
    """Original function to process messages in a loop"""
    return send_pending_replies_task()

def main():
    """Main function for running as a standalone script"""
    while True:
        print("🔁 Checking for new messages...")
        process_messages()
        time.sleep(10)  # Wait for 10 seconds before polling again
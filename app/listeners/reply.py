import os
import time
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime, timezone
from app.celery_app import celery_app  # Import the Celery app

# Load environment variables
load_dotenv()

# Config
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")

client = WebClient(token=SLACK_BOT_TOKEN)
BASE_API_URL = os.getenv("BASE_API_URL")
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = "agent.tom@codsy.ai"
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

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
            "message_type": original_message.get("message_type", ""),
            "processed": True,  # Assuming the message is processed
            "status": "successful"
        }

        print(f"Updating message {mid} with payload: {payload}")
        response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)

        if response.status_code == 200:
            print(f"✅ Successfully updated message {mid}")
            return True
        else:
            print(f"❌ Failed to update message {mid}: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception while updating message {mid}: {e}")
        return False

# Add the Celery task decorator
@celery_app.task(name='app.listeners.reply.send_pending_replies_task')
def send_pending_replies_task():
    """Celery task to process messages and send replies"""
    mids = get_processed_message_ids()
    print(f"🔍 Found {len(mids)} processed messages")

    processed_count = 0
    for entry in mids:
        mid = entry.get("mid")
        if not mid:
            continue

        message = get_message_by_mid(mid)
        if not message:
            continue

        # Only process messages with status "processed", not those already being handled
        if message.get("status") != "processed":
            print(f"⚠️ Skipping message {mid} — status is not 'processed'")
            continue

        channel = message.get("channel", "").lower()
        reply = message.get("reply")

        if not reply:
            print(f"⚠️ Skipping message {mid} — no reply content")
            continue

        # Mark message as being handled to prevent other workers from processing it
        mark_as_handling(mid, message)

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
            processed_count += 1
    
    return f"Processed {processed_count} replies"

def mark_as_handling(mid, original_message):
    """Mark message as being handled to prevent duplicate processing"""
    try:
        payload = original_message.copy()
        payload["status"] = "handling"  # Temporary status while processing
        
        print(f"Marking message {mid} as 'handling'")
        response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)
        
        if response.status_code == 200:
            print(f"✅ Successfully marked message {mid} as handling")
            return True
        else:
            print(f"❌ Failed to mark message {mid}: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception while marking message {mid}: {e}")
        return False

# Keep the original process_messages function for backward compatibility
def process_messages():
    mids = get_processed_message_ids()
    print(f"🔍 Found {len(mids)} processed messages")

    for entry in mids:
        mid = entry.get("mid")
        if not mid:
            continue

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

def main():
    while True:
        print("🔁 Checking for new messages...")
        process_messages()
        time.sleep(10)  # Wait for 10 seconds before polling again
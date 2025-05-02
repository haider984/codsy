import os
import time
import requests
import logging
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime, timezone, timedelta

# Import Celery app instance
from ..celery_app import celery_app

# Load environment variables
load_dotenv()

# Config
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
# Use INTERNAL_BASE_API_URL for calls from worker to web API
INTERNAL_BASE_API_URL = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000")
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = os.getenv("USER_EMAIL", "agent.tom@codsy.ai")
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

# --- LOGGER SETUP ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s")
logger = logging.getLogger(__name__)

# Initialize Slack WebClient
slack_client = None
if SLACK_BOT_TOKEN:
    try:
        slack_client = WebClient(token=SLACK_BOT_TOKEN)
        logger.info("Slack client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Slack client: {e}", exc_info=True)
else:
    logger.warning("SLACK_BOT_TOKEN not found. Slack replies will fail.")

# Global token cache
_graph_token = None
_graph_token_expiry = None

def get_access_token():
    global _graph_token, _graph_token_expiry
    now = datetime.now(timezone.utc)
    if _graph_token and _graph_token_expiry and now < _graph_token_expiry:
        logger.debug("Using cached MS Graph token.")
        return _graph_token
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
        logger.error("Missing Microsoft Graph API credentials for reply task.")
        return None
    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(AUTH_URL, data=token_data, timeout=10)
        response.raise_for_status()
        token_json = response.json()
        if "access_token" in token_json:
             _graph_token = token_json["access_token"]
             expires_in = int(token_json.get("expires_in", 3599))
             _graph_token_expiry = now + timedelta(seconds=expires_in - 60)
             logger.info("✅ Access Token Fetched")
             return token_json["access_token"]
        else:
            logger.error(f"❌ Error fetching token: {token_json}")
            return None
    except requests.exceptions.RequestException as e: logger.error(f"❌ Network error fetching MS Graph token: {e}"); return None
    except Exception as e: logger.error(f"❌ Unexpected error fetching MS Graph token: {e}", exc_info=True); return None

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
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code == 202:
            logger.info(f"📧 Replied to message {message_id}")
            return True
        else:
            logger.error(f"❌ Failed to reply to {message_id}: {resp.status_code} | {resp.text}")
            return False
    except requests.exceptions.RequestException as e: logger.error(f"❌ Network error replying to email {message_id}: {e}"); return False
    except Exception as e: logger.error(f"❌ Unexpected error replying to email {message_id}: {e}", exc_info=True); return False

def send_slack_reply(channel_id, message_text, thread_ts=None):
    if not slack_client: logger.error("Slack client not initialized."); return False
    try:
        response = slack_client.chat_postMessage(
            channel=channel_id,
            text=message_text,
            thread_ts=thread_ts
        )
        logger.info(f"✅ Reply sent to Slack | channel: {channel_id} | new_ts: {response['ts']}")
        return response
    except SlackApiError as e: logger.error(f"❌ Slack API Error: {e.response['error']}"); return None
    except Exception as e: logger.error(f"❌ Unexpected error sending Slack reply: {e}", exc_info=True); return None

def get_processed_message_ids():
    url = f"{INTERNAL_BASE_API_URL}/api/v1/messages/by_status/?status=processed"
    logger.debug(f"Fetching processed message IDs from {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        ids_data = response.json()
        logger.info(f"🔍 Found {len(ids_data)} processed message entries.")
        return ids_data
    except Exception as e:
        logger.error(f"❌ Failed to fetch message IDs: {e}")
        return []

def get_message_by_mid(mid):
    url = f"{INTERNAL_BASE_API_URL}/api/v1/messages/{mid}"
    logger.debug(f"Fetching full message details for {mid} from {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch message {mid}: {e}")
        return None

def update_status(mid, original_message):
    """Update the message status to successful in DB"""
    api_endpoint = f"{INTERNAL_BASE_API_URL}/api/v1/messages/{mid}"
    try:
        payload = original_message.copy()
        payload["status"] = "successful"
        payload["processed"] = True
        payload.pop("_id", None)
        payload.pop("id", None)

        logger.debug(f"Updating message {mid} status to successful via PUT {api_endpoint}")
        response = requests.put(api_endpoint, json=payload, timeout=10)

        if response.status_code == 200:
            logger.info(f"✅ Successfully updated message {mid} status to successful")
            return True
        else:
            logger.error(f"❌ Failed to update message {mid} status: {response.status_code} {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Exception while updating message {mid} status: {e}")
        return False

# --- CELERY TASK ---
@celery_app.task(name="app.listeners.slack_reply.send_pending_replies_task")
def send_pending_replies_task():
    """
    Celery task wrapper for the original process_messages logic.
    Fetches processed message IDs, gets full message, and attempts replies.
    """
    task_logger = logging.getLogger(__name__ + ".task")
    task_logger.info("🔁 Starting reply sending task run...")

    mids_entries = get_processed_message_ids()
    task_logger.info(f"🔍 Found {len(mids_entries)} processed message entries.")

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for entry in mids_entries:
        mid = entry.get("mid")
        if not mid:
            task_logger.warning("Skipping entry with no 'mid'.")
            skipped_count += 1
            continue

        message = get_message_by_mid(mid)
        if not message:
            task_logger.warning(f"Could not fetch full details for mid {mid}. Skipping.")
            skipped_count += 1
            continue

        channel = message.get("source", "").lower()
        reply = message.get("reply")

        if not reply:
            task_logger.warning(f"⚠️ Skipping message {mid} — no reply content")
            skipped_count += 1
            continue

        task_logger.info(f"Processing reply for message {mid} (channel: {channel})")
        success = False

        if channel == "email" and message.get("msg_id"):
            success = reply_to_email(
                message_id=message["msg_id"],
                response_body=message["reply"]
            )

        elif channel == "slack" and message.get("channel_id"):
            slack_response = send_slack_reply(
                channel_id=message["channel_id"],
                message_text=message["reply"],
                thread_ts=message.get("thread_ts")
            )
            success = slack_response is not None

        else:
            task_logger.warning(f"⚠️ Skipping message {mid} — unsupported channel '{channel}' or missing fields")
            skipped_count += 1
            continue

        if success:
            if update_status(mid, message):
                sent_count += 1
            else:
                task_logger.warning(f"Reply sent for {mid}, but failed to update DB status.")
                failed_count += 1
        else:
            task_logger.error(f"Failed attempt to send reply for message {mid} (channel: {channel}).")
            failed_count += 1

    task_logger.info(f"Finished reply sending task run. Sent: {sent_count}, Failed/Update Errors: {failed_count}, Skipped: {skipped_count}")

# --- REMOVED ORIGINAL main() and if __name__ == "__main__": block ---

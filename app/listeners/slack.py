import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import requests
from datetime import datetime, timezone # Removed unused timedelta

# Import the Celery app instance
from ..celery_app import celery_app

# ——— CONFIGURATION ———
load_dotenv()
SLACK_BOT_TOKEN   = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN   = os.getenv("SLACK_APP_TOKEN")
# BASE_API_URL is used by the listener process if it makes direct calls (currently doesn't)
# BASE_API_URL = os.getenv("BASE_API_URL", "http://localhost:8000")
# ——— LOGGER + SLACK INIT ———
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)
# Initialize handler only if app token is present
handler = SocketModeHandler(app, SLACK_APP_TOKEN) if SLACK_APP_TOKEN else None


# Define a Celery task for processing/saving the message
@celery_app.task(name="app.listeners.slack.process_slack_message_task")
def process_slack_message_task(username, text, msg_ts, channel_id, source, message_type, email=None):
    """Celery task to save Slack message details to the database."""
    # Ensure logger configuration is effective in the worker context as well
    # logging.basicConfig(level=logging.INFO) # Maybe needed if worker logging isn't set up globally
    task_logger = logging.getLogger(__name__ + ".task") # Use a specific logger for the task

    sid = "680f69cc5c250a63d068bbec"
    uid = "680f69605c250a63d068bbeb"
    pid = "60c72b2f9b1e8a3f4c8a1b2c"

    internal_api_url = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000")

    payload = {
        "sid": sid,
        "uid": uid,
        "pid": pid,
        "username": username,
        "content": text,
        "reply": "",
        "message_datetime": datetime.now(timezone.utc).isoformat(),
        "source": "slack",
        "msg_id": "",
        "channel": "slack",
        "channel_id": channel_id,
        "thread_ts": msg_ts,
        "message_type": "",
        "processed": False,
        "status": "pending"
    }

    try:
        api_endpoint = f"{internal_api_url}/api/v1/messages/"
        task_logger.debug(f"[Slack Worker] Posting message to {api_endpoint} for ts {msg_ts}")
        resp = requests.post(api_endpoint, json=payload)

        if resp.status_code in (200, 201):
            response_data = resp.json()
            mid = response_data.get("mid")
            if mid:
                task_logger.info(f"[Slack Worker] Message saved to DB for ts {msg_ts}. Received mid: {mid}")
            else:
                 task_logger.error(f"[Slack Worker] Message API success for ts {msg_ts}, but 'mid' not found: {response_data}")
        else:
            task_logger.error(f"[Slack Worker] Failed to save message {msg_ts} to DB: {resp.status_code} {resp.text}")
    except requests.exceptions.RequestException as e:
        task_logger.error(f"[Slack Worker] Network error posting message to DB for ts {msg_ts}: {e}")
    except Exception as e:
        task_logger.error(f"[Slack Worker] Unexpected error posting message to DB for ts {msg_ts}: {e}", exc_info=True)

@app.event("message")
def handle_message_events(event, say):
    listener_logger = logging.getLogger(__name__ + ".listener") # Specific logger
    user = event.get("user")
    text = event.get("text", "").strip()
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if subtype or not user or not text:
        return

    if channel_type in ("im", "mpim"):
        try:
            user_info = app.client.users_info(user=user)
            user_profile = user_info["user"]["profile"]
            username = user_profile.get("real_name") or user_profile.get("display_name") or user
            email = user_profile.get("email")
            listener_logger.info(f"[Slack Listener] DM received (ts:{ts}) from {username} ({email or 'No email'}). Enqueuing task.")

            process_slack_message_task.delay(
                username=username, text=text, msg_ts=ts, channel_id=channel_id,
                source="slack_dm", message_type="received", email=email
            )
        except Exception as e:
            listener_logger.error(f"[Slack Listener] Error handling DM (ts:{ts}): {e}", exc_info=True)

@app.event("app_mention")
def handle_app_mention(event, say):
    listener_logger = logging.getLogger(__name__ + ".listener") # Specific logger
    user = event.get("user")
    text = event.get("text", "")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if not user or not text:
        return

    try:
        user_info = app.client.users_info(user=user)
        user_profile = user_info["user"]["profile"]
        username = user_profile.get("real_name") or user_profile.get("display_name") or user

        bot_mention_pattern = f"<@{event.get('api_app_id', 'UNKNOWN_BOT_ID')}>"
        stripped_text = text.replace(bot_mention_pattern, "").strip()

        listener_logger.info(f"[Slack Listener] Mention received (ts:{ts}) in {channel_id} by {username}. Enqueuing task.")

        process_slack_message_task.delay(
            username=username, text=stripped_text or text, msg_ts=ts, channel_id=channel_id,
            source="slack_mention", message_type="received"
        )
    except Exception as e:
        listener_logger.error(f"[Slack Listener] Error handling mention (ts:{ts}): {e}", exc_info=True)


# ——— ENTRY POINT ———
if __name__ == "__main__":
    # Ensure handler was initialized (requires SLACK_APP_TOKEN)
    if handler:
        logger.info("[Slack Listener] Starting Slack Listener Bot (Socket Mode)...")
        handler.start()
    else:
        logger.error("[Slack Listener] SocketModeHandler not initialized (Missing SLACK_APP_TOKEN?). Cannot start listener.")
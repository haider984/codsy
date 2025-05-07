import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import requests
from datetime import datetime, timezone, timedelta
from app.celery_app import celery_app  # Import the Celery app

# ——— CONFIGURATION ———
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")
# ——— LOGGER + SLACK INIT ———
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)


def create_message_in_db(username,text, msg_ts, channel_id):
    sid = "680f69cc5c250a63d068bbec"  # Static for now
    uid = "680f69605c250a63d068bbeb"
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
        "message_type": "",
        "processed": False,
        "status": "pending"
    }

    try:
        resp = requests.post(f"{BASE_API_URL}/api/v1/messages/", json=payload)
        if resp.status_code in (200, 201):
            logger.info(f"Message ID: {resp.text}")
            logger.info(f"Message saved to DB: {msg_ts}")
        else:
            logger.error(f"Failed to save message {msg_ts}: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Error posting message to DB: {e}")

        
@app.event("message")
def handle_message_events(event, say):
    user = event.get("user")
    text = event.get("text", "").strip()
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if subtype or not user or not text:
        return

    if channel_type in ("im", "mpim"):  # Direct Message
        logger.info(f"DM from {user}: {text}")
        user_info = app.client.users_info(user=user)

        user_profile = user_info["user"]["profile"]
        username = user_profile.get("real_name") or user_profile.get("display_name") or user
        email = user_profile.get("email", "unknown@example.com")

        logger.info(f"DM from {username} ({email}): {text}")
        # Save message to DB
        create_message_in_db(username,text, ts, channel_id)
        

    

@app.event("app_mention")
def handle_app_mention(event, say):
    user = event.get("user")
    text = event.get("text", "")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if not user or not text:
        return

    bot_id = app.client.auth_test()["user_id"]
    mention = f"<@{bot_id}>"
    stripped = text.replace(mention, "").strip()

    logger.info(f"Mention by {user}: {stripped}")

    # Save message to DB
    create_message_in_db(stripped or text, ts, channel_id)


@celery_app.task(name='app.listeners.slack.run_slack_listener')
def run_slack_listener():
    """
    Celery task to start the Slack socket mode handler.
    This is a long-running task that will block until the connection is closed.
    """
    logger.info("Starting Slack Listener Bot from Celery task...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
    # This is a blocking call - the task will remain active as long as the socket connection is open


# ——— ENTRY POINT ———
if __name__ == "__main__":
    logger.info("Starting Slack Listener Bot directly...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()

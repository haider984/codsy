import os
import time
import requests
from datetime import datetime, timezone, timedelta
import logging
import re
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from app.celery_app import celery_app  # Import the Celery app
from app.services.agent_user import get_groq_api_key_sync

# ─── SETUP ─────────────────────────────────────────────────────────────────────

load_dotenv()

TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = os.getenv("USER_EMAIL") # This is the app's email, not the sender's for permission check
BASE_API_URL  = os.getenv("BASE_API_URL")
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_token = None
_token_expiry = None

# ─── PERMISSION CHECK HELPER ───────────────────────────────────────────────────

def check_user_permission(email: str, base_api_url: str) -> bool:
    """Checks if a user is allowed by querying the agent_users status endpoint."""
    if not email or email == "Unknown" or "@" not in email: # Basic email validity check
        logger.warning(f"Permission check: No valid email provided ('{email}'). Denying permission.")
        return False
    try:
        # Ensure email is URL-encoded if it contains special characters, though requests usually handles this.
        # Using a timeout for the request is a good practice.
        response = requests.get(f"{base_api_url}/api/v1/agent_users/status/email/{email}", timeout=10)
        if response.status_code == 200:
            status = response.json() # The endpoint directly returns the status string "allowed" or "not_allowed"
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


# ─── ACCESS TOKEN ──────────────────────────────────────────────────────────────

def get_access_token():
    global _token, _token_expiry
    now = datetime.now(timezone.utc)
    if _token and _token_expiry and now < _token_expiry:
        return _token
    resp = requests.post(AUTH_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    })
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expiry = now + timedelta(seconds=int(data["expires_in"]))
    return _token

# ─── MARK AS READ ──────────────────────────────────────────────────────────────

def mark_email_as_read(token, message_id):
    url = f"{GRAPH_API}/users/{USER_EMAIL}/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "isRead": True
    }
    resp = requests.patch(url, headers=headers, json=payload)
    if resp.status_code == 200:
        logger.info(f"Marked message {message_id} as read.")
    else:
        logger.error(f"Failed to mark {message_id} as read: {resp.status_code} {resp.text}")


# ─── Extract Meeting Invite Details ──────────────────────────────────────────────────────────────

def extract_meeting_details_bs(html_body):
    """
    Parse the HTML email body to extract:
      1) Meeting URL
      2) Meeting ID
      3) Passcode

    Step 1: Use "primary" or "original" logic
    Step 2: If any data is still 'Not Found', use fallback logic gleaned from screenshots
    """

    soup = BeautifulSoup(html_body, "html.parser")

    # ----------------------------------------------------------------------------
    # Step 1: Primary Logic
    # ----------------------------------------------------------------------------

    # 1) Meeting URL
    meeting_url_tag = soup.find("a", {"id": "meet_invite_block.action.join_link"})
    meeting_url = meeting_url_tag.get("href", "Not Found") if meeting_url_tag else "Not Found"

    # 2) Meeting ID
    meeting_id_label = soup.find("span", string=lambda text: text and "Meeting ID:" in text)
    if meeting_id_label:
        meeting_id_span = meeting_id_label.find_next_sibling("span")
        meeting_id = meeting_id_span.get_text(strip=True) if meeting_id_span else "Not Found"
    else:
        meeting_id = "Not Found"

    # 3) Passcode
    passcode_label = soup.find("span", string=lambda text: text and "Passcode:" in text)
    if passcode_label:
        passcode_span = passcode_label.find_next_sibling("span")
        passcode = passcode_span.get_text(strip=True) if passcode_span else "Not Found"
    else:
        passcode = "Not Found"

    # ----------------------------------------------------------------------------
    # Step 2: Fallback Logic
    # ----------------------------------------------------------------------------

    # Fallback for Meeting URL
    if meeting_url == "Not Found":
        fallback_link = soup.find("a", href=lambda x: x and ("teams.live.com" in x or "zoom.us" in x))
        if fallback_link:
            meeting_url = fallback_link.get("href", "Not Found")

    # Fallback for Meeting ID
    if meeting_id == "Not Found":
        meeting_code_span = soup.find("span", {"data-tid": "meeting-code"})
        if meeting_code_span:

            nested_meeting_id_span = meeting_code_span.find("span")
            if nested_meeting_id_span:
                meeting_id = nested_meeting_id_span.get_text(strip=True)
            else:

                parent_text = meeting_code_span.get_text(strip=True)

                match = re.search(r'(\d[\d\s]+)', parent_text)
                if match:
                    meeting_id = match.group(1).strip()

    # Fallback for Passcode
    if passcode == "Not Found":

        passcode_span = soup.find("span", {"data-id": "passcode"})
        if passcode_span:
            passcode = passcode_span.get_text(strip=True)
        else:

            fallback_passcode_label = soup.find("span", string=lambda text: text and "Passcode:" in text)
            if fallback_passcode_label:
                fallback_passcode_span = fallback_passcode_label.find_next_sibling("span")
                if fallback_passcode_span:
                    passcode = fallback_passcode_span.get_text(strip=True)


    return meeting_url, meeting_id, passcode

# ─── Extract Meeting Time Details ──────────────────────────────────────────────────────────────

def fetch_calendar_events(access_token):
    """
    Fetch the user's calendar events to see if there's a matching subject & upcoming time.
    """
    calendar_url = f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/calendar/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(calendar_url, headers=headers)
    if response.status_code != 200:
        print("❌ Error fetching calendar events:", response.text)
        return []
    events_json = response.json()
    events_list = events_json.get("value", [])
    results = []
    for ev in events_list:
        results.append({
            "subject": ev.get("subject", "No subject"),
            "start": ev.get("start", {}).get("dateTime", None),
            "end": ev.get("end", {}).get("dateTime", None),
        })
    return results


def parse_iso_datetime(dt_str):
    """
    Safely parse an ISO date/time string to a timezone-aware datetime.
    If naive, assume UTC.
    """
    if not dt_str:
        return None
    if dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        print(f"Error parsing datetime '{dt_str}': {e}")
        return None

def merge_meetings(email_meetings, calendar_events):
    """
    Try to pair up an email's meeting details with a future calendar event
    that has the same subject. If found, store them in merged_meetings.
    """
    merged_meetings = []
    now = datetime.now(timezone.utc)

    for em in email_meetings:
        subj_email = em["subject"].strip().lower()
        for ev in calendar_events:
            subj_cal = ev["subject"].strip().lower()
            start_dt_str = ev["start"]
            start_dt = parse_iso_datetime(start_dt_str)
            if start_dt and start_dt > now and subj_email == subj_cal:
                merged_meetings.append({
                    "subject":   em["subject"],
                    "meeting_url": em["meeting_url"],
                    "meeting_id":  em["meeting_id"],
                    "passcode":    em["passcode"],
                    "start":       ev["start"],
                    "end":         ev["end"]
                })
                break
    return merged_meetings

# ─── Classify emails ──────────────────────────────────────────────────────────────
def classify_email_with_llm(html_body, sender_email):
    """
    Use a ChatGroq LLM to classify the email into:
    'meeting', 'transcript', 'instructions', or 'other'.
    
    Now gets the API key from the database based on sender_email.
    """
    # Get the API key for this user
    is_allowed, api_key = get_groq_api_key_sync(sender_email, BASE_API_URL)
    
    # If user is not allowed or no key is available, use fallback or return error
    if not is_allowed:
        logger.error(f"User {sender_email} is not allowed to use Groq API")
        return "classification_error"
        
    if not api_key:
        # Try fallback to environment variable
        api_key = GROQ_API_KEY
        if not api_key:
            logger.error(f"No GROQ API key available for {sender_email} and no fallback configured")
            return "classification_error"
        else:
            logger.warning(f"Using fallback GROQ API key for {sender_email}")

    # Simplify HTML for LLM processing - extract text, maybe limit length
    try:
        soup = BeautifulSoup(html_body, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)

    except Exception as e:
        logger.error(f"Error parsing HTML for classification: {e}")
        body_text = "Error parsing body."

    try:
        # Use the user-specific API key
        llm = ChatGroq(model="llama3-70b-8192", api_key=api_key, temperature=0.5)
        classification_prompt = PromptTemplate(
            template = """
                Analyze the following email body and classify its primary purpose.
                Respond with ONLY ONE of the following keywords: 'meeting', 'other'.

                - **meeting**: The email is primarily an invitation, update, or reminder for a video conference (e.g., Microsoft Teams, Zoom, Google Meet). Look for keywords like "invite", "join", "meeting URL", "passcode", specific times/dates for a meeting.
                - **other**: The email does NOT fit the 'meeting' criteria. This includes transcripts, instructions on using tools (like Fireflies), general notifications, questions, etc.

                Email Body Text:
                {body}

                Classification:""",
            input_variables=["body"],
        )
        formatted_prompt = classification_prompt.format(body=body_text)
        response = llm.invoke(formatted_prompt)

        classification = response.content.strip().lower()
        # Validate response
        if classification not in ['meeting', 'other']:
            logger.warning(f"LLM classification returned unexpected value: '{classification}'. Defaulting to 'other'.")
            return 'other' # Default to 'other' if LLM response is invalid
        return classification
    except Exception as e:
         logger.error(f"LLM invocation failed during classification for {sender_email}: {e}", exc_info=True)
         return "classification_error" # Return specific error string



# ─── Create message in Message Table of DB ──────────────────────────────────────────────────────────────

def create_message_in_db(sender_email, subject, body_preview, msg_id):
    # Static for now. TODO: Lookup dynamically based on sender_email if needed.
    sid = "680f69cc5c250a63d068bbec"
    uid = "680f69605c250a63d068bbeb"
    pid = "60c72b2f9b1e8a3f4c8a1b2c"

    payload = {
        "sid": sid,
        "uid": uid,
        "pid": pid,
        "username": sender_email,
        "content": body_preview,
        "reply": "",
        "message_datetime": datetime.utcnow().isoformat() + "Z",
        "source": "email",
        "msg_id": msg_id,
        "channel": "email",
        "thread_ts": "",
        "channel_id":"",
        "message_type": "",
        "processed": False,
        "status": "pending"
    }

    try:
        resp = requests.post(
            f"{BASE_API_URL}/api/v1/messages/",
            json=payload
        )
        if resp.status_code in (200, 201):
            logger.info(f"Message ID: {resp.text}")
            # Extract the `mid` from the response
            mid = resp.json().get("mid")
            return mid
        else:
            logger.error(f"Failed to save message {msg_id}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Error posting message to DB: {e}")
        return None

# ───Create Meetings in Meeting Table of DB ──────────────────────────────────────────────────────────────

def create_meeting_in_db(email, meeting_url, meeting_id, passcode, start_time, end_time, mid):
    """
    Create a meeting entry in the database with the given details.
    """
    payload = {
        "mid": mid,
        "email": email,
        "meeting_url": meeting_url,
        "meeting_ID": meeting_id,
        "passcode": passcode,
        "start_time": start_time,
        "end_time": end_time,
    }

    try:
        resp = requests.post(f"{BASE_API_URL}/api/v1/meetings/", json=payload)
        if resp.status_code in (200, 201):
            logger.info(f"Meeting created in DB with mid: {mid}")
        else:
            logger.error(f"Failed to create meeting in DB: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Error posting meeting to DB: {e}")



# ─── POLL INBOX TASK ─────────────────────────────────────────────────────────────────

@celery_app.task(name='app.listeners.email.poll_inbox_task')
def poll_inbox_task():
    """
    Celery task to check for unread emails, process them, and mark as read.
    Will be scheduled to run periodically by Celery Beat.
    """
    processed_count = 0
    skipped_unauthorized = 0
    
    # Ensure BASE_API_URL is available for the permission check
    if not BASE_API_URL:
        logger.error("BASE_API_URL not set. Cannot perform permission checks.")
        return "Error: BASE_API_URL not configured."

    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH_API}/users/{os.getenv('USER_EMAIL')}/mailFolders/inbox/messages?$filter=isRead eq false" # Use app's user email here
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        messages = resp.json().get('value', [])
        logger.info(f"Found {len(messages)} unread messages.")

        for msg in messages:
            msg_id = msg["id"]
            
            # It's better to handle seen_ids logic at a higher level if possible,
            # or ensure it's robust. For now, proceeding with existing logic.
            # seen_ids = getattr(poll_inbox_task, 'seen_ids', set())
            # if msg_id in seen_ids:
            #     continue
            # seen_ids.add(msg_id)
            # poll_inbox_task.seen_ids = seen_ids # Persist if needed

            sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "Unknown")
            subject = msg.get("subject", "")
            body_preview = msg.get("bodyPreview", "")
            html_body    = msg.get("body", {}).get("content", "")
            # conversation_id = msg.get("conversationId") # Not currently used

            logger.info(f"Processing Email from {sender_email}, Subject: {subject}")

            # === PERMISSION CHECK ===
            if not check_user_permission(sender_email, BASE_API_URL):
                logger.warning(f"User {sender_email} is not allowed. Skipping processing for email '{subject}'.")
                mark_email_as_read(token, msg_id) # Mark as read to avoid reprocessing
                skipped_unauthorized += 1
                continue # Skip to the next message

            # --- Proceed with processing if user is allowed ---
            mid = create_message_in_db(sender_email, subject, body_preview, msg_id)
            if not mid:
                logger.error(f"Failed to create message in DB for msg_id: {msg_id}. Skipping further processing for this email.")
                mark_email_as_read(token, msg_id)
                continue
            
            # Pass sender_email to classify_email_with_llm to get the right API key
            classification = classify_email_with_llm(html_body, sender_email)
            logger.info(f"Email classified as: {classification}")

            if classification == "meeting":
                meeting_url, meeting_id, passcode = extract_meeting_details_bs(html_body)
                if meeting_url != "Not Found":
                    # Consider if start/end times should be extracted from email or calendar
                    start_time = datetime.now(timezone.utc).isoformat() 
                    end_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                    create_meeting_in_db(sender_email, meeting_url, meeting_id, passcode, start_time, end_time, mid)
                else:
                    logger.warning(f"Meeting details not found for email: {subject}")
            
            # TODO: Update message in DB with classification if your schema supports it
            # e.g., by calling a an update message endpoint with mid and classification.

            mark_email_as_read(token, msg_id)
            processed_count += 1
        
    except Exception as e:
        logger.error(f"Error during polling: {e}", exc_info=True)
        return f"Error during polling: {str(e)}"
        
    return f"Polling complete. Processed {processed_count} emails. Skipped {skipped_unauthorized} unauthorized emails."

# Original function maintained for backward compatibility or manual runs
def poll_inbox():
    """Legacy function that runs the polling in an infinite loop"""
    while True:
        poll_inbox_task()
        time.sleep(10)
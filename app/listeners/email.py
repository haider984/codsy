import os
import time # Keep time if needed for internal logic, but not for the main sleep
import requests
from datetime import datetime, timezone, timedelta
import logging
import re
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from bs4 import BeautifulSoup
# Remove load_dotenv here, it's handled by docker-compose or celery_app.py
# from dotenv import load_dotenv

# Import the Celery app instance we created
from ..celery_app import celery_app
# Import settings if needed for shared config (like BASE_API_URL if not passed via env)
# from ..core.config import settings

# ─── SETUP ─────────────────────────────────────────────────────────────────────
# load_dotenv() # Remove this

# Get environment variables (will be populated by docker-compose env_file)
TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = os.getenv("USER_EMAIL", "agent.tom@codsy.ai") # Provide default if useful
BASE_API_URL  = os.getenv("BASE_API_URL", "http://localhost:8000") # Get from env
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_token = None
_token_expiry = None

# Keep all your helper functions:
# get_access_token, mark_email_as_read, extract_meeting_details_bs,
# fetch_calendar_events, parse_iso_datetime, merge_meetings,
# classify_email_with_llm, create_message_in_db, create_meeting_in_db
# (Code for these functions remains the same as your original script)
# ... (Paste your existing functions here) ...
# ─── ACCESS TOKEN ──────────────────────────────────────────────────────────────

def get_access_token():
    global _token, _token_expiry
    now = datetime.now(timezone.utc)
    if _token and _token_expiry and now < _token_expiry:
        return _token

    # Check if essential credentials are loaded
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
        logger.error("Missing Microsoft Graph API credentials (TENANT_ID, CLIENT_ID, CLIENT_SECRET). Cannot obtain token.")
        # Optionally raise an exception or return None, depending on desired failure behavior
        raise ValueError("Missing Microsoft Graph API credentials.")

    resp = requests.post(AUTH_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    })
    try:
        resp.raise_for_status() # Will raise an HTTPError for bad responses (4xx or 5xx)
        data = resp.json()
        _token = data["access_token"]
        _token_expiry = now + timedelta(seconds=int(data["expires_in"]))
        logger.info("Successfully obtained new Microsoft Graph API access token.")
        return _token
    except requests.exceptions.RequestException as e:
        logger.error(f"Error requesting access token: {e}")
        logger.error(f"Response status: {resp.status_code}, Response body: {resp.text}")
        raise # Re-raise the exception to indicate failure

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
    try:
        resp = requests.patch(url, headers=headers, json=payload)
        if resp.status_code == 200:
            logger.info(f"Marked message {message_id} as read.")
        else:
            # Log more details on failure
            logger.error(f"Failed to mark {message_id} as read: {resp.status_code} - {resp.text}")
            resp.raise_for_status() # Optionally raise for non-200 status
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error marking email as read {message_id}: {e}")
        # Decide if you want to retry or just log

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
    if not html_body:
        logger.warning("Received empty HTML body for meeting detail extraction.")
        return "Not Found", "Not Found", "Not Found"

    try:
        soup = BeautifulSoup(html_body, "html.parser")

        # ----------------------------------------------------------------------------
        # Step 1: Primary Logic
        # ----------------------------------------------------------------------------

        # 1) Meeting URL
        meeting_url_tag = soup.find("a", {"id": "meet_invite_block.action.join_link"})
        meeting_url = meeting_url_tag.get("href", "Not Found") if meeting_url_tag else "Not Found"

        # 2) Meeting ID
        meeting_id_label = soup.find("span", string=lambda text: text and "Meeting ID:" in text)
        meeting_id = "Not Found"
        if meeting_id_label:
            meeting_id_span = meeting_id_label.find_next_sibling("span")
            if meeting_id_span:
                meeting_id = meeting_id_span.get_text(strip=True)

        # 3) Passcode
        passcode_label = soup.find("span", string=lambda text: text and "Passcode:" in text)
        passcode = "Not Found"
        if passcode_label:
            passcode_span = passcode_label.find_next_sibling("span")
            if passcode_span:
                passcode = passcode_span.get_text(strip=True)


        # ----------------------------------------------------------------------------
        # Step 2: Fallback Logic (Only if primary logic failed)
        # ----------------------------------------------------------------------------

        # Fallback for Meeting URL
        if meeting_url == "Not Found":
            # More robust search for various meeting link patterns
            fallback_link = soup.find("a", href=re.compile(r"https://(teams\.live\.com|zoom\.us|meet\.google\.com)/")) # Add other providers if needed
            if fallback_link:
                meeting_url = fallback_link.get("href", "Not Found")
            else: # Last resort: Find any link that looks like a meeting URL
                potential_links = soup.find_all("a")
                for link in potential_links:
                    href = link.get("href", "")
                    if "meeting" in href.lower() or "join" in href.lower():
                         meeting_url = href
                         break # Take the first likely candidate


        # Fallback for Meeting ID
        if meeting_id == "Not Found":
            # Look for common patterns using regex if specific tags fail
            text_content = soup.get_text(" ", strip=True)
            id_match = re.search(r'(?:Meeting ID|Conference ID|Meeting Number):\s*([\d\s]+)', text_content, re.IGNORECASE)
            if id_match:
                meeting_id = re.sub(r'\s+', '', id_match.group(1)) # Remove spaces often included
            else: # Try finding a long number sequence that might be an ID
                 potential_id_match = re.search(r'\b(\d{9,12})\b', text_content) # Zoom IDs are often 9-11 digits, Teams can vary
                 if potential_id_match:
                    meeting_id = potential_id_match.group(1)


        # Fallback for Passcode
        if passcode == "Not Found":
             # Look for common patterns using regex
            text_content = soup.get_text(" ", strip=True)
            passcode_match = re.search(r'(?:Passcode|Password):\s*([a-zA-Z0-9]+)', text_content, re.IGNORECASE)
            if passcode_match:
                passcode = passcode_match.group(1)


        return meeting_url, meeting_id, passcode

    except Exception as e:
        logger.error(f"Error parsing HTML for meeting details: {e}", exc_info=True)
        return "Error Parsing", "Error Parsing", "Error Parsing"

# ─── Extract Meeting Time Details ──────────────────────────────────────────────────────────────
# This section seems unused by the main poll_inbox logic based on the original script
# If fetch_calendar_events and merge_meetings ARE used, keep them.
# Otherwise, they can be removed or commented out for clarity.
# def fetch_calendar_events(access_token): ...
# def parse_iso_datetime(dt_str): ...
# def merge_meetings(email_meetings, calendar_events): ...

# ─── Classify emails ──────────────────────────────────────────────────────────────

# Ensure GROQ_API_KEY is set in the .env file for this to work
def classify_email_with_llm(html_body):
    """
    Use a ChatGroq LLM to classify the email into:
    'meeting', 'transcript', 'instructions', or 'other'.
    """
    if not os.getenv("GROQ_API_KEY"):
        logger.error("GROQ_API_KEY environment variable not set. Cannot classify email.")
        return "classification_error" # Return specific error string

    # Simplify HTML for LLM processing - extract text, maybe limit length
    try:
        soup = BeautifulSoup(html_body, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)
        # Optional: Truncate if bodies can be very large
        max_length = 4000 # Example limit
        if len(body_text) > max_length:
            body_text = body_text[:max_length] + "..."

    except Exception as e:
        logger.error(f"Error parsing HTML for classification: {e}")
        body_text = "Error parsing body."

    try:
        llm = ChatGroq(model="llama3-70b-8192", temperature=0.2) # Using known good model, adjust temp
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
         logger.error(f"LLM invocation failed during classification: {e}", exc_info=True)
         return "classification_error" # Return specific error string


# ─── Create message in Message Table of DB ──────────────────────────────────────────────────────────────

def create_message_in_db(username, subject, body_preview, msg_id, sender_email):
    # Static IDs - consider making these configurable or dynamic if needed
    sid = "680f69cc5c250a63d068bbec" # Example Session ID
    uid = "680f69605c250a63d068bbeb" # Example User ID (Maybe lookup based on sender_email?)
    pid = "60c72b2f9b1e8a3f4c8a1b2c" # Example Project ID (Maybe lookup based on sender_email or subject?)

    payload = {
        "sid": sid,
        "uid": uid,
        "pid": pid,
        "username": username, # Name of the sender
        "content": body_preview, # Preview of the email content
        "reply": "", # Placeholder for replies
        "message_datetime": datetime.now(timezone.utc).isoformat(), # Use timezone-aware UTC time
        "source": "email",
        "msg_id": msg_id, # Microsoft Graph message ID
        "channel": "email", # Store sender's email as the channel
        "thread_ts": "", # Not applicable for primary email usually
        "channel_id": "", # Not applicable for email
        "message_type": "received", # Indicate it's an incoming message
        "processed": False, # Mark as not yet processed by further logic
        "status": "pending" # Initial status
    }

    try:
        api_endpoint = f"{BASE_API_URL}/api/v1/messages/"
        logger.debug(f"Posting message to {api_endpoint} with payload: {payload}")
        resp = requests.post(api_endpoint, json=payload)

        if resp.status_code in (200, 201):
            response_data = resp.json()
            mid = response_data.get("mid") # Assuming your API returns the created message ID as 'mid'
            if mid:
                logger.info(f"Message saved to DB for msg_id {msg_id}. Received mid: {mid}")
                return mid
            else:
                logger.error(f"Message API response successful for {msg_id}, but 'mid' not found in response: {response_data}")
                return None
        else:
            logger.error(f"Failed to save message {msg_id} to DB: {resp.status_code} {resp.text}")
            # Optionally raise an error here depending on how critical this step is
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error posting message to DB for msg_id {msg_id}: {e}")
        return None
    except Exception as e: # Catch other potential errors (e.g., JSON decoding)
        logger.error(f"Unexpected error posting message to DB for msg_id {msg_id}: {e}", exc_info=True)
        return None


# ───Create Meetings in Meeting Table of DB ──────────────────────────────────────────────────────────────

def create_meeting_in_db(email, meeting_url, meeting_id, passcode, start_time, end_time, mid):
    """
    Create a meeting entry in the database with the given details.
    Requires the 'mid' (message ID from our DB) to link the meeting to the original email message.
    """
    if not mid:
        logger.error("Cannot create meeting in DB without a valid 'mid' (message ID).")
        return

    payload = {
        "mid": mid,
        "email": email, # Sender's email
        "meeting_url": meeting_url if meeting_url != "Not Found" else None, # Store null if not found
        "meeting_ID": meeting_id if meeting_id != "Not Found" else None,   # Store null if not found
        "passcode": passcode if passcode != "Not Found" else None,       # Store null if not found
        "start_time": start_time, # Should be extracted from calendar ideally, or default
        "end_time": end_time,     # Should be extracted from calendar ideally, or default
        # Add other relevant fields your Meeting model expects
    }

    try:
        api_endpoint = f"{BASE_API_URL}/api/v1/meetings/"
        logger.debug(f"Posting meeting to {api_endpoint} with payload: {payload}")
        resp = requests.post(api_endpoint, json=payload)
        if resp.status_code in (200, 201):
            logger.info(f"Meeting created/updated in DB linked to mid: {mid}")
        else:
            logger.error(f"Failed to create/update meeting in DB for mid {mid}: {resp.status_code} {resp.text}")
            # Optionally raise an error
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error posting meeting to DB for mid {mid}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error posting meeting to DB for mid {mid}: {e}", exc_info=True)


# ─── CELERY TASK ─────────────────────────────────────────────────────────────────

# Use a set for seen IDs within a single task run? Or rely on isRead flag?
# Using the isRead flag is generally more robust across worker restarts/multiple workers.
# Let's remove the seen_ids set for now and rely purely on fetching unread messages.

@celery_app.task(name="app.listeners.email_listener.poll_inbox_task") # Bind task to celery app
def poll_inbox_task():
    """
    Celery task to poll Microsoft Graph for unread emails, classify them,
    save them to the DB, potentially extract meeting details, and mark as read.
    This task should be run periodically (e.g., by Celery Beat).
    """
    logger.info("Starting email poll task...")
    try:
        token = get_access_token() # Get token at the start of the task run
        if not token:
            logger.error("Failed to get access token. Aborting poll task run.")
            return # Exit task if token fails

        headers = {"Authorization": f"Bearer {token}"}
        # Fetch only unread messages
        url = f"{GRAPH_API}/users/{USER_EMAIL}/mailFolders/inbox/messages?$filter=isRead eq false&$top=25" # Limit batch size with $top
        resp = requests.get(url, headers=headers)
        resp.raise_for_status() # Raise HTTPError for bad responses
        messages = resp.json().get('value', [])

        if not messages:
            logger.info("No unread messages found.")
            return # Exit task if no messages

        logger.info(f"Found {len(messages)} unread messages to process.")

        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                logger.warning("Found message with no ID, skipping.")
                continue

            # --- Extract Core Information ---
            try:
                sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "Unknown Address")
                username = msg.get("from", {}).get("emailAddress", {}).get("name", "Unknown Name")
                subject = msg.get("subject", "No Subject")
                body_preview = msg.get("bodyPreview", "")
                html_body = msg.get("body", {}).get("content", "") # Important: content might be None
                # conversation_id = msg.get("conversationId") # Uncomment if needed

                logger.info(f"Processing message ID: {msg_id} from {sender_email}, Subject: {subject}")

                # --- Save Initial Message to DB ---
                # Pass sender_email to potentially use it for linking user/project
                mid = create_message_in_db(username, subject, body_preview, msg_id, sender_email)
                if not mid:
                    logger.error(f"Failed to save initial message in DB for msg_id: {msg_id}. Skipping further processing for this email.")
                    # Decide whether to mark as read or retry later. Marking as read avoids infinite loops on DB errors.
                    # mark_email_as_read(token, msg_id) # Uncomment if you want to mark as read even if DB save fails
                    continue # Skip to next message

                # --- Classify Email ---
                classification = classify_email_with_llm(html_body or body_preview) # Pass preview if HTML is empty
                logger.info(f"Message ID: {msg_id} classified as: {classification}")

                # --- Process Based on Classification ---
                if classification == "meeting":
                    meeting_url, meeting_id, passcode = extract_meeting_details_bs(html_body)

                    # Basic check if details were found (improve robustness as needed)
                    if meeting_url != "Not Found" or meeting_id != "Not Found" or passcode != "Not Found":
                         logger.info(f"Extracted meeting details for msg_id {msg_id}: URL={meeting_url != 'Not Found'}, ID={meeting_id != 'Not Found'}, Passcode={passcode != 'Not Found'}")
                         # TODO: Get actual start/end times. Placeholder for now.
                         # This likely requires fetching the corresponding calendar event using msg['conversationId'] or subject/sender matching
                         # Using fetch_calendar_events and merge_meetings would be the way to go here.
                         start_time = datetime.now(timezone.utc).isoformat() # Placeholder
                         end_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat() # Placeholder

                         create_meeting_in_db(sender_email, meeting_url, meeting_id, passcode, start_time, end_time, mid)
                    else:
                        logger.warning(f"Classified as 'meeting' but failed to extract details for msg_id: {msg_id}")

                # --- Mark Email as Read (Important: Do this last) ---
                # Only mark as read if processing (including DB saving) was reasonably successful
                mark_email_as_read(token, msg_id)

            except Exception as inner_e:
                 # Catch errors processing a single message so the loop continues
                 logger.error(f"Error processing message ID {msg_id}: {inner_e}", exc_info=True)
                 # Consider whether to mark as read even on error to avoid retrying a poison message
                 # mark_email_as_read(token, msg_id)

        logger.info("Finished processing batch of emails.")

    except requests.exceptions.RequestException as e:
        # Handle errors fetching the list of messages
        logger.error(f"HTTP error during email poll: {e}", exc_info=True)
    except Exception as e:
        # Catch-all for other unexpected errors in the task
        logger.error(f"Unexpected error during email poll task: {e}", exc_info=True)

# Remove the __main__ block, Celery workers will run the task
# if __name__ == "__main__":
#     poll_inbox()
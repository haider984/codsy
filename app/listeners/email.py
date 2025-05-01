import os
import logging
# import asyncio # No longer needed for minimal task
import time # Import time for sync sleep
import requests
from datetime import datetime, timezone, timedelta
import re
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from bs4 import BeautifulSoup
from bson import ObjectId
import asyncio # <--- Import asyncio
from dotenv import load_dotenv

# --- Celery and Service Imports ---
from ..celery_app import celery_app
# --- Temporarily COMMENT OUT service and model imports ---
# from ..services.message import add_message
# from ..services.meeting import add_meeting
# from ..models.message import MessageCreate # Pydantic model for service
# from ..models.meeting import MeetingCreate, MeetingInDB # Pydantic model for service
# --- Temporarily COMMENT OUT other complex imports ---
# import requests
# from datetime import datetime, timezone, timedelta
# from langchain_groq import ChatGroq
# from langchain.prompts import PromptTemplate
# from bs4 import BeautifulSoup
# from bson import ObjectId


# ─── SETUP ─────────────────────────────────────────────────────────────────────

load_dotenv()

TENANT_ID     = os.getenv("TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_EMAIL    = os.getenv("USER_EMAIL", "agent.tom@codsy.ai")
BASE_API_URL  = os.getenv("BASE_API_URL", "http://localhost:8000")
GRAPH_API = "https://graph.microsoft.com/v1.0"
AUTH_URL  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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
    """
    soup = BeautifulSoup(html_body, "html.parser")
    
    # Default values if extraction fails
    meeting_url = "Not Found"
    meeting_id = "Not Found"
    passcode = "Not Found"
    
    # Attempt to find meeting details in the HTML body
    try:
        # Look for common patterns in meeting invitation emails
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(domain in href for domain in ['zoom.us', 'teams.microsoft.com', 'meet.google.com']):
                meeting_url = href
                break
                
        # Try to find meeting ID (common patterns)
        id_patterns = [
            r'Meeting ID:?\s*(\d[\d\s-]*\d)', 
            r'ID:\s*(\d[\d\s-]*\d)',
            r'meeting number:?\s*(\d[\d\s-]*\d)'
        ]
        
        for pattern in id_patterns:
            matches = re.search(pattern, html_body, re.IGNORECASE)
            if matches:
                meeting_id = matches.group(1).strip()
                break
                
        # Try to find passcode (common patterns)
        passcode_patterns = [
            r'Passcode:?\s*([a-zA-Z0-9]+)',
            r'Password:?\s*([a-zA-Z0-9]+)',
            r'Access code:?\s*([a-zA-Z0-9]+)'
        ]
        
        for pattern in passcode_patterns:
            matches = re.search(pattern, html_body, re.IGNORECASE)
            if matches:
                passcode = matches.group(1).strip()
                break
                
    except Exception as e:
        logger.warning(f"Error extracting meeting details: {str(e)}")
        
    if html_body is None or html_body.strip() == "":
        logger.warning("Received empty HTML body for meeting detail extraction.")
        
    return meeting_url, meeting_id, passcode

# ─── Classify Email with LLM ────────────────────────────────────────────────────

def classify_email_with_llm(email_content):
    """
    Use LLM to classify email as 'meeting', 'general', etc.
    """
    try:
        # Initialize Groq LLM client
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            logger.warning("GROQ_API_KEY not set, using generic classification")
            # Basic classification fallback
            if any(term in email_content.lower() for term in ["meeting", "zoom", "teams", "google meet", "calendar"]):
                return "meeting"
            return "general"
            
        # Set up LLM with Groq
        llm = ChatGroq(
            model_name="llama3-8b-8192",
            groq_api_key=groq_api_key,
            temperature=0
        )
        
        # Create prompt for classification
        template = """
        Classify the following email content into exactly ONE of these categories:
        - meeting (if it contains meeting details, calendar invites, or video calls)
        - general (for normal correspondence, questions, updates)
        
        Email content:
        {email_content}
        
        Classification (respond with ONLY 'meeting' or 'general'):
        """
        
        prompt = PromptTemplate(
            template=template,
            input_variables=["email_content"]
        )
        
        # Get response from LLM
        response = llm.invoke(prompt.format(email_content=email_content[:4000]))  # Limit content length
        
        # Extract classification
        response_text = response.content.lower().strip()
        if "meeting" in response_text:
            return "meeting"
        else:
            return "general"
            
    except Exception as e:
        logger.error(f"Error classifying email: {str(e)}")
        return "general"  # Default fallback

# ─── Database Functions ─────────────────────────────────────────────────────────

async def create_message_in_db(username, subject, body_preview, msg_id, sender_email):
    """Create a message record in the database"""
    try:
        # Using API endpoint to save message
        payload = {
            "username": username,
            "subject": subject,
            "content": body_preview,
            "external_id": msg_id,
            "email": sender_email
        }
        
        # Make request to internal API
        response = requests.post(f"{BASE_API_URL}/api/messages/", json=payload)
        
        if response.status_code in (200, 201):
            result = response.json()
            logger.info(f"Message saved to database with ID: {result.get('id')}")
            return result.get('id')
        else:
            logger.error(f"Failed to save message: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating message in DB: {str(e)}")
        return None

async def create_meeting_in_db(sender_email, meeting_url, meeting_id, passcode, start_time, end_time, message_id):
    """Create a meeting record in the database"""
    try:
        # Using API endpoint to save meeting
        payload = {
            "email": sender_email,
            "meeting_url": meeting_url,
            "meeting_id": meeting_id,
            "passcode": passcode,
            "start_time": start_time,
            "end_time": end_time,
            "message_id": str(message_id)
        }
        
        # Make request to internal API
        response = requests.post(f"{BASE_API_URL}/api/meetings/", json=payload)
        
        if response.status_code in (200, 201):
            result = response.json()
            logger.info(f"Meeting saved to database with ID: {result.get('id')}")
            return result.get('id')
        else:
            logger.error(f"Failed to save meeting: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating meeting in DB: {str(e)}")
        return None

# ─── Celery Task Definition (SYNC) ────────────────────────────────────────────

@celery_app.task(name="app.listeners.email.poll_inbox_task", bind=True)
def poll_inbox_task(self):
    """
    SYNC Celery task to poll Microsoft Graph. Uses asyncio.run() for async DB calls.
    """
    print("***** SYNC Task poll_inbox_task ENTERED *****", flush=True)
    logger = logging.getLogger(__name__)
    if not logger.handlers:
         handler = logging.StreamHandler()
         formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
         handler.setFormatter(formatter)
         logger.addHandler(handler)
         logger.setLevel(logging.INFO)

    logger.info("========== Starting SYNC task run... ==========")
    logger.info(f"Checking environment variables: TENANT_ID={'Set' if os.getenv('TENANT_ID') else 'Not Set'}, CLIENT_ID={'Set' if os.getenv('CLIENT_ID') else 'Not Set'}, CLIENT_SECRET={'Set' if os.getenv('CLIENT_SECRET') else 'Not Set'}, USER_EMAIL={os.getenv('USER_EMAIL')}, GROQ_API_KEY={'Set' if os.getenv('GROQ_API_KEY') else 'Not Set'}")

    try:
        # Get access token directly inside the task
        now = datetime.now(timezone.utc)
        logger.info("Obtaining Microsoft Graph access token...")
        
        resp = requests.post(AUTH_URL, data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        })
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        logger.info("Successfully obtained access token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH_API}/users/{USER_EMAIL}/mailFolders/inbox/messages?$filter=isRead eq false&$top=25"
        logger.debug(f"Fetching unread emails from: {url}")
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        messages = resp.json().get('value', [])

        if not messages:
            logger.info("No unread messages found in this run.")
            return

        logger.info(f"Found {len(messages)} unread messages to process.")

        for i, msg in enumerate(messages):
            msg_id = msg.get("id") # External MS Graph ID
            logger.info(f"--- Processing message {i+1}/{len(messages)} (external msg_id: {msg_id}) ---")
            if not msg_id:
                logger.warning("Found message with no external ID, skipping.")
                continue

            try:
                sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "Unknown")
                username = msg.get("from", {}).get("emailAddress", {}).get("name", "Unknown")
                subject = msg.get("subject", "")
                body_preview = msg.get("bodyPreview", "")
                html_body = msg.get("body", {}).get("content", "")

                logger.info(f"Extracted info for external msg_id: {msg_id} from {sender_email}")

                # --- Call the async DB function for Message ---
                logger.info(f"Attempting to save initial message to DB for external msg_id: {msg_id}")
                mid = asyncio.run(create_message_in_db(username, subject, body_preview, msg_id, sender_email))
                if not mid:
                    logger.error(f"Failed to create message entry for external msg_id: {msg_id}. Skipping rest of processing for this email.")
                    continue # Skip to the next email

                logger.info(f"Message entry CREATED for external msg_id: {msg_id}. Internal mid: {mid}")

                # --- Classification (Sync) ---
                logger.info(f"Classifying email for internal mid: {mid} (external: {msg_id})")
                classification = classify_email_with_llm(html_body or body_preview)
                logger.info(f"Email classified as '{classification}' for internal mid: {mid}")

                # --- Meeting Processing ---
                if classification == "meeting":
                    logger.info(f"Extracting meeting details for internal mid: {mid}")
                    meeting_url, meeting_id, passcode = extract_meeting_details_bs(html_body)

                    if meeting_url != "Not Found" or meeting_id != "Not Found" or passcode != "Not Found":
                        logger.info(f"Extracted meeting details found for internal mid: {mid}. Attempting to save meeting.")
                        start_time_iso = datetime.now(timezone.utc).isoformat() # Placeholder
                        end_time_iso = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat() # Placeholder

                        # --- Call the async DB function for Meeting ---
                        asyncio.run(create_meeting_in_db(sender_email, meeting_url, meeting_id, passcode, start_time_iso, end_time_iso, mid))
                    else:
                        logger.warning(f"Email classified as 'meeting' but no details extracted for internal mid: {mid}")

                # --- Mark as Read (Sync) ---
                logger.info(f"Attempting to mark email as read for external msg_id: {msg_id}")
                mark_email_as_read(token, msg_id)

            except Exception as inner_e:
                 logger.error(f"Unhandled exception processing external msg_id {msg_id}: {inner_e}", exc_info=True)

        logger.info(f"--- Finished processing {len(messages)} message(s). ---")

    except ValueError as ve:
         logger.error(f"Task failed due to Value Error (likely missing credentials): {ve}")
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error during email poll request: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error during email poll task run: {e}", exc_info=True)
    finally:
        logger.info("========== Finished SYNC task run. ==========")
        print("***** SYNC Task poll_inbox_task EXITED *****", flush=True)

    # Task implicitly returns None when ignore_result=True

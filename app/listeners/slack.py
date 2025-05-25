import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_sdk import WebClient
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from datetime import datetime, timezone, timedelta
from app.celery_app import celery_app
from groq import Groq
import json
import asyncio


# ——— CONFIGURATION ———
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback

# ——— LOGGER + SLACK INIT ———
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)

client = WebClient(token=SLACK_BOT_TOKEN)
# Don't initialize Groq client globally - we'll create per-user instances

# ─── PERMISSION CHECK HELPER ───────────────────────────────────────────────────
def check_user_permission(email: str, base_api_url: str) -> bool:
    """Checks if a user is allowed by querying the agent_users status endpoint."""
    if not email or email == "Unknown" or "@" not in email: # Basic email validity check
        logger.warning(f"Permission check: No valid email provided ('{email}'). Denying permission.")
        return False
    if not base_api_url: # Check if BASE_API_URL is configured
        logger.error("Permission check: BASE_API_URL not configured. Denying permission.")
        return False
    try:
        response = requests.get(f"{base_api_url}/api/v1/agent_users/status/email/{email}", timeout=10)
        if response.status_code == 200:
            status = response.json()
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
def get_groq_api_key(sender_email):
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/agent_users/groq/{sender_email}", timeout=10)

        if response.status_code == 200:
            data = response.json()
            api_key = data.get("id")
            if api_key:
                return api_key
            else:
                logger.error(f"No API key found in response for {sender_email}")
                return None
        else:
            logger.error(f"Failed to get API key for {sender_email}, status code: {response.status_code}")
            return None

    except Exception as e:
        logger.exception(f"Exception occurred while fetching Groq API key for {sender_email}: {e}")
        return None

class ContextAwareSlackHandler:
    def __init__(self):
        self.history_window = timedelta(hours=48)  # Look back 48 hours for context
        self.groq_clients = {}  # Cache of Groq clients by user email

    def get_groq_client(self, email: str):
        """
        Get a Groq client for the specified user email.
        Uses cached client if available, otherwise creates a new one.
        Falls back to environment variable if user key not available.
        """
        # Return cached client if available
        if email in self.groq_clients:
            return self.groq_clients[email]
            
        # Get API key for this user
        api_key = get_groq_api_key(email)
        
        # If user is not allowed or no key available, fall back to environment variable
        if not api_key:
            if GROQ_API_KEY:
                api_key = GROQ_API_KEY
                logger.warning(f"Using fallback GROQ API key for {email}")
            else:
                logger.error(f"No GROQ API key available for {email} and no fallback configured")
                return None
                
        # Create and cache the client
        try:
            client = Groq(api_key=api_key)
            self.groq_clients[email] = client
            return client
        except Exception as e:
            logger.error(f"Failed to create Groq client for {email}: {e}")
            return None

    def get_message_history(self, channel_id, user=None, limit=10):
        """
        Retrieve message history from the database
        Optionally filter by user and limit the number of records
        """
        try:
            params = {}
            if user:
                params["username"] = user
            if channel_id:
                params["channel_id"] = channel_id
                
            response = requests.get(f"{BASE_API_URL}/api/v1/messages/", params=params)
            response.raise_for_status()
            
            # Sort messages by datetime
            messages = response.json()
            messages.sort(key=lambda x: x.get("message_datetime", ""))
            
            # Return the most recent messages up to the limit
            return messages[-limit:] if limit else messages
        except Exception as e:
            logger.error(f"Error fetching message history: {e}")
            return []

    def extract_information_with_llm(self, message_history, current_message):
        """
        Use LLM to extract git repository, branch names, and other contextual information
        from message history
        """
        # Get user email from the current message
        email = current_message.get("user_email_for_context", current_message.get("username", ""))
        
        # Get Groq client for this user
        client = self.get_groq_client(email)
        if not client:
            logger.warning(f"No Groq client available for {email}. Skipping LLM information extraction.")
            return {
                "repo_names": [], "branch_names": [], "project_names": [], "file_paths": [],
                "languages": [], "current_action": {"action_type": "unknown", "target": "", "description": ""},
                "is_followup": False, "requires_context": False
            }
            
        try:
            # Format history for information extraction
            conversation_history = []
            for msg in message_history:
                username = msg.get("username", "User")
                content = msg.get("content", "")
                reply = msg.get("reply", "")
                
                if content:
                    conversation_history.append(f"User ({username}): {content}")
                if reply and reply not in [None, "", "null"]:
                    conversation_history.append(f"Assistant: {reply}")
            
            # Add current message
            current_content = current_message.get("content", "")
            current_username = current_message.get("username", "User")
            conversation_history.append(f"User ({current_username}): {current_content}")
            
            system_prompt = """
            You are an information extraction assistant specialized in technical conversations.
            Your task is to extract specific information from a conversation history.
            
            Extract the following information:
            1. Git repository names
            2. Git branch names  
            3. Project names or IDs
            4. File paths or directories mentioned
            5. Programming languages or frameworks mentioned
            6. Task or action requests
            
            Provide a JSON response with the following fields:
            {
                "repo_names": [list of repository names],
                "branch_names": [list of branch names],
                "project_names": [list of project names],
                "file_paths": [list of file paths],
                "languages": [list of programming languages],
                "current_action": {
                    "action_type": "create"|"update"|"delete"|"push"|"pull"|"merge"|"other",
                    "target": "what the action applies to",
                    "description": "brief description of the requested action"
                },
                "is_followup": true/false (is the current message a follow-up to previous conversation?),
                "requires_context": true/false (does the current message require context to be fully understood?)
            }
            
            Guidelines:
            - Only include information explicitly mentioned in the conversation
            - If a repository is referred to in the latest message using "it" or "this repo", include that repo name
            - For action requests like "push this", determine what "this" refers to from context
            - Return empty arrays for fields where no information was found
            - Pay special attention to the MOST RECENT messages for context
            - only extract one name per field and it should be the most latest one. Do not combine names extract as it is.
            """
            
            user_prompt = f"""
            Conversation history:
            {chr(10).join([f"{i+1}. {msg}" for i, msg in enumerate(conversation_history)])}
            
            Extract all relevant information from this conversation, with special focus on the last message.
            """
            
            # Use the user-specific client
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temperature for more deterministic response
                response_format={"type": "json_object"},
                max_tokens=800
            )
            
            # Parse the JSON response
            extraction_result = json.loads(response.choices[0].message.content)
            logger.info(f"Information extraction result: {extraction_result}")
            
            return extraction_result
        except Exception as e:
            logger.error(f"Information extraction failed: {e}")
            # Default response if extraction fails
            return {
                "repo_names": [],
                "branch_names": [],
                "project_names": [],
                "file_paths": [],
                "languages": [],
                "current_action": {
                    "action_type": "unknown",
                    "target": "",
                    "description": ""
                },
                "is_followup": False,
                "requires_context": False
            }

    def analyze_message_context(self, current_message, history):
        """
        Analyze the current message to determine:
        1. If it's a follow-up to previous conversation
        2. If it needs context enhancement
        3. What specific context should be included
        """
        # Get user email from the current message
        email = current_message.get("user_email_for_context", current_message.get("username", ""))
        
        # Get Groq client for this user
        client = self.get_groq_client(email)
        if not client:
            logger.warning(f"No Groq client available for {email}. Skipping LLM context analysis.")
            return {
                "is_followup": False, "needs_context": False, "context_quality": 0.0,
                "relevant_context": [], "rewrite_suggestion": None, "extracted_info": {}
            }
        if not history:
            return {
                "is_followup": False,
                "needs_context": False,
                "context_quality": 0.0,
                "relevant_context": [],
                "rewrite_suggestion": None,
                "extracted_info": {}
            }
            
        try:
            # Extract information from message history using LLM
            extracted_info = self.extract_information_with_llm(history, current_message)
            
            # Determine if this is a follow-up based on the extraction result
            is_followup = extracted_info.get("is_followup", False)
            needs_context = extracted_info.get("requires_context", False)
            
            # Create a prompt for the LLM to analyze context
            current_content = current_message.get("content", "")
            current_username = current_message.get("username", "User")
            
            # Format history for context analysis
            conversation_history = []
            for msg in history:
                username = msg.get("username", "User")
                content = msg.get("content", "")
                reply = msg.get("reply", "")
                
                if content:
                    conversation_history.append(f"User ({username}): {content}")
                if reply and reply not in [None, "", "null"]:
                    conversation_history.append(f"Assistant: {reply}")
            
            # Format extracted information for the context analysis
            extracted_info_formatted = "\n".join([
                f"Repository Names: {', '.join(extracted_info.get('repo_names', []))}",
                f"Branch Names: {', '.join(extracted_info.get('branch_names', []))}",
                f"Project Names: {', '.join(extracted_info.get('project_names', []))}",
                f"File Paths: {', '.join(extracted_info.get('file_paths', []))}",
                f"Languages/Frameworks: {', '.join(extracted_info.get('languages', []))}"
            ])
            
            # Information about the current action
            current_action = extracted_info.get('current_action', {})
            action_formatted = f"Current Action: {current_action.get('action_type', 'unknown')} - {current_action.get('description', '')}"
            
            system_prompt = f"""
            You are a context analysis assistant. Your task is to analyze the current message 
            and determine if it requires previous conversation context to be fully understood.
            
            Based on the conversation, I've extracted the following information:
            {extracted_info_formatted}
            {action_formatted}
            
            Provide a JSON response with the following fields:
            - is_followup: boolean (true if this message is continuing a previous conversation)
            - needs_context: boolean (true if this message needs additional context to be properly understood)
            - context_quality: float (0.0-1.0 score indicating how much this message depends on previous context)
            - relevant_context: array of integers (indices of relevant messages from the history, starting from 0)
            - rewrite_suggestion: string (a suggested rewrite of the query that includes missing context to make it self-contained)
            
            For the rewrite_suggestion, if the message involves:
            1. Creating/modifying files: Include what file types, contents, and where they should be saved
            2. Git operations: Include the repository name, branch, and what should be committed/pushed
            3. Web/API requests: Include the full URLs, endpoints, and what data should be sent/retrieved
            
            The rewrite should be detailed enough that someone without conversation context could understand exactly what to do.
            """
            
            user_prompt = f"""
            Current message: "{current_content}"
            
            Previous conversation history (in chronological order):
            {chr(10).join([f"{i+1}. {msg}" for i, msg in enumerate(conversation_history[-10:])])}
            
            Analyze if the current message needs context from previous messages to be fully understood.
            If it does, provide a comprehensive rewrite that includes all necessary context.
            """
            
            # Use the user-specific client for both extraction and analysis
            extracted_info = self.extract_information_with_llm(history, current_message)
            
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temperature for more deterministic response
                response_format={"type": "json_object"},
                max_tokens=600
            )
            
            # Parse the JSON response
            analysis = json.loads(response.choices[0].message.content)
            
            # Add extracted information to the analysis
            analysis["extracted_info"] = extracted_info
            
            logger.info(f"Context analysis result: {analysis}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Context analysis failed: {e}")
            # Default response if analysis fails
            return {
                "is_followup": False,
                "needs_context": False,
                "context_quality": 0.0,
                "relevant_context": [],
                "rewrite_suggestion": None,
                "extracted_info": {}
            }

    def enhance_message_with_context(self, message, history, analysis):
        """
        If the message needs context enhancement, modify it to include necessary context
        """
        if not analysis.get("needs_context", False):
            return message
            
        try:
            # Get the original content
            original_content = message.get("content", "")
            
            # If there's a rewrite suggestion, use it
            if analysis.get("rewrite_suggestion"):
                enhanced_content = analysis["rewrite_suggestion"]
                
                # Create an enhanced message object
                enhanced_message = message.copy()
                enhanced_message["original_content"] = original_content
                enhanced_message["content"] = enhanced_content
                enhanced_message["context_enhanced"] = True
                enhanced_message["context_quality"] = analysis.get("context_quality", 0.0)
                enhanced_message["extracted_info"] = analysis.get("extracted_info", {})
                
                logger.info(f"Enhanced message: '{original_content}' -> '{enhanced_content}'")
                return enhanced_message
                
            return message
        except Exception as e:
            logger.error(f"Error enhancing message with context: {e}")
            return message

    def generate_llm_response(self, message, message_history, analysis):
        """
        Generate a response using the Groq LLM based on message and history
        Intelligently include relevant context based on analysis
        """
        # Get user email from the message
        email = message.get("user_email_for_context", message.get("username", ""))
        
        # Get Groq client for this user
        client = self.get_groq_client(email)
        if not client:
            logger.warning(f"No Groq client available for {email}. Skipping LLM response generation.")
            return "I am currently unable to process your request due to an API configuration issue. Please contact support."
        try:
            # Get extracted information
            extracted_info = analysis.get("extracted_info", {})
            
            # Format extracted information for the system prompt
            if extracted_info:
                # Format git info
                repo_info = f"Repository: {', '.join(extracted_info.get('repo_names', []))}" if extracted_info.get('repo_names') else ""
                branch_info = f"Branch: {', '.join(extracted_info.get('branch_names', []))}" if extracted_info.get('branch_names') else ""
                project_info = f"Project: {', '.join(extracted_info.get('project_names', []))}" if extracted_info.get('project_names') else ""
                
                # Format current action
                current_action = extracted_info.get('current_action', {})
                action_info = ""
                if current_action and current_action.get('action_type') != 'unknown':
                    action_info = f"Current Action: {current_action.get('action_type')} {current_action.get('target')} - {current_action.get('description')}"
                
                # Combine context information
                context_info = "\n".join(filter(None, [repo_info, branch_info, project_info, action_info]))
            else:
                context_info = ""
            
            system_prompt = f"""
            You are Agent Lisa, a helpful technical assistant integrated with a Slack workspace.
            
            IMPORTANT INSTRUCTIONS:
            1. Always maintain context between messages and reference specific details from previous exchanges.
            2. When responding to requests about creating or modifying resources (like GitHub repos, Jira projects, etc.):
               - Use the SAME NAMES for related resources unless explicitly told otherwise
               - If a user created a GitHub repo called "ailet", create Jira projects with the same name "ailet"
               - Extract and reuse specific resource names mentioned in previous messages
            3. Be direct and action-oriented in your responses. Act as if you have already completed the requested tasks.
            4. For resource creation responses, always include:
               - The exact resource name (repo name, project name, etc.)
               - A fictitious but realistic access URL
            5. Your responses should be concise (2-3 sentences) and focused.
            6. Never say you "would" do something or that you "can" do something - just do it and report completion.
            
            CURRENT CONTEXT INFORMATION:
            {context_info}
            
            Remember: You are NOT a conversational assistant - you are a technical agent that completes tasks.
            """

            formatted_messages = [{"role": "system", "content": system_prompt}]
            
            # Include relevant conversation history for context
            if analysis.get("is_followup", False) or analysis.get("needs_context", False):
                # Get indices of relevant messages or use the last 5 if none specified
                relevant_indices = analysis.get("relevant_context", [])
                if not relevant_indices:
                    relevant_indices = list(range(max(0, len(message_history) - 5), len(message_history)))
                
                # Add only the relevant messages from history
                for idx in sorted(relevant_indices):
                    if 0 <= idx < len(message_history):
                        msg = message_history[idx]
                        username = msg.get("username", "User")
                        content = msg.get("content", "")
                        
                        if content:
                            formatted_messages.append({"role": "user", "content": f"{username}: {content}"})
                        
                        reply = msg.get("reply")
                        if reply and reply not in [None, "", "null"]:
                            formatted_messages.append({"role": "assistant", "content": reply})
            
            # Add the current message
            current_content = message.get("content", "")
            current_username = message.get("username", "User")
            
            # If this is a contextually enhanced message, make it clear to the LLM
            if message.get("context_enhanced", False):
                user_message = f"""
                {current_username}: {current_content}
                
                [Note: This message has been automatically enhanced with context from previous conversation]
                """
                formatted_messages.append({"role": "user", "content": user_message})
            else:
                formatted_messages.append({"role": "user", "content": f"{current_username}: {current_content}"})

            # Use the user-specific client
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=formatted_messages,
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"I'm sorry, I couldn't process your request at the moment. Please try again later."

    def update_message_with_reply(self, mid, message):
        """
        Update a message in the database with the generated reply and any context enhancements
        """
        try:
            # Include any enhanced content flags and extracted information
            context_metadata = {}
            if message.get("context_enhanced", False):
                context_metadata = {
                    "original_content": message.get("original_content", ""),
                    "context_enhanced": True,
                    "context_quality": message.get("context_quality", 0.0)
                }
            
            # Add extracted information to metadata
            if message.get("extracted_info"):
                if not context_metadata:
                    context_metadata = {}
                context_metadata["extracted_info"] = message.get("extracted_info")
            
            payload = {
                "content": message.get("content", ""),
                "reply": message.get("reply", ""),
                "message_type": message.get("message_type", "user_message"),
                "processed": False,
                "status": "pending",
                "username": message.get("username", ""),
                "message_datetime": message.get("message_datetime", datetime.now(timezone.utc).isoformat()),
                "sid": message.get("sid", ""),
                "uid": message.get("uid", ""),
                "pid": message.get("pid", ""),
                "source": message.get("source", "slack"),
                "msg_id": message.get("msg_id", ""),
                "channel": message.get("channel", "slack"),
                "channel_id": message.get("channel_id", ""),
                "thread_ts": message.get("thread_ts", ""),
                "metadata": context_metadata if context_metadata else message.get("metadata", {})
            }

            response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=payload)
            if response.status_code == 200:
                logger.info(f"Updated message {mid} with reply and context data")
                return True
            else:
                logger.error(f"Update failed: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False
            
    def process_new_message(self, message):
        """
        Process a new message with context awareness:
        1. Analyze if message needs context
        2. Enhance message with context if needed
        3. Generate a response using the enhanced message
        4. Update the database with the enhanced message and reply
        """
        mid = message.get("mid")
        if not mid:
            logger.warning("Message missing 'mid', skipping")
            return False
            
        channel_id = message.get("channel_id")
        username = message.get("username")
        
        # Get conversation history-
        history = self.get_message_history(channel_id=channel_id, user=username, limit=10)
        
        # Analyze message context using LLM
        context_analysis = self.analyze_message_context(message, history)
        
        # Enhance message with context if needed
        enhanced_message = self.enhance_message_with_context(message, history, context_analysis)
        
        # Generate response
        reply = self.generate_llm_response(enhanced_message, history, context_analysis)
        
        # Update the enhanced message with the reply
        enhanced_message["reply"] = reply
        
        # Update message in database with enhanced content and reply
        success = self.update_message_with_reply(mid, enhanced_message)
        
        return success

# Create a global instance of the handler
slack_handler = ContextAwareSlackHandler()

def create_message_in_db(username, text, msg_ts, channel_id, user_email_for_context=""):
    """
    Create a new message in the database.
    The user_email_for_context is not directly saved but used for context if needed by process_new_message.
    """
    sid = "680f69cc5c250a63d068bbec"  # Static for now
    uid = "680f69605c250a63d068bbeb"
    if user_email_for_context:
        try:
            response = requests.get(f"{BASE_API_URL}/api/v1/agent_users/{user_email_for_context}", timeout=10)

            if response.status_code == 200:
                uid = response.json()["id"]
            else:
                print(f"Warning: Failed to fetch UID for email {user_email_for_context}: {response.status_code}")
        except Exception as e:
            print(f"Error fetching UID for email {user_email_for_context}: {e}")

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
        "message_type": "user_message",
        "processed": False,
        "status": "pending",
        "user_email_for_context": user_email_for_context
    }

    try:
        resp = requests.post(f"{BASE_API_URL}/api/v1/messages/", json=payload)
        if resp.status_code in (200, 201):
            logger.info(f"Message saved to DB: {msg_ts}")
            # Get the message ID from the response
            message_id = resp.json().get("mid") if resp.headers.get("content-type") == "application/json" else resp.text
            
            # Create the message object with the returned ID
            message = payload.copy()
            message["mid"] = message_id
            
            # Process the message with context awareness
            slack_handler.process_new_message(message)
            return message_id
        else:
            logger.error(f"Failed to save message {msg_ts}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Error posting message to DB: {e}")
        return None

@app.event("message")
def handle_message_events(event, say):
    user_id = event.get("user") # Renamed from 'user' to 'user_id' for clarity
    text = event.get("text", "").strip()
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if subtype or not user_id or not text:
        return

    if channel_type in ("im", "mpim"):  # Direct Message
        try:
            user_info_response = app.client.users_info(user=user_id)
            user_profile = user_info_response["user"]["profile"]
            username = user_profile.get("real_name") or user_profile.get("display_name") or user_id
            email = user_profile.get("email")

            if not email:
                logger.warning(f"Could not retrieve email for user {username} ({user_id}). Cannot check permissions.")
                say("I couldn't verify your permissions because your email is not available. Please check your Slack profile.")
                return

            logger.info(f"DM from {username} ({email}): {text}")

            # === PERMISSION CHECK ===
            if not check_user_permission(email, BASE_API_URL):
                logger.warning(f"User {username} ({email}) is not allowed for DM interaction.")

                say("Sorry, you are not authorized to use this feature.")
                return

            # Save message to DB and process with context awareness
            create_message_in_db(username, text, ts, channel_id, user_email_for_context=email)
        except Exception as e:
            logger.error(f"Error in handle_message_events for user {user_id}: {e}", exc_info=True)
            say("Sorry, an error occurred while processing your message.")

@app.event("app_mention")
def handle_app_mention(event, say):
    user_id = event.get("user") # Renamed from 'user' to 'user_id' for clarity
    text = event.get("text", "")
    channel_id = event.get("channel")
    ts = event.get("ts")

    if not user_id or not text:
        return

    try:
        # Get user info
        user_info_response = app.client.users_info(user=user_id)
        user_profile = user_info_response["user"]["profile"]
        username = user_profile.get("real_name") or user_profile.get("display_name") or user_id
        email = user_profile.get("email")

        if not email:
            logger.warning(f"Could not retrieve email for user {username} ({user_id}) in app_mention. Cannot check permissions.")
            say("I couldn't verify your permissions because your email is not available. Please check your Slack profile or contact an admin.")
            return

        bot_id_response = app.client.auth_test()
        bot_id = bot_id_response["user_id"]
        mention = f"<@{bot_id}>"
        stripped_text = text.replace(mention, "").strip()

        logger.info(f"Mention by {username} ({email}): {stripped_text}")

        # === PERMISSION CHECK ===
        if not check_user_permission(email, BASE_API_URL):
            logger.warning(f"User {username} ({email}) is not allowed for app_mention interaction.")
            say("Sorry, you are not authorized to use this feature.")
            return

        # Save message to DB and process with context awareness
        create_message_in_db(username, stripped_text or text, ts, channel_id, user_email_for_context=email)
    except Exception as e:
        logger.error(f"Error in handle_app_mention for user {user_id}: {e}", exc_info=True)
        say("Sorry, an error occurred while processing your mention.")

@celery_app.task(name='app.listeners.slack.process_pending_messages')
def process_pending_messages():
    """
    Celery task to process any pending messages in the database
    """
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/messages/?status=pending")
        if response.status_code == 200:
            pending_messages = response.json()
            logger.info(f"Found {len(pending_messages)} pending messages to process")
            
            for message in pending_messages:
                slack_handler.process_new_message(message)
    except Exception as e:
        logger.error(f"Error processing pending messages: {e}")

@celery_app.task(name='app.listeners.slack.run_slack_listener')
def run_slack_listener():
    """
    Celery task to start the Slack socket mode handler.
    This is a long-running task that will block until the connection is closed.
    """
    logger.info("Starting Context-Aware Slack Listener Bot from Celery task...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
    # This is a blocking call - the task will remain active as long as the socket connection is open

# ——— ENTRY POINT ———
if __name__ == "__main__":
    logger.info("Starting Context-Aware Slack Listener Bot directly...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
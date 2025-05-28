
import os
import requests
import logging
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timezone
import json

# Load environment
load_dotenv()
openai_api_key = os.getenv("TASK_ANALYZER_OPENAI_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")

client = OpenAI(api_key=openai_api_key)
logger = logging.getLogger("TaskAnalyzer")

def fetch_message(mid):
    try:
        response = requests.get(f"{BASE_API_URL}/api/v1/messages/{mid}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch message: {e}")
        return None

def analyze_tasks_with_llm(content):
    prompt = f"""
You are a task analyzer. IMPORTANT: Given message content, extract each GITHUB and JIRA related task and decide whether each task belongs in GitHub or Jira.
IMPORTANT: Analyze the message content completely and see if there is any task that can be extracted.
IMPORTANT: ALWAYS make sure that no github and jira related task is left behind and that you are not missing any task even. 

Required JSON format:
[
  {{
    "title": "Short task title",
    "description": "Detailed task description",
    "platform": "jira" or "git"
  }}
]
IMPORTANT: ALWAYS make sure to include github repository name both in title and description for git platform
IMPORTANT: ALWAYS make sure to include project key and project name in capital letters for jira platform
Example Input:
now create a 1 mobile shop website page frontend in html and CSS for selling mobile in sellingmobile.html and push it to us repository
Example Output (JSON):
[
  {{
    "title": "Create mobile shop website page in github repository named us",
    "description": "Create a mobile shop website page frontend in HTML and CSS for selling mobiles in github repository named us. The file should be named 'sellingmobile.html'",
    "platform": "git"
  }}
  {{
    "title": "Push mobile shop page to GitHub repository named us",
    "description": "Commit and push the completed mobile shop page to the GitHub repository named us.",
    "platform": "git"
  }}
Example Input:
I've got a new project I want you to start — it's called DevTrack8. It's a single-page HTML dashboard meant to mock up a simple developer task tracker. Here's what I need:
- First of all give me list of all jira projects and github repositories
- Create a public GitHub repo called devtrack8-dashboard
- Create a Jira project called DEVTRACK8
- Add a ticket for yourself to implement the first version of the dashboard
- The dashboard should be a single HTML file. Include:
  - A header that says "DevTrack8"
  - A search bar at the top to filter tasks
  - A list of 4–5 hardcoded tasks, each with:
    - Title
    - Status (To Do / In Progress / Done)
    - Optional tag (e.g. "Frontend", "Bug", "Low Priority")
  - Basic responsive styling to make it look like a mini web app
  - Tasks can be represented using HTML and styled with CSS — no real interactivity is needed right now
- Push the result to the GitHub repo when you're done.
Example Output (JSON):
[
  {{
    "title": "list github repositories",
    "description": "List github repositories",
    "platform": "git"
  }},
  {{
    "title": "list jira projects",
    "description": "List jira projects",
    "platform": "jira"
  }},
  {{
    "title": "Create GitHub repository for DevTrack8",
    "description": "Set up a public GitHub repository named 'devtrack8-dashboard' to host the code for the DevTrack8 dashboard project.",
    "platform": "git"
  }},
  {{
    "title": "Set up Jira project named DEVTRACK8",
    "description": "Create a new Jira project named DEVTRACK8 to track tasks related to the DevTrack8 dashboard.",
    "platform": "jira"
  }},
  {{
    "title": "Add initial ticket to Jira for dashboard implementation in jira project named DEVTRACK8",
    "description": "Create a Jira ticket for implementing the first version of the dashboard as a single HTML file.",
    "platform": "jira"
  }},
  {{
    "title": "Implement basic DevTrack8 dashboard in HTML in github repository named devtrack8-dashboard",
    "description": "Create a single HTML file index.html with a header ('DevTrack8'), a search bar to filter tasks, and a list of 4–5 hardcoded tasks with title, status, and optional tags. Apply basic responsive styling to resemble a web app. Commit and push the completed HTML dashboard to the 'devtrack8-dashboard' repository.",
    "platform": "git"
  }},
  {{
    "title": "Push HTML dashboard to GitHub repository named devtrack8-dashboard",
    "description": "Commit and push the completed HTML dashboard to the 'devtrack8-dashboard' repository.",
    "platform": "git"
  }}
]
Now, read the following message and ALWAYS return a list of tasks as JSON.
Content:
\"\"\"
{content}
\"\"\"
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        output = response.choices[0].message.content.strip()
        logger.debug(f"Raw LLM response: {output}")
        # Clean up JSON response
        if output.startswith("```json"):
            output = output[7:]  # Remove ```json
        if output.endswith("```"):
            output = output[:-3]  # Remove ```

        return json.loads(output)   # Safer: use `json.loads()` if model output is guaranteed JSON
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM output: {e}")
        return []
    except Exception as e:
        logger.error(f"Task analysis failed: {e}")
        return []
from datetime import datetime, timezone

def post_task(task, mid):
    task["mid"] = mid
    task["reply"] = ""
    task["status"] = "pending"
    
    # Adjust creation_date to match the required format (without 'Z' or extra characters)
    task["creation_date"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()  # No 'Z' added
    
    # Set completion_date to None if not provided
    task["completion_date"] = None  # Ensure this is either None or a valid datetime
    
    task["description"] = task.get("description", "")  # Ensure description is provided

    # Choose the correct endpoint based on the platform
    endpoint = "/api/v1/jiratasks/" if task["platform"] == "jira" else "/api/v1/gittasks/"

    try:
        response = requests.post(BASE_API_URL + endpoint, json=task)
        response.raise_for_status()  # Will raise an exception for 4xx/5xx errors
        logger.info(f"Posted task: {task['title']} to {task['platform']}")
        return True
    except requests.exceptions.HTTPError as e:
        logger.error(f"Failed to post task: {e.response.status_code} {e.response.text}")
        return False


def update_message_status(mid, original_msg):
    try:
        original_msg["processed"] = True
        original_msg["status"] = "processed"
        response = requests.put(f"{BASE_API_URL}/api/v1/messages/{mid}", json=original_msg)
        response.raise_for_status()
        logger.info(f"Updated message {mid} to processed")
    except Exception as e:
        logger.error(f"Failed to update message status: {e}")

def update_message_with_reply(mid, reply):
        try:
            url = f"{BASE_API_URL}/api/v1/messages/{mid}"
            get_response = requests.get(url)
            get_response.raise_for_status()
            message_data = get_response.json()

            # # Check if the status is already "successful" and preserve it
            # if message_data.get("status") != "successful":
            
            
            message_data["reply"] = reply
            message_data["completion_date"] = datetime.now(timezone.utc).isoformat()

            update_response = requests.put(url, json=message_data)
            update_response.raise_for_status()
            logger.info(f"Message {mid} updated with reply")
            return True
        except Exception as e:
            logger.error(f"Error updating message {mid}: {e}")
            return False
def process_message_for_tasks(mid):
    msg = fetch_message(mid)
    if not msg:
        return

    tasks = analyze_tasks_with_llm(msg["content"])
    if not tasks:
        update_message_with_reply(mid, "Sorry, I can't help with that right now — but I'm happy to answer another question!")
        logger.info(f"No tasks found in message {mid}")
        return

    for task in tasks:
        post_task(task, mid)

    # update_message_status(mid, msg)
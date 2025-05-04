from jira import JIRA 
import getpass
import requests
import json
import sys
import os
from dotenv import load_dotenv

# Load environment variables when this module is loaded
load_dotenv()

# Initialize JIRA client

from .metadata_utils import (
    load_metadata,
    save_metadata,
    update_project_metadata,
    get_project_key_by_name,
    store_issue_metadata,
    JSON_PATH
)

def connect_jira():
    # Read credentials from environment variables
    server = os.getenv("JIRA_SERVER")
    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")

    # Validate essential Jira credentials
    if not all([server, email, api_token]):
        print("Critical Error: JIRA_SERVER, JIRA_EMAIL, or JIRA_API_TOKEN environment variable not set in jira_functions.")
        # Optionally raise an error instead of exiting:
        # raise ValueError("Missing required Jira environment variables (SERVER, EMAIL, API_TOKEN)")
        sys.exit(1) # Or handle more gracefully

    # Removed getpass fallback as token should always come from env
    # if not api_token:
    #     api_token = getpass.getpass("Enter your Jira API token: ")

    try:
        print(f"Connecting to Jira server: {server} with email: {email}") # Log connection attempt
        jira_client = JIRA(server=server, basic_auth=(email, api_token))
        # Test connection (optional but recommended)
        jira_client.myself()
        print("Successfully connected to Jira.")
        return jira_client
    except Exception as e:
        print(f"Failed to connect to Jira: {e}")
        # Optionally raise the exception or handle it
        # raise ConnectionError(f"Failed to connect to Jira: {e}") from e
        sys.exit(1) # Exit if connection fails


def get_project(project_key):
    
    # First, try to load from JSON
    try:
        with open(JSON_PATH, 'r') as f:
            projects_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        projects_data = {}

    # Check if project exists in JSON
    if project_key in projects_data:
        project = projects_data[project_key]
        print(f"(From JSON) Project: {project['key']} - {project['name']}")
        print(f"Here is the direct link -> https://agent1kodmate.atlassian.net/browse/{project['key']}")
        return project
    
    # If not in JSON, fallback to Jira API
    jira = connect_jira()
    try:
        project = jira.project(project_key)
        print(f"(From Jira API) Project: {project.key} - {project.name}")
        print(f"Here is the direct link -> {jira_url(jira, project_key)}")
        return project
    except Exception as e:
        print(f"Failed to get project {project_key}: {e}")
        return None


def list_projects():
    
    try:
        with open(JSON_PATH, 'r') as f:
            projects_data = json.load(f)
    except FileNotFoundError:
        print("Metadata file not found.")
        return []
    except json.JSONDecodeError:
        print("Error decoding JSON from metadata file.")
        return []

    data = []
    for key, project in projects_data.items():
        project_info = {
            "key": project.get("key"),
            "name": project.get("name"),
            "url": f"https://agent1kodmate.atlassian.net/browse/{key}"
        }
        data.append(project_info)
        print(f"Project-key: {project_info['key']} | Name: {project_info['name']} | URL: {project_info['url']}")

    return data


def create_project_rest(key, name):
    # Get credentials from environment variables
    server = os.getenv("JIRA_SERVER")
    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")

    # Validate essential Jira credentials
    if not all([server, email, api_token]):
        print("Critical Error: Missing required Jira environment variables (SERVER, EMAIL, API_TOKEN) for create_project_rest.")
        return {"error": "Missing Jira credentials in environment"}

    project_type = "software"
    template_key = "com.pyxis.greenhopper.jira:basic-software-development-template" # Default template
    url = f"{server}/rest/api/3/project"
    auth = (email, api_token) # Use credentials from environment
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    # jira = connect_jira() # No need to connect separately if just using requests

    # Get your account ID using the credentials from environment
    myself_url = f"{server}/rest/api/3/myself"
    print(f"Fetching account ID from: {myself_url}")
    try:
        response = requests.get(myself_url, headers=headers, auth=auth)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching account ID: {e}")
        # Attempt to parse error response if possible
        error_details = "Unknown error"
        try:
            error_details = response.json() if response else "No response"
        except json.JSONDecodeError:
            error_details = response.text if response else "No response text"
        print(f"Response details: {error_details}")
        return {"error": f"Failed to fetch account ID: {e}"}

    account_id = response.json().get('accountId')
    if not account_id:
        print("Error: Could not retrieve accountId from Jira.")
        return {"error": "Could not retrieve accountId"}

    print(f"Using leadAccountId: {account_id}")

    payload = {
        "key": key,
        "name": name,
        "projectTypeKey": project_type,
        "projectTemplateKey": template_key,
        "leadAccountId": account_id
    }

    print(f"Attempting to create project '{key}' ({name}) at {url}")
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, auth=auth)
        response.raise_for_status() # Raise HTTPError for bad responses
    except requests.exceptions.RequestException as e:
        print(f"Error creating project {key}: {e}")
        error_details = "Unknown error"
        try:
            error_details = response.json() if response else "No response"
        except json.JSONDecodeError:
            error_details = response.text if response else "No response text"
        print(f"Response details: {error_details}")
        return {"error": f"Failed to create project: {e}", "details": error_details}

    print(f"Successfully created project {key} -> {server}/browse/{key}")

    project_data = {
        "name": name,
        "key": key,
        "issues": []
    }
    update_project_metadata(project_data)
    return response.json() # Return the successful response JSON



def update_project(project_key, new_name=None, new_description=None):
    jira=connect_jira()
    try:
        # Get the server from the JIRA object
        server = jira._options['server']
        
        # For authentication, we need to extract the credentials differently
        # based on how they're stored in the JIRA object
        auth = None
        
        # Check if basic_auth is present as a tuple
        if 'basic_auth' in jira._options and isinstance(jira._options['basic_auth'], tuple):
            email, api_token = jira._options['basic_auth']
            auth = (email, api_token)
        else:
            # Try to get auth info from session object
            try:
                auth = jira._session.auth
            except AttributeError:
                print("Could not extract authentication details from JIRA object")
                return None
        
        if not auth:
            print("Authentication details not found in JIRA object")
            return None
        
        # Build the request
        url = f"{server}/rest/api/3/project/{project_key}"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Build the payload with only the fields we want to update
        payload = {}
        if new_name:
            payload["name"] = new_name
        
        if new_description:
            payload["description"] = new_description
        
        # Only make the request if we have fields to update
        if payload:
            response = requests.put(
                url,
                data=json.dumps(payload),
                headers=headers,
                auth=auth
            )
            
            if response.status_code >= 400:
                print(f"Error updating project: {response.status_code}")
                print(response.text)
                return None
            
            if new_name:
                print(f"Updated project name to {new_name}")
            
            if new_description:
                print(f"Updated project description")
            
            updated_project = jira.project(project_key)

            # Now, save the updated project metadata in the JSON file
            updated_project_data = {
                "name": updated_project.name,
                "key": project_key,
                "issues": []  # Assuming no issues are added in this update; add them if needed
            }
            
            # Update metadata in JSON
            update_project_metadata(updated_project_data)
        else:
            print("No updates provided for the project")
        print(f"Here is the direct link -> {jira_url(jira,project_key)}")
        return jira.project(project_key)
        
    except Exception as e:
        print(f"Failed to update project {project_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,project_key)}")
        return None


def delete_project(project_key):
    
    
    # Connect to Jira
    jira = connect_jira()
    jira_deleted = False
    try:
        jira.delete_project(project_key)
        print(f"Project {project_key} deleted successfully from Jira")
        jira_deleted = True
    except Exception as e:
        if '404' in str(e) or 'No project could be found' in str(e):
            print(f"Project {project_key} already deleted or not found in Jira")
            jira_deleted = True  # treat as success and continue
        else:
            print(f"Failed to delete project {project_key} from Jira: {e}")
            return False

    # Delete from JSON
    try:
        with open(JSON_PATH, 'r') as f:
            projects_data = json.load(f)
        
        if project_key in projects_data:
            del projects_data[project_key]
            with open(JSON_PATH, 'w') as f:
                json.dump(projects_data, f, indent=2)
            print(f"Project {project_key} deleted successfully from JSON metadata")
        else:
            print(f"Project {project_key} not found in JSON metadata")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error accessing metadata file: {e}")
    
    return jira_deleted


def sanitize_project_key(name):
    
    sanitized = ''.join(c for c in name.upper() if c.isalnum())
    if not sanitized or not sanitized[0].isalpha():
        sanitized = 'A' + sanitized  # Ensure it starts with a letter
    return sanitized[:10]


def create_issue(project_key, summary, description):
    jira=connect_jira()
    try:
        new_issue = jira.create_issue(
            project=project_key,
            summary=summary,
            description=description,
            issuetype= "Task"
        )
        print(f"Created issue: {new_issue.key} -> {jira_url(jira,new_issue.key)}")
        store_issue_metadata(project_key, new_issue.key, summary)
        return new_issue
    except Exception as e:
        print(f"Failed to create issue: {e}")
        return None


def get_issue(issue_key):
    jira = connect_jira()
    issue_found = False

    try:
        # Check JSON metadata first
        with open(JSON_PATH, 'r') as f:
            projects_data = json.load(f)
        
        for project in projects_data.values():
            for issue in project.get('issues', []):
                if issue['issue_key'] == issue_key:
                    print(f"(From JSON) Issue {issue['issue_key']}: {issue['summary']}")
                    print(f"Here is the direct link -> {jira_url(jira, issue_key)}")
                    issue_found = True
                    break
            if issue_found:
                break
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading metadata file: {e}")

    # If not found in JSON, fallback to Jira
    if not issue_found:
        try:
            issue = jira.issue(issue_key)
            print(f"(From Jira) Issue {issue.key}: {issue.fields.summary}")
            print(f"Here is the direct link -> {jira_url(jira, issue_key)}")
            return issue
        except Exception as e:
            print(f"Failed to get issue {issue_key} from Jira: {e}")
            print(f"Here is the direct link -> {jira_url(jira, issue_key)}")
            return None


def update_issue(issue_key, summary=None, description=None):
    jira = connect_jira()
    if not jira: return None # Handle connection failure
    updated_in_json = False

    try:
        # Update issue in Jira
        issue = jira.issue(issue_key)
        update_fields = {}

        if summary:
            update_fields["summary"] = summary
        if description:
            update_fields["description"] = description

        if update_fields:
            issue.update(**update_fields)
            print(f"Updated issue {issue_key} in Jira")

        print(f"Here is the direct link -> {jira_url(jira, issue_key)}")

        # Update metadata JSON if exists
        try:
            with open(JSON_PATH, 'r') as f:
                projects_data = json.load(f)

            for project in projects_data.values():
                for issue_entry in project.get('issues', []):
                    if issue_entry['issue_key'] == issue_key:
                        if summary:
                            issue_entry['summary'] = summary
                        # We're not storing description in JSON, but you could extend here
                        updated_in_json = True
                        break

            if updated_in_json:
                with open(JSON_PATH, 'w') as f:
                    json.dump(projects_data, f, indent=2)
                print(f"Updated issue {issue_key} in metadata JSON")

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error updating metadata JSON: {e}")

        return jira.issue(issue_key)

    except Exception as e:
        print(f"Failed to update issue {issue_key}: {e}")
        return None


def add_comment(issue_key, comment_text):
    jira=connect_jira()
    if not jira: return None # Handle connection failure
    try:
        issue = jira.issue(issue_key)
        comment = jira.add_comment(issue, comment_text)
        print(f"Added comment to {issue_key} -> {jira_url(jira,issue_key)}")
        return comment
    except Exception as e:
        print(f"Failed to add comment to {issue_key}: {e} ")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return None


def delete_issue(issue_key):
    jira = connect_jira()
    if not jira: return False # Handle connection failure
    try:
        # First, get the issue from Jira
        issue = jira.issue(issue_key)
        
        # Extract the project key from the issue key (e.g., SOFT-3 -> SOFT)
        project_key = issue_key.split('-')[0]
        
        # Load existing project metadata from the JSON file
        projects_data = load_metadata() # Use load_metadata utility

        # Check if the project exists in the metadata
        if project_key in projects_data:
            # Find the issue in the project's issues list and delete it
            issues = projects_data[project_key].get("issues", [])
            updated_issues = [i for i in issues if i['issue_key'] != issue_key]
            
            # Update the issues list in the project metadata
            projects_data[project_key]['issues'] = updated_issues
            
            # Save the updated metadata back to the JSON file
            save_metadata(projects_data) # Use save_metadata utility

            print(f"Deleted issue {issue_key} from metadata")

        else:
            print(f"Project {project_key} not found in metadata")

        # Then delete the issue from Jira
        issue.delete()
        print(f"Deleted issue {issue_key} from Jira")
        
        return True

    except Exception as e:
        print(f"Failed to delete issue {issue_key}: {e}")
        return False



def assign_issue(assignee, issue_key):
    jira=connect_jira()
    try:
        print(f"Trying to assign issue {issue_key} to {assignee}...")
        issue = jira.issue(issue_key)
        jira.assign_issue(issue, assignee)
        print(f"Successfully assigned {issue_key} to {assignee} -> {jira_url(jira,issue_key)}")
        return True

    except Exception as e:
        print(f"Failed to assign issue. Issue Key: {issue_key}, Assignee: {assignee}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        print(f"Error: {e}")
        return False


def get_issues_in_project(project_key):
    jira = connect_jira()
    try:
        with open(JSON_PATH, 'r') as f:
            projects_data = json.load(f)
        if project_key in projects_data and projects_data[project_key].get("issues"):
            for issue in projects_data[project_key]["issues"]:
                print(f"{issue['issue_key']}: {issue['summary']}")
            return projects_data[project_key]["issues"]
        jql = f'project = {project_key}'
        issues = jira.search_issues(jql)
        for issue in issues:
            print(f"{issue.key}: {issue.fields.summary} -> {jira_url(jira,issue.key)}")
        return issues
    except Exception as e:
        print(f"Failed to fetch issues for project {project_key}: {e}")
        return []


def add_attachment(issue_key, file_path):
    jira=connect_jira()
    try:
        issue = jira.issue(issue_key)
        jira.add_attachment(issue, file_path)
        print(f"Attachment {file_path} added to issue {issue_key} -> {jira_url(jira,issue_key)}")
        return True
    except Exception as e:
        print(f"Failed to add attachment to issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return False

def get_comments(issue_key):
    jira=connect_jira()
    try:
        issue = jira.issue(issue_key)
        comments = jira.comments(issue)
        for comment in comments:
            print(f"Comment by {comment.author.displayName}: {comment.body}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return comments
    except Exception as e:
        print(f"Failed to fetch comments for issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return []


def set_priority(issue_key, priority_name):
    jira=connect_jira()
    try:
        # Fetch the issue
        issue = jira.issue(issue_key)

        # Get the list of all priorities
        priorities = jira.priorities()

        # Find the priority by name (case-insensitive comparison)
        priority = next((p for p in priorities if p.name.lower() == priority_name.lower()), None)

        if priority:
            # Update the issue's priority
            issue.update(fields={"priority": {"id": priority.id}})
            print(f"Priority of issue {issue_key} set to {priority_name} -> {jira_url(jira,issue_key)}")
        else:
            print(f"Priority '{priority_name}' not found.")
            print(f"Here is the direct link -> {jira_url(jira,issue_key)}")

        return True
    except Exception as e:
        print(f"Failed to set priority for issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return False


def get_issue_status(issue_key):
    jira=connect_jira()
    try:
        issue = jira.issue(issue_key)
        status = issue.fields.status.name
        print(f"Issue {issue_key} is currently in {status} status -> {jira_url(jira,issue_key)}")
        return status
    except Exception as e:
        print(f"Failed to fetch status for issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return None


def set_due_date(issue_key, due_date):
    jira=connect_jira()
    try:
        issue = jira.issue(issue_key)
        issue.update(fields={"duedate": due_date})
        print(f"Due date for issue {issue_key} set to {due_date} -> {jira_url(jira,issue_key)}")
        return True
    except Exception as e:
        print(f"Failed to set due date for issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return False


def get_issues_sorted_by_due_date(project_key):
    jira=connect_jira()
    try:
        # Define the JQL query to get all issues and sort them by due date in ascending order
        jql_query = f'project = "{project_key}" AND due IS NOT NULL ORDER BY due ASC'


        # Execute the JQL query
        issues = jira.search_issues(jql_query)

        # Sort the issues by due date (if not sorted by JQL)
        sorted_issues = sorted(issues, key=lambda x: x.fields.duedate)

        # Print the sorted issues
        print(f"Found {len(sorted_issues)} issues sorted by due date:")
        for issue in sorted_issues:
            print(f"{issue.key}: Due Date - {issue.fields.duedate} -> {jira_url(jira,issue.key)}")

        return sorted_issues
    except Exception as e:
        print(f"Failed to fetch issues sorted by due date: {e}")
        print(f"Here is the direct link -> {jira_url(jira,project_key)}")
        return None

def edit_comment(issue_key, search_text, new_text):
    jira=connect_jira()
    try:
        # Get the comments of the issue
        issue = jira.issue(issue_key)
        comments = jira.comments(issue)
        
        # Search for the comment by text
        comment_to_edit = None
        for comment in comments:
            if search_text in comment.body:  # Search if the comment contains the text
                comment_to_edit = comment
                break
        
        if comment_to_edit:
            # Edit the comment
            comment_to_edit.update(body= new_text)
            print(f"Comment containing '{search_text}' edited in issue {issue_key} -> {jira_url(jira,issue_key)}")
        else:
            print(f"No comment containing '{search_text}' found in issue {issue_key} -> {jira_url(jira,issue_key)}")
    except Exception as e:
        print(f"Failed to edit comment in issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")

def add_label_to_issue(issue_key, label):
    jira=connect_jira()
    try:
        issue = jira.issue(issue_key)
        issue.fields.labels.append(label)
        issue.update(fields={"labels": issue.fields.labels})
        print(f"Label '{label}' added to issue {issue_key} -> {jira_url(jira,issue_key)} ")
    except Exception as e:
        print(f"Failed to add label: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")


def get_issue_transitions(issue_key):
    jira=connect_jira()

    try:
        # Fetch the issue by its key
        issue = jira.issue(issue_key)
        
        # Get available transitions for the issue
        transitions = jira.transitions(issue)
        
        # Print and return all available transitions
        print(f"Available transitions for issue {issue_key} -> {jira_url(jira,issue_key)}")
        for transition in transitions:
            print(f"  - Transition ID: {transition['id']}, Name: {transition['name']}")
        
        return transitions
    except Exception as e:
        print(f"Failed to fetch transitions for issue {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")
        return None


def transition_issue(issue_key, transition_name):
    jira=connect_jira()
    try:
        # Fetch available transitions for the issue
        transitions = get_issue_transitions(issue_key)
        
        if transitions:
            # Find the transition ID by matching the transition name
            transition_id = next((t['id'] for t in transitions if t['name'] == transition_name), None)
            
            if transition_id:
                # Transition the issue using the transition ID
                jira.transition_issue(issue_key, transition_id)
                print(f"Issue {issue_key} transitioned to {transition_name}")
            else:
                print(f"Transition '{transition_name}' not found for issue {issue_key}")
        else:
            print(f"No transitions available for issue {issue_key}")
    except Exception as e:
        print(f"Failed to transition issue {issue_key} to '{transition_name}': {e}")
        print(f"Here is the direct link -> {jira_url(issue_key)}")
        


def delete_comment(issue_key, search_text):
    jira=connect_jira()
    try:
        # Get the comments of the issue
        issue = jira.issue(issue_key)
        comments = jira.comments(issue)
        
        # Search for the comment by text
        comment_to_delete = None
        for comment in comments:
            if search_text in comment.body:  # Search if the comment contains the text
                comment_to_delete = comment
                break
        
        if comment_to_delete:
            # Delete the comment
            comment_to_delete.delete()
            print(f"Comment containing '{search_text}' deleted from issue {issue_key} -> {jira_url(jira,issue_key)}")
        else:
            print(f"No comment containing '{search_text}' found in issue {issue_key} -> {jira_url(jira,issue_key)}")
    except Exception as e:
        print(f"Failed to delete comment in issue {issue_key}: {e}")



def get_issue_history(issue_key):
    jira=connect_jira()
    
    try:
        # Make the API call to fetch the changelog using the Jira REST API
        changelog_url = f"{jira._options['server']}/rest/api/2/issue/{issue_key}/changelog"
        response = jira._session.get(changelog_url)
        
        # Check if the response was successful
        if response.status_code == 200:
            changelog = response.json()
            
            print(f"History for issue {issue_key} -> {jira_url(jira,issue_key)}")
            
            # Iterate through the changelog entries
            for history in changelog['values']:
                print(f"Change made by {history['author']['displayName']} on {history['created']}:")
                
                # Print the details of each field change
                for item in history['items']:
                    print(f"  Field '{item['field']}' changed from '{item['fromString']}' to '{item['toString']}'")
        
        else:
            print(f"Failed to fetch history for issue {issue_key}: {response.status_code}")
            print(f"Here is the direct link -> {jira_url(jira,issue_key)}")

    
    except Exception as e:
        print(f"Error fetching issue history for {issue_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,issue_key)}")


def remove_label(issue_key, label):
    jira=connect_jira()
    issue = jira.issue(issue_key)
    labels = issue.fields.labels
    if label in labels:
        labels.remove(label)
        issue.update(fields={"labels": labels})
        print(f"Label '{label}' removed from {issue_key} -> {jira_url(jira,issue_key)}")


def search_issues_by_assignee(assignee):
    jira=connect_jira()
    jql = f'assignee = "{assignee}" ORDER BY updated DESC'
    issues = jira.search_issues(jql)
    return issues


def download_attachments(issue_key):
    jira=connect_jira()
    issue = jira.issue(issue_key)
    current_directory = os.getcwd()
    for attachment in issue.fields.attachment:
        file_content = requests.get(attachment.content, auth=(jira._session.auth[0], jira._session.auth[1]))
        with open(f"{current_directory}/{attachment.filename}", "wb") as f:
            f.write(file_content.content)
        print(f"Downloaded: {attachment.filename}")



def move_issue_to_project(issue_key, new_project_key):
    jira=connect_jira()
    new_issue_type="Task"
    delete_original=True
    try:
        # Fetch the original issue
        original = jira.issue(issue_key)

        # Determine if the issue has already been moved (look for a specific pattern)
        summary = original.fields.summary
        if "Moved from" in summary:
            # Remove the previous move reference, only keeping the most recent one
            summary = summary.split(']')[-1].strip()

        # Prepare fields for the new issue
        fields = {
            'project': {'key': new_project_key},
            'summary': f"[Moved from {issue_key}] {summary}",  # Include original issue key in summary
            'description': original.fields.description,  # Add original issue key to description
            'issuetype': {'id': original.fields.issuetype.id},  # Ensure issue type is an ID
        }

        # Sanitize the description to avoid sensitive information (like the original key)
        sanitized_description = fields['description'].replace(issue_key, "[REDACTED]")
        fields['description'] = sanitized_description

        # Create the new issue in the new project
        new_issue = jira.create_issue(fields=fields)

        # Optionally delete the original issue
        if delete_original:
            original.delete()

        print(f"Issue {issue_key} moved to project {new_project_key} successfully -> {jira_url(jira,new_project_key)}")

    except Exception as e:
        print(f"Failed to move issue {issue_key} to project {new_project_key}")


def create_subtask(parent_issue_key, subtask_summary, subtask_description):
    jira=connect_jira()
    try:
        # Prepare fields for the subtask
        fields = {
            'project': {'key': jira.issue(parent_issue_key).fields.project.key},
            'summary': subtask_summary,
            'description': subtask_description,
            'issuetype': {'name': 'Sub-task'},
            'parent': {'key': parent_issue_key}
        }

        # Create the subtask
        subtask = jira.create_issue(fields=fields)
        print(f"Subtask created successfully under issue {parent_issue_key} -> {jira_url(jira,parent_issue_key)}")

    except Exception as e:
        print(f"Failed to create subtask under issue {parent_issue_key}")

def link_issues(issue_key_1, issue_key_2, link_type):
    jira=connect_jira()
    # Define allowed link types
    allowed_link_types = [
        "is blocked by",
        "is cloned by",
        "is duplicated by",
        "blocks",
        "clones",
        "duplicates",
        "relates to"
    ]
    
    try:
        # Validate if the provided link type is in the allowed list
        if link_type not in allowed_link_types:
            print(f"Invalid link type '{link_type}'. Available link types are:")
            for lt in allowed_link_types:
                print(f"- {lt}")
            return

        # Create the issue link with the selected link type
        jira.create_issue_link(link_type, issue_key_1, issue_key_2)
        print(f"Issues {issue_key_1} and {issue_key_2} linked successfully with '{link_type}' link.")

    except Exception as e:
        print(f"Failed to link issues {issue_key_1} and {issue_key_2}: {e}")



def get_issue_details(jira, issue_key):
    try:
        # Fetch the issue
        issue = jira.issue(issue_key)
        
        # Print out basic issue details
        print(f"Issue URL: {jira_url(jira,issue.key)}")
        print(f"Issue Key: {issue.key}")
        print(f"Summary: {issue.fields.summary}")
        print(f"Description: {issue.fields.description}")
        print(f"Status: {issue.fields.status.name}")
        print(f"Assignee: {issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'}")
        
    except Exception as e:
        print(f"Failed to fetch details for issue {issue_key}")


def create_release_version(project_key, version_name, description="", release_date=None):
    jira=connect_jira()
    if not jira: return None # Handle connection failure
    try:
        version = jira.create_version(name=version_name, project=project_key, description=description, releaseDate=release_date)
        print(f"Version '{version_name}' created successfully in project {project_key} -> {jira_url(jira,project_key)}")
        return version
    except Exception as e:
        print(f"Failed to create version '{version_name}' in project {project_key}: {e}")
        print(f"Here is the direct link -> {jira_url(jira,project_key)}")
        return None # Added return None on failure

def assign_version_to_issue(issue_key, version_name):
    jira=connect_jira()
    if not jira: return False # Handle connection failure
    try:
        # Fetch the issue
        issue = jira.issue(issue_key)
        
        # Assign the version to the issue
        issue.update(fields={"fixVersions": [{"name": version_name}]})
        print(f"Version '{version_name}' assigned to issue {issue_key} -> {jira_url(jira,issue_key)}")
        return True
    except Exception as e:
        print(f"Failed to assign version '{version_name}' to issue {issue_key}: {e}")
        return False # Added return False


def get_project_versions(project_key):
    jira=connect_jira()
    if not jira: return None # Handle connection failure
    try:
        versions = jira.project_versions(project_key)
        if versions:
            print(f"Versions for project {project_key}:")
            for version in versions:
                print(f"Version: {version.name}, Released: {version.released}")
        else:
            print(f"No versions found for project {project_key}.")
        print(f"Here is the direct link -> {jira_url(jira,project_key)}")
        return versions # Return the versions list
    except Exception as e:
        print(f"Failed to fetch versions for project {project_key}: {e}")
        return None # Added return None


#---------------URL Func--------------
def jira_url(jira, key):
    # No need to call connect_jira() here, pass the connected client
    if not jira:
        print("Error: Jira client not provided for URL generation.")
        return "#" # Return a placeholder or raise error
    try:
        server = jira._options['server']
        url = f"{server}/browse/{key}"
        return url
    except Exception as e:
        print(f"Failed to generate Jira URL: {e}")
        return "#" # Return placeholder


# Remove the old __main__ block entirely or ensure no credentials remain
if __name__ == "__main__":
    # This block is generally not recommended for library files used by Celery/web apps
    # Keep it empty or remove it to avoid accidental execution or credential exposure
    pass
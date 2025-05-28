import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
import json
import sys
import re
import logging
from app.services.agent_user import get_groq_api_key_sync  # Add this import
from .jira_functions import (
    connect_jira, list_projects, get_project, create_issue, get_issue,
    update_issue, add_comment, delete_issue, assign_issue,
    get_issues_in_project, add_attachment, get_comments, set_priority,
    get_issue_status, set_due_date, get_issues_sorted_by_due_date,
    edit_comment, add_label_to_issue, get_issue_transitions,
    transition_issue, delete_comment, get_issue_history, remove_label,
    search_issues_by_assignee, download_attachments, move_issue_to_project,
    create_subtask, link_issues, get_issue_details, create_release_version,
    assign_version_to_issue, get_project_versions, create_project_rest,
    update_project, delete_project, sanitize_project_key
)

from .metadata_utils import (
    load_metadata,
    save_metadata,
    update_project_metadata,
    get_project_key_by_name,
    store_issue_metadata
)

JSON_PATH = "project_metadata.json"

# Load environment
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback
BASE_API_URL = os.getenv("BASE_API_URL")

# Jira credentials
JIRA_SERVER = os.getenv("JIRA_SERVER")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN =os.getenv("JIRA_API_TOKEN")
    
# Initialize Jira client
jira = connect_jira()

function_descriptions = {
    "list_projects": "Lists all available Jira projects",
    "get_project": "Gets details about a specific project. Requires project_key",
    "create_issue": "Creates a new issue in a project. Requires project_key, summary, description",
    "get_issue": "Gets details about a specific issue. Requires issue_key",
    "update_issue": "Updates an existing issue. Requires issue_key and optionally summary and/or description",
    "add_comment": "Adds a comment to an issue. Requires issue_key and comment_text",
    "delete_issue": "Deletes an issue. Requires issue_key",
    "assign_issue": "Assigns an issue to a user. Requires assignee and issue_key",
    "get_issues_in_project": "Gets all issues in a project. Requires project_key",
    "add_attachment": "Adds an attachment to an issue. Requires issue_key and file_path",
    "get_comments": "Gets all comments on an issue. Requires issue_key",
    "set_priority": "Sets the priority of an issue. Requires issue_key and priority_name",
    "get_issue_status": "Gets the status of an issue. Requires issue_key",
    "set_due_date": "Sets the due date for an issue. Requires issue_key and due_date (YYYY-MM-DD)",
    "get_issues_sorted_by_due_date": "Gets issues in a project sorted by due date. Requires project_key",
    "edit_comment": "Edits a comment on an issue. Requires issue_key, search_text, and new_text",
    "add_label_to_issue": "Adds a label to an issue. Requires issue_key and label",
    "transition_issue": "Transitions an issue to a new status. Requires issue_key and transition_name",
    "delete_comment": "Deletes a comment from an issue. Requires issue_key and search_text",
    "get_issue_history": "Gets the history of an issue. Requires issue_key",
    "remove_label": "Removes a label from an issue. Requires issue_key and label",
    "search_issues_by_assignee": "Searches for issues assigned to a user. Requires assignee",
    "download_attachments": "Downloads all attachments from an issue. Requires issue_key",
    "move_issue_to_project": "Moves an issue to a different project. Requires issue_key and new_project_key",
    "create_subtask": "Creates a subtask under a parent issue. Requires parent_issue_key, subtask_summary, and subtask_description",
    "link_issues": "Links two issues. Requires issue_key_1, issue_key_2, and link_type",
    "get_issue_details": "Gets detailed information about an issue. Requires issue_key",
    "create_release_version": "Creates a release version in a project. Requires project_key and version_name",
    "assign_version_to_issue": "Assigns a version to an issue. Requires issue_key and version_name",
    "get_project_versions": "Gets all versions for a project. Requires project_key",
    "update_project": "Updates a project. Requires project_key and optionally new_name and/or new_description",
    "delete_project": "Deletes a project. Requires project_key",
    "create_project_rest": "Creates a new project. Requires key, name"
}

# Function to get Groq API key
def get_groq_api_key(email="service@codsy.ai"):
    """Get the Groq API key for the given email, with fallback to environment variable"""
    # Try to get API key from database
    is_allowed, api_key = get_groq_api_key_sync(email, BASE_API_URL)
    
    # Fall back to environment variable if needed
    if not is_allowed or not api_key:
        if GROQ_API_KEY:
            api_key = GROQ_API_KEY
            print(f"Using fallback GROQ API key for {email}")
        else:
            print(f"No GROQ API key available for {email}")
            return None
            
    return api_key

def extract_parameters(func_name, query, email="service@codsy.ai"):
    """
    Use ChatGroq with Llama 3.3 Versatile to extract parameters from the user query
    based on the function name.
    """
    # Get API key for this email
    api_key = get_groq_api_key(email)
    if not api_key:
        logging.error("No GROQ API key available. Cannot extract parameters.")
        return "parameter_extraction_error"
    
    # Special case for create_project_rest to ensure we get a valid key and name
    if func_name == "create_project_rest" and "project" in query.lower():
        # Try to extract project name directly first
        project_name_match = re.search(r'called\s+([A-Za-z0-9_]+)', query)
        if project_name_match:
            project_name = project_name_match.group(1)
            return {
                "key": sanitize_project_key(project_name),
                "name": project_name
            }
    # Define the parameter requirements for each function
    param_requirements = {
        "list_projects": [],
        "get_project": ["project_key"],
        "create_issue": ["project_key", "summary", "description"],
        "get_issue": ["issue_key"],
        "update_issue": ["issue_key", {"name": "summary", "optional": True}, {"name": "description", "optional": True}],
        "add_comment": ["issue_key", "comment_text"],
        "delete_issue": ["issue_key"],
        "assign_issue": ["assignee", "issue_key"],
        "get_issues_in_project": ["project_key"],
        "add_attachment": ["issue_key", "file_path"],
        "get_comments": ["issue_key"],
        "set_priority": ["issue_key", "priority_name"],
        "get_issue_status": ["issue_key"],
        "set_due_date": ["issue_key", "due_date"],
        "get_issues_sorted_by_due_date": ["project_key"],
        "edit_comment": ["issue_key", "search_text", "new_text"],
        "add_label_to_issue": ["issue_key", "label"],
        "transition_issue": ["issue_key", "transition_name"],
        "delete_comment": ["issue_key", "search_text"],
        "get_issue_history": ["issue_key"],
        "remove_label": ["issue_key", "label"],
        "search_issues_by_assignee": ["assignee"],
        "download_attachments": ["issue_key"],
        "move_issue_to_project": ["issue_key", "new_project_key"],
        "create_subtask": ["parent_issue_key", "subtask_summary", "subtask_description"],
        "link_issues": ["issue_key_1", "issue_key_2", "link_type"],
        "get_issue_details": ["issue_key"],
        "create_release_version": ["project_key", "version_name", {"name": "description", "optional": True}, {"name": "release_date", "optional": True}],
        "assign_version_to_issue": ["issue_key", "version_name"],
        "get_project_versions": ["project_key"],
        "update_project": ["project_key", {"name": "new_name", "optional": True}, {"name": "new_description", "optional": True}],
        "delete_project": ["project_key"],
        "create_project_rest": ["key", "name"]
    }
    
    # Get the required parameters for the function
    required_params = [p if isinstance(p, str) else p["name"] for p in param_requirements.get(func_name, [])]
    
    if not required_params:
        return {}  # No parameters needed
    
    # Create a prompt for Groq to extract parameters
    param_list = ", ".join(required_params)
    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.5, api_key=api_key)
        extraction_prompt = PromptTemplate(
            template="""
                Extract the following parameters from the user query: {param_list}
                User query: "{query}"
                Return ONLY a JSON object with the parameter names as keys and extracted values as values.
                Additional instructions:
                - If a parameter is not found in the query, set its value to null or a reasonable default.
                - If any date is mentioned, convert it to the format "yyyy-MM-dd".
                - If any label is mentioned, normalize it by replacing spaces with underscores (e.g., "very low" → "very_low").
                - If a project name is mentioned (e.g. "test"), create a new key `"project"` with the value set to the uppercase of the project name (e.g., "TEST").
                - If an issue is referenced like "issue 5 in project test" or "issue one in test", create a new key `"issue"` with the value formatted as issue_key (e.g., "TEST-5").
                - Handle numeric and word forms of small integers (e.g., "one" = 1, "two" = 2).
                - IMPORTANT: project_key and issue_key must ALWAYS match the inferred project key and issue key in uppercase letters.
                
                Return output in the following JSON format:
                ```json
                {{
                "param1": "value1",
                "param2": "value2"
                }}
                """,
                input_variables=["param_list", "query"],
        )
    
        formatted_prompt = extraction_prompt.format(
                param_list=param_list,
                query=query
            )
        response = llm.invoke(formatted_prompt)
        result = response.content.strip().lower()
        print(f"Raw response: {result}")
        
        # Extract JSON from response
        json_match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
        if json_match:
            result = json_match.group(1)
        else:
            # Try to find anything that looks like JSON
            json_match = re.search(r'(\{.*\})', result, re.DOTALL)
            if json_match:
                result = json_match.group(1)
        
        # Parse JSON
        parsed = json.loads(result)
        return parsed
    
    except Exception as e:
        print(f"Error extracting parameters: {e}")
        return {}

def identify_function(query, email="service@codsy.ai"):
    """
    Use ChatGroq with Llama 3.3 Versatile to identify the most appropriate function
    based on the user query.
    """
    # Get API key for this email
    api_key = get_groq_api_key(email)
    if not api_key:
        logging.error("No GROQ API key available. Cannot identify function.")
        return "function_identification_error"
    
    function_list = "\n".join([f"- {name}: {desc}" for name, desc in function_descriptions.items()])

    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.5, api_key=api_key)
        analysis_prompt = PromptTemplate(
            template="""
                Based on the following functions available for Jira interaction, identify the SINGLE most appropriate function to call based on the user query.

                Available functions:
                {function_list}

                User query: "{query}"

                Return ONLY the function name, nothing else. Just the function name as a single word.
                """,
            input_variables=["function_list", "query"],
        )

        formatted_prompt = analysis_prompt.format(
                function_list=function_list,
                query=query
            )
        response = llm.invoke(formatted_prompt)
        
        function_name = response.content.strip().lower()
        # Remove any extra text, quotes, backticks, etc.
        function_name = re.sub(r'[`"\'\n]', '', function_name)
        
        # Make sure it's one of our functions
        if function_name in function_descriptions:
            return function_name
        else:
            # Try to find a close match
            for fname in function_descriptions.keys():
                if fname.lower() in function_name.lower():
                    return fname
            
            print(f"Could not identify a valid function from response: {function_name}")
            return None
    
    except Exception as e:
        print(f"Error identifying function: {e}")
        return None

def generate_unique_project_key(base_key, json_path):
    key = base_key.upper()
    print(f"Base key: {key}")
    suffix = 1

    existing_keys = set()

    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            try:
                data = json.load(f)
                # Assuming it's a list of project objects
                existing_keys = set(proj.get('key', '').upper() for proj in data if 'key' in proj)
            except json.JSONDecodeError:
                print(f"Warning: JSON file at {json_path} is empty or invalid. Proceeding with empty key set.")
                existing_keys = set()

    new_key = key
    while new_key in existing_keys:
        new_key = f"{key}{suffix}"
        suffix += 1

    return new_key

def process_query_jira(query, email="service@codsy.ai"):
    print(f"Processing query: {query}")
    function_name = identify_function(query, email)
    if not function_name:
        return "Sorry, I couldn't identify which Jira function to use for your query."

    print(f"Identified function: {function_name}")
    params = extract_parameters(function_name, query, email)

    # Auto-generate unique project key if missing
    if function_name == "create_project_rest":
        if not params.get("key"):
            base_key = sanitize_project_key(params.get("name", ""))
            if not base_key:
                return "Error: Could not generate a valid project key. Please provide one explicitly."
            params["key"] = generate_unique_project_key(base_key, JSON_PATH)
        else:
            # Ensure provided key is uppercase
            params["key"] = params["key"].upper()


    # Resolve project key if project name is provided
    if 'project_key' in params:
        project_name = params['project_key']
        resolved_key = get_project_key_by_name(project_name)
        if resolved_key:
            print(f"Resolved project key: {resolved_key}")
            params['project_key'] = resolved_key
        else:
            return f"Project '{project_name}' not found in metadata."

    print(f"Updated parameters: {params}")

    try:
        func = globals()[function_name]

        if function_name == "update_project":
            result = update_project(
                params.get("project_key"),
                new_name=params.get("new_name"),
                new_description=params.get("new_description")
            )

        elif function_name == "create_project_rest":
            result = create_project_rest(
                params["key"],
                params.get("name")
            )

        else:
            import inspect
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())

            args = []
            if "jira" in param_names and function_name != "create_project_rest":
                args.append(jira)
                param_names.remove("jira")

            for name in param_names:
                if name in params:
                    args.append(params.get(name))
                else:
                    return f"Error: Missing required parameter '{name}'"

            result = func(*args)

        # Format the result as JSON if it's structured
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        else:
            return str(result)

    except Exception as e:
        return f"Error executing function {function_name}: {str(e)}"



# if __name__ == "__main__":
#     print("Welcome to the Jira Assistant!")
#     print("You can ask queries in natural language to interact with Jira.")
#     print("Type 'exit' to quit.")
    
#     while True:
#         query = input("\nEnter your query: ")
#         if query.lower() in ['exit', 'quit']:
#             break
        
#         result = process_query_jira(query)
#         print("\nResult:", result)
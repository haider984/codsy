import os
from dotenv import load_dotenv
from groq import Groq
import json
import sys
import re
import logging
from app.services.agent_user import get_groq_api_key_sync  # Add this import
from .github_functions import (
    sanitize_repo_name,
    create_github_repo,
    clone_repo,
    create_branch,
    commit_changes,
    push_changes,
    read_file,
    list_repos,
    list_branches,
    analyze_repo_structure,
    list_issues,
    create_github_issue,
    auto_label_issue,
    auto_merge_pr,
    create_release,
    get_commit_activity,
    assign_users,
    sync_branch_with_main,
    create_workflow,
   
    rename_repository,
    generate_code,
    update_code,
    update_existing_code,
    generate_and_push_code,
    create_pull_request,
    archive_repo, 
    unarchive_repo,
    backup_repo,
    rename_branch,
    duplicate_repo,
    restore_repo,
    delete_and_backup_repo,
    
)

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Keep as fallback
BASE_API_URL = os.getenv("BASE_API_URL")

# Don't initialize client globally

# Dictionary to cache Groq clients by email
groq_clients = {}

def get_groq_client(email="service@codsy.ai"):
    """Get a Groq client for the given email, with fallback to environment variable"""
    # Return cached client if available
    if email in groq_clients:
        return groq_clients[email]
        
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
            
    # Create and cache client
    try:
        client = Groq(api_key=api_key)
        groq_clients[email] = client
        return client
    except Exception as e:
        print(f"Error creating Groq client: {e}")
        return None

# Function descriptions for GitHub functions available in github_actions.py
function_descriptions = {
    "sanitize_repo_name": "Sanitizes the repository name by removing invalid characters.",
    "create_github_repo": "Creates a new GitHub repository. Requires repository name.",
    "clone_repo": "Clones a repository to the local machine. Requires repository name.",
    "create_branch": "Creates a new branch in the repository. Requires repository name and branch name.",
    "commit_changes": "Commits changes to a file in the repository. Requires repository name, file path, commit message, and optional file content.",
    "push_changes": "Pushes local changes to the remote repository. Requires repository name.",
    "read_file": "Reads the contents of a file in the repository. Requires repository name and file path.",
    "list_repos": "Lists all repositories in the GitHub account.",
    "list_branches": "Lists all branches in a repository. Requires repository name.",
    "analyze_repo_structure": "Analyzes the structure of the repository. Requires repository name.",
    "list_issues": "Lists all open issues in a repository. Requires repository name.",
    "create_github_issue": "Creates a new issue in a repository. Requires repository name, title, optional body, and optional labels.",
    "auto_label_issue": "Labels an existing issue. Requires repository name, issue number, and labels.",
    "create_pull_request": "Create a PR as per the instructions",
    "auto_merge_pr": "Merges a pull request if it's mergeable. Requires repository name, PR number, and optional merge message.",
    "create_release": "Creates a new release for the repository. Requires repository name, tag name, release name, optional body, and optional draft status.",
    "get_commit_activity": "Fetches recent commit activity for a repository. Requires repository name.",
    "assign_users": "Assigns users to an issue. Requires repository name, issue number, and assignees.",
    "sync_branch_with_main": "Synchronizes a branch with the main branch. Requires repository name and branch name.",
    "create_workflow": "Creates a GitHub Actions workflow. Requires repository name and optional filename.",
    "rename_repository": "Renames a GitHub repository. Requires old name and new name.",
    "generate_code": "Generates code based on a given prompt using Groq LLM.",
    "update_code": "Updates existing code based on natural language instructions.",
    "update_existing_code": "Updates code in a repository file based on instructions. Requires repository name, file path, and instruction.",
    "generate_and_push_code": "Generates code from a prompt and commits it to a repository. Requires repository name, filename, and prompt.",
     "archive_repo": "Archives a repository, making it read-only. Requires repository name.",
    "unarchive_repo": "Unarchives a previously archived repository, restoring it to active status.",
    "backup_repo": "Creates a backup of the repository, usually by making a zip to another location.",
    "rename_branch": "Renames a branch in a repository. Requires branch name and new name.",
    "duplicate_repo": "Duplicates an existing repository to a new repository. Requires source and destination repository details.",
    "restore_repo": "Restores a repository from a previously downloaded zip backup.",
    "delete_and_backup_repo": "First backs up the repository to a zip file, then deletes it from GitHub.",
     
}

# Define parameter requirements for each function based on github_actions.py implementations
param_requirements = {
    "sanitize_repo_name": ["repo_name"],
    "create_github_repo": ["repo_name"],
    "clone_repo": ["repo_name"],
    "create_branch": ["repo_name", "branch_name"],
    "commit_changes": ["repo_name", "file_path", "commit_message", "file_content"],
    "push_changes": ["repo_name"],
    "read_file": ["repo_name", "file_path"],
    "list_repos": [],
    "list_branches": ["repo_name"],
    "analyze_repo_structure": ["repo_name"],
    "list_issues": ["repo_name"],
    "create_github_issue": ["repo_name", "title", "body", "labels"],
    "auto_label_issue": ["repo_name", "issue_number", "labels"],
    "auto_merge_pr": ["repo_name", "pr_number", "merge_msg"],
    "create_pull_request":["repo_name", "title", "body", "head", "base"],
    "create_release": ["repo_name", "tag_name", "release_name", "body", "draft"],
    "get_commit_activity": ["repo_name"],
    "assign_users": ["repo_name", "issue_number", "assignees"],
    "sync_branch_with_main": ["repo_name", "branch_name"],
    "create_workflow": ["repo_name", "filename"],
    "rename_repository": ["old_name", "new_name"],
    "generate_code": ["request_prompt"],
    "update_code": ["existing_code", "instruction"],
    "update_existing_code": ["repo_name", "file_path", "instruction"],
    "generate_and_push_code": ["repo_name", "filename", "prompt"],
    "archive_repo": ["repo_name"],
    "unarchive_repo": ["repo_name"],
    "backup_repo": ["repo_name"],
    "rename_branch": ["repo_name", "old_branch", "new_branch"],
    "duplicate_repo": ["source_repo", "new_repo_name"],
    "restore_repo": ["repo_name"],
     "delete_and_backup_repo": ["repo_name"],

}

def identify_function(query, email="service@codsy.ai"):
    """
    Use Groq with Llama 3.3 Versatile to identify the most appropriate GitHub function
    based on the user query.
    """
    client = get_groq_client(email)
    if not client:
        print("No Groq client available. Cannot identify function.")
        return None
        
    function_list = "\n".join([f"- {name}: {desc}" for name, desc in function_descriptions.items()])

    prompt = f"""
        Based on the following functions available for GitHub interaction, identify the SINGLE most appropriate function to call based on the user query.

        Available functions:
        {function_list}

        User query: "{query}"

        Return ONLY the function name, nothing else. Just the function name as a single word.
        """

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_completion_tokens=100
        )
        
        function_name = response.choices[0].message.content.strip()
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

def extract_parameters(func_name, query, email="service@codsy.ai"):
    """
    Use Groq with Llama 3.3 Versatile to extract parameters from the user query
    based on the function name.
    """
    client = get_groq_client(email)
    if not client:
        print("No Groq client available. Cannot extract parameters.")
        return {}
        
    # Get the required parameters for the function
    required_params = param_requirements.get(func_name, [])
    
    if not required_params:
        return {}  # No parameters needed

    # Create a prompt for Groq to extract parameters
    param_list = ", ".join(required_params)
    prompt = f"""
        Analyze the user query completely and then Extract the following parameters from the user query: {param_list}

        User query: "{query}"
        IMPORTANT: In query analyze the repository name parameter 

        For example: if user query  is "now change the code of of index.html file and add a new page for colors generation and push changes to github repo named finaltest" then the repo_name parameter is finaltest.

        Return ONLY a JSON object with the parameter names as keys and extracted values as values.
        If a parameter is not found in the query, set its value to null or a reasonable default.
        If there is any "labels" parameter, transform spaces to underscores (e.g., "very low" to "very_low").

        Example response format:
        ```json
        {{
            "param1": "value1",
            "param2": "value2"
        }}
        ```
        """

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_completion_tokens=400
        )
        
        result = response.choices[0].message.content
        
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

def process_query(query, email="service@codsy.ai"):
    """
    Process a natural language query by:
    1. Identifying the appropriate GitHub function
    2. Extracting parameters from the query
    3. Executing the function with those parameters
    """
    print(f"Processing query: {query}")

    # Step 1: Identify the appropriate function
    function_name = identify_function(query, email)
    if not function_name:
        return "Sorry, I couldn't identify which GitHub function to use for your query."

    print(f"Identified function: {function_name}")

    # Step 2: Extract parameters for the function
    params = extract_parameters(function_name, query, email)
    print(f"Extracted parameters: {params}")

    # Step 3: Execute the function
    try:
        # Get the function from globals
        func = globals()[function_name]
        
        # Special handling for certain functions
        if function_name == "create_github_issue":
            if not params.get("title"):
                return "Error: Missing required parameter 'title'"
            if not params.get("body"):
                params["body"] = "No description provided"
            if not params.get("labels"):
                params["labels"] = []
        
        # Handle parameter passing based on the function's signature
        import inspect
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())
        
        # Build arguments for the function
        args = []
        for name in param_names:
            if name in params:
                args.append(params.get(name))
            else:
                # For missing required parameters, check if we should return an error
                if name in param_requirements.get(function_name, []):
                    return f"Error: Missing required parameter '{name}'"
                # Otherwise, append None for optional parameters
                args.append(None)
        
        # Execute the function with the arguments
        result = func(*args)
        
        # Format and return the result
        if result is None:
            return "Operation completed successfully with specific result."
        elif isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        else:
            return str(result)

    except Exception as e:
        return f"Error executing function {function_name}: {str(e)}"

def main():
    print("Welcome to the GitHub Assistant!")
    print("You can ask queries in natural language to interact with GitHub.")
    print("Type 'exit' to quit.")

    while True:
        query = input("\nEnter your query: ")
        if query.lower() in ['exit', 'quit']:
            break
        
        result = process_query(query)
        print("\nResult:", result)

if __name__ == "__main__":
    main()
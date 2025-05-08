# metadata_utils.py

import json
import os

# Path to the JSON file
JSON_PATH = "project_metadata.json"

def load_metadata():
    # Create the file if it doesn't exist
    if not os.path.exists(JSON_PATH):
        with open(JSON_PATH, "w") as f:
            json.dump({}, f)  # Initialize with an empty dictionary
        return {}
    
    with open(JSON_PATH, "r") as f:
        return json.load(f)

# Save metadata to JSON file
def save_metadata(data):
    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)

# Add or update a single project's metadata
def update_project_metadata(project):
    data = load_metadata()
    key = project["key"]
    data[key] = {
        "name": project["name"],
        "key": key,
        #"description": project.get("description", ""),
        "issues": project.get("issues", [])
    }
    save_metadata(data)

def store_issue_metadata(project_key, issue_key, summary):
    """Store issue metadata in a JSON file under the corresponding project."""
    # Load the existing data
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r') as file:
            data = json.load(file)
    else:
        data = {}

    # Ensure the project exists in the data
    if project_key not in data:
        data[project_key] = {"name": "", "key": project_key, "issues": []}
    
    # Add the new issue metadata to the issues list
    issue_data = {"issue_key": issue_key, "summary": summary}
    data[project_key]["issues"].append(issue_data)

    # Save the updated data back to the file
    with open(JSON_PATH, 'w') as file:
        json.dump(data, file, indent=4)


# Get project key by its name
def get_project_key_by_name(name):
    data = load_metadata()
    for key, project in data.items():
        if project["name"].lower() == name.lower():
            return key
    return None

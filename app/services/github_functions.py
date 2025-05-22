import os
import logging
import sys
from datetime import datetime
from dotenv import load_dotenv
from github import Github
from git import Repo, InvalidGitRepositoryError, GitCommandError
import requests
import subprocess
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
import hashlib
import re
import zipfile
from slack_sdk import WebClient
from app.services.agent_user import get_groq_api_key_sync

# Load .env vars
load_dotenv()
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
github_client = Github(GITHUB_TOKEN)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")
API_URL = "https://api.github.com"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

PREVIEW_SERVER_URL = os.getenv("PREVIEW_SERVER_URL")
PREVIEW_SERVER_PORT = os.getenv("PREVIEW_SERVER_PORT")

def get_groq_api_key(email="service@codsy.ai"):
    """Get the Groq API key for the given email, with fallback to environment variable"""
    # Try to get API key from database
    is_allowed, api_key = get_groq_api_key_sync(email, BASE_API_URL)
    
    # Fall back to environment variable if needed
    if not is_allowed or not api_key:
        if GROQ_API_KEY:
            api_key = GROQ_API_KEY
            logger.warning(f"Using fallback GROQ API key for {email}")
        else:
            logger.error(f"No GROQ API key available for {email}")
            return None
            
    return api_key

def sanitize_repo_name(repo_name: str) -> str:
    return repo_name.strip().replace(" ", "-")

def sanitize_basename(name: str) -> str:
    """
    Turn an arbitrary string into a safe filename base:
    - lowercase alphanumerics and dashes
    - strip out invalid characters
    """
    # keep letters, numbers, spaces, dash, underscore
    clean = re.sub(r"[^A-Za-z0-9 _-]", "", name)
    # collapse spaces/underscores to single dash
    clean = re.sub(r"[ _]+", "-", clean.strip())
    return clean.lower() or "file"

def create_github_repo(repo_name: str):
    try:
        if not repo_name or repo_name.lower() == "not specified":
            repo_name = "testrepo_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        repo_name = sanitize_repo_name(repo_name)

        user = github_client.get_user()
        existing = [r.name for r in user.get_repos()]
        if repo_name in existing:
            repo = user.get_repo(repo_name)
            msg = f"Already exists: {repo.html_url}"
            print(msg)
            return {
                "success": True,
                "message": msg,
                "repo_name": repo_name,
                "repo_url": repo.html_url
            }

        repo = user.create_repo(repo_name)

        try:
            repo.create_file(
                "README.md",
                "Initial commit",
                f"# {repo_name}\nRepository created by GitHub Automation Bot."
            )
        except Exception as e:
            print(f"⚠️ Warning: could not create README.md: {e}")

        msg = f"Created repository: {repo.html_url}"
        print(msg)
        return {
            "success": True,
            "message": msg,
            "repo_name": repo_name,
            "repo_url": repo.html_url
        }

    except Exception as e:
        msg = f"❌ Error creating repository: {e}"
        print(msg)
        return {
            "success": False,
            "message": msg,
            "repo_name": repo_name
        }



def clone_repo(repo_name: str):
    try:
        safe = sanitize_repo_name(repo_name)
        repo_url = f"https://github.com/{GITHUB_USERNAME}/{safe}.git"
        local_dir = os.path.join(".", safe)

        if os.path.exists(local_dir):
            print(f"Already cloned at {local_dir}")
            return {"success": True, "message": "Already cloned", "local_path": local_dir}

        Repo.clone_from(repo_url, local_dir)
        print(f"Cloned to {local_dir}")
        return {"success": True, "message": "Cloned successfully", "local_path": local_dir}

    except Exception as e:
        print(f"Error cloning repository: {e}")
        return {"success": False, "message": str(e), "local_path": None}


def create_branch(repo_name: str, branch_name: str):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = os.path.join(".", safe)

        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first…")
            clone_res = clone_repo(repo_name)
            if not clone_res.get("success"):
                return {"success": False, "message": "Failed to clone repo", "branch": None}

        repo = Repo(local_dir)

        # Ensure at least one commit exists
        if not repo.head.is_valid():
            dummy = os.path.join(local_dir, ".init")
            with open(dummy, "w") as f:
                f.write("init")
            repo.git.add(all=True)
            repo.index.commit("initial commit")
            repo.git.checkout("-b", "init")

        # Reset and recreate branch
        repo.git.reset("--hard", "HEAD")
        try:
            repo.git.branch("-D", branch_name)
        except GitCommandError:
            pass
        repo.git.checkout("-B", branch_name)
        print(f"Branch '{branch_name}' created locally in {local_dir}")

        # ←── **NEW** push it to GitHub
        repo.git.push("--set-upstream", "origin", branch_name)
        print(f"Branch '{branch_name}' pushed to origin/{branch_name}")

        return {
            "success": True,
            "message": f"Branch '{branch_name}' created and pushed to '{repo_name}'",
            "branch": branch_name,
            "path": local_dir
        }

    except Exception as e:
        print(f"Error creating branch: {e}")
        return {"success": False, "message": str(e), "branch": None}



def commit_changes(repo_name, file_path, commit_message, file_content="Sample content"):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = f"./{safe}"
        os.makedirs(local_dir, exist_ok=True)
        full = os.path.join(local_dir, file_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        
        if file_content is None:
            with open(file_path, "r") as src:
                file_content = src.read()

        with open(full, "w") as f:
            f.write(file_content)

        try:
            repo = Repo(local_dir)
        except InvalidGitRepositoryError:
            print("Initializing new Git repository...")
            repo = Repo.init(local_dir)
            repo.create_remote("origin", f"https://github.com/{GITHUB_USERNAME}/{safe}.git")

        repo.git.add(A=True)

        try:
            commit = repo.index.commit(commit_message)
            commit_hash = commit.hexsha
            print(f"Committed '{file_path}': {commit_hash}")
            return {
                "success": True,
                "message": f"Committed '{file_path}'",
                "commit_hash": commit_hash,
                "repo_path": local_dir
            }
        except Exception as e:
            print(f"No commit made: {e}")
            return {
                "success": False,
                "message": f"No commit made: {e}",
                "commit_hash": None,
                "repo_path": local_dir
            }

    except Exception as e:
        print(f"Error committing changes: {e}")
        return {
            "success": False,
            "message": str(e),
            "commit_hash": None,
            "repo_path": None
        }


def push_changes(repo_name):
    try:
        safe = sanitize_repo_name(repo_name)
        local_dir = f"./{safe}"
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)
        repo = Repo(local_dir)

        try:
            branch = repo.active_branch
        except Exception as e:
            print(f"No active branch (detached HEAD): {e}")
            return

        if not any(r.name == "origin" for r in repo.remotes):
            repo.create_remote("origin", f"https://github.com/{GITHUB_USERNAME}/{safe}.git")
        origin = repo.remote("origin")

        if branch.tracking_branch() is None:
            repo.git.push("--set-upstream", "origin", branch.name)
        else:
            origin.push()
        print(f"Pushed branch '{branch.name}' to origin")
        return(f"Pushed branch '{branch.name}' to origin")
    except Exception as e:
        print(f"Error pushing changes: {e}")
        return(f"Error pushing changes: {e}")


def read_file(repo_name: str, file_path: str):
    try:
        local_dir = os.path.join(".", repo_name)
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)
        full = os.path.join(local_dir, file_path)
        if not os.path.exists(full):
            print(f"File not found: {file_path}")
            return
        with open(full) as f:
            content = f.read()
        print(f"Contents of '{file_path}':\n{content}")
        return(f"Contents of '{file_path}':\n{content}")
    except Exception as e:
        print(f"Error reading file: {e}")
        return(f"Error reading file: {e}")


def list_repos():
    try:
        user = github_client.get_user()
        repos = user.get_repos()
        repo_list = []
        for r in repos:
            repo_list.append({
                "name": r.name,
                "url": r.html_url
            })
        return {
            "success": True,
            "repositories": repo_list
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def list_branches(repo_name: str):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        branches = repo.get_branches()
        branch_list = [b.name for b in branches]
        return {
            "success": True,
            "repo": repo_name,
            "branches": branch_list
        }
    except Exception as e:
        return {
            "success": False,
            "repo": repo_name,
            "error": str(e)
        }



def analyze_repo_structure(repo_name: str):
    try:
        local_dir = os.path.join(".", repo_name)
        if not os.path.exists(local_dir):
            print("Local repo not found, cloning first...")
            clone_repo(repo_name)

        structure = []
        for root, dirs, files in os.walk(local_dir):
            if ".git" in root:
                continue
            rel_path = os.path.relpath(root, local_dir)
            file_list = [f for f in files if not f.startswith(".")]
            structure.append({
                "path": rel_path,
                "files": file_list
            })

        return {
            "success": True,
            "repo": repo_name,
            "structure": structure
        }

    except Exception as e:
        return {
            "success": False,
            "repo": repo_name,
            "error": str(e)
        }

def list_issues(repo_name: str):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issues = repo.get_issues(state="open")
        issue_list = [
            {
                "number": i.number,
                "title": i.title,
                "url": i.html_url
            }
            for i in issues
        ]
        return {
            "success": True,
            "repo": repo_name,
            "issues": issue_list
        }
    except Exception as e:
        return {
            "success": False,
            "repo": repo_name,
            "error": str(e)
        }



def create_github_issue(repo_name: str, title: str, body: str = "", labels=None):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.create_issue(title=title, body=body, labels=labels or [])
        print(f"Issue created: {issue.html_url}")
        return(f"Issue created: {issue.html_url}")
    except Exception as e:
        print(f"Error creating issue: {e}")
        return(f"Error creating issue: {e}")


def auto_label_issue(repo_name: str, issue_number, labels: list) -> dict:
    """
    Adds the given labels to a GitHub issue, with robust handling of
    string inputs and nonexistent issues.
    """
    # 1) Normalize and validate inputs
    try:
        issue_num = int(issue_number)
    except (TypeError, ValueError):
        return {
            "success": False,
            "message": "❌ Invalid issue number. Please provide an integer."
        }
    if not labels:
        return {
            "success": False,
            "message": "❌ No labels provided."
        }

    try:
        # 2) Fetch the repo and issue
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.get_issue(number=issue_num)

    except Exception as e:
        # If GitHub returns a 404, issue doesn't exist
        err = str(e)
        if "404" in err or "Not Found" in err:
            return {
                "success": False,
                "message": f"❌ Issue #{issue_num} not found in {repo_name}."
            }
        return {
            "success": False,
            "message": f"❌ Error fetching issue: {err}"
        }

    try:
        # 3) Apply labels
        issue.set_labels(*labels)
        return {
            "success": True,
            "message": f"✅ Added labels {labels} to issue #{issue_num}"
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error labeling issue: {str(e)}"
        }
def create_pull_request(repo_name, title, body, head, base):
    repo = github_client.get_user().get_repo(repo_name)
    pr = repo.create_pull(title=title, body=body, head=head, base=base)
    return {
        "success": True,
        "message": f"✅ Created PR #{pr.number}",
        "pr_number": pr.number
    }


def auto_merge_pr(repo_name: str, pr_number, merge_msg="Auto-merged by bot") -> dict:
    """
    Attempts to auto-merge the given pull request.

    Args:
        repo_name (str): GitHub repo (owner/repo_name)
        pr_number (int or str): Pull request number
        merge_msg (str): Merge commit message

    Returns:
        dict: {success: bool, message: str}
    """
    try:
        # Ensure PR number is int
        pr_number = int(pr_number)
    except (TypeError, ValueError):
        return {"success": False, "message": "❌ Invalid PR number."}

    try:
        repo = github_client.get_user().get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        if not pr.mergeable:
            return {"success": False, "message": f"❌ PR #{pr_number} is not mergeable at this time."}

        result = pr.merge(commit_message=merge_msg)
        if result.merged:
            return {"success": True, "message": f"✅ PR #{pr_number} merged successfully."}
        else:
            return {"success": False, "message": f"❌ Failed to merge PR #{pr_number}."}

    except Exception as e:
        return {"success": False, "message": f"❌ Error merging PR: {e}"}



def create_release(repo_name, tag_name, release_name, body="", draft=True):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        release = repo.create_git_release(
            tag=tag_name,
            name=release_name,
            message=body,
            draft=draft,
            prerelease=False
        )
        print(f"Release '{release_name}' created: {release.html_url}")
    except Exception as e:
        print(f"Error creating release: {e}")

def duplicate_repo(source_repo: str, new_repo_name: str):
   
    source = github_client.get_user().get_repo(source_repo)
    if not source:
        return

    create_github_repo(new_repo_name)
    clone_result = clone_repo(source_repo)
    if not clone_result["success"]:
        print(clone_result["message"])
        return

    source_local = clone_result["local_path"]
    target_url = f"https://github.com/{GITHUB_USERNAME}/{sanitize_repo_name(new_repo_name)}.git"

    try:
        repo = Repo(source_local)
        if "neworigin" not in [r.name for r in repo.remotes]:
            repo.create_remote("neworigin", target_url)
        repo.git.push("--mirror", "neworigin")
        print(f"✅ Repository duplicated to '{new_repo_name}'.")
    except Exception as e:
        print(f"❌ Error during push: {e}")

def get_commit_activity(repo_name):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        commits = list(repo.get_commits())[:5]
        print(f"Last 5 commits in '{repo_name}':")
        for c in commits:
            date = c.commit.author.date
            msg = c.commit.message.strip()
            sha = c.sha[:7]
            print(f" - [{date}] {msg} ({sha})")
    except Exception as e:
        print(f"Error fetching commits: {e}")


def assign_users(repo_name, issue_number, assignees):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)
        issue.add_to_assignees(*assignees)
        print(f"Assigned {assignees} to issue #{issue_number}")
    except Exception as e:
        print(f"Error assigning users: {e}")


def sync_branch_with_main(repo_name, branch_name):
    try:
        repo = github_client.get_user().get_repo(repo_name)
        main = repo.get_branch("main")
        branch = repo.get_branch(branch_name)
        repo.merge(branch.name, main.commit.sha)
        print(f"Synchronized branch '{branch_name}' with main")
    except Exception as e:
        print(f"Error syncing branches: {e}")


def create_workflow(repo_name, filename="ci.yml"):
    try:
        content = """name: CI
on:
  push:
    branches: [ main ]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: echo Hello, world!
"""
        repo = github_client.get_user().get_repo(repo_name)
        repo.create_file(f".github/workflows/{filename}", "Add CI workflow", content)
        print(f"Workflow '{filename}' created in '{repo_name}'")
    except Exception as e:
        print(f"Error creating workflow: {e}")


def delete_and_backup_repo(repo_name: str):
    """
    Backup and delete a GitHub repo.
    - Saves a .zip of the `main` branch
    - Deletes the repo from GitHub
    - Prints status updates instead of returning
    """
    zip_url = f"https://github.com/{GITHUB_USERNAME}/{repo_name}/archive/refs/heads/main.zip"
    backup_path = f"./{repo_name}_backup.zip"

    try:
        # 1. Backup first
        print(f"📦 Downloading backup from {zip_url}...")
        r = requests.get(zip_url, stream=True)
        if r.status_code == 200:
            with open(backup_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    f.write(chunk)
            print(f"✅ Backup saved to {backup_path}")
        else:
            print(f"❌ Failed to download backup: {r.status_code} {r.text}")
            return

        # 2. Delete the repository
        print(f"🗑️ Deleting repository '{repo_name}' from GitHub...")
        repo = github_client.get_user().get_repo(repo_name)
        repo.delete()
        print(f"✅ Repository '{repo_name}' deleted successfully.")

    except Exception as e:
        print(f"❌ Error during backup/delete: {e}")


def restore_repo(repo_name: str):
    """
    Restore a deleted GitHub repo from a previously saved .zip backup.
    """
    zip_path = f"./{repo_name}_backup.zip"
    restore_dir = f"./restored_{repo_name}"

    # 1. Check for backup
    if not os.path.exists(zip_path):
        return {"success": False, "message": f"No backup zip found at {zip_path}"}

    try:
        # 2. Recreate the GitHub repo
        create_result = create_github_repo(repo_name)
        if not create_result.get("success"):
            print(create_result.get("message"))

        # 3. Extract backup
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(restore_dir)

        # GitHub zips repo into folder like: repo_name-main
        extracted_subdir = os.path.join(restore_dir, f"{repo_name}-main")
        if not os.path.exists(extracted_subdir):
            return {"success": False, "message": f"Expected folder {extracted_subdir} not found"}

        # 4. Reinitialize git repo
        os.chdir(extracted_subdir)
        os.system("git init")
        os.system("git add .")
        os.system('git commit -m "Restore from backup"')
        os.system(f"git branch -M main")
        os.system(f"git remote add origin https://github.com/{GITHUB_USERNAME}/{repo_name}.git")
        os.system("git push -u origin main")
        os.chdir("../../")  # return to original dir

        return {"success": True, "message": f"✅ Repo '{repo_name}' restored and pushed from backup"}

    except Exception as e:
        return {"success": False, "message": f"❌ Restore failed: {e}"}

def rename_repository(old_name, new_name):
    try:
        repo = github_client.get_user().get_repo(old_name)
        repo.edit(name=new_name)
        print(f"Renamed repository to '{new_name}'")
    except Exception as e:
        print(f"Error renaming repository: {e}")

def archive_repo(repo_name: str):
  
    repo = github_client.get_user().get_repo(repo_name)
    if not repo:
        return
    try:
        repo.edit(archived=True)
        print(f"📦 Repository '{repo_name}' archived successfully.")
    except Exception as e:
        print(f"❌ Error archiving repo: {e}")


def unarchive_repo(repo_name: str):
   
    repo = github_client.get_user().get_repo(repo_name)
    if not repo:
        return
    try:
        if repo.archived:
            repo.edit(archived=False)
            print(f"♻️ Repository '{repo_name}' unarchived successfully.")
        else:
            print(f"ℹ️ Repository '{repo_name}' is already active.")
    except Exception as e:
        print(f"❌ Error unarchiving repo: {e}")

def backup_repo(repo_name: str):
   
    if not github_client.get_user().get_repo(repo_name):
        return
    try:
        zip_url = f"https://github.com/{GITHUB_USERNAME}/{repo_name}/archive/refs/heads/main.zip"
        r = requests.get(zip_url, stream=True)
        if r.status_code == 200:
            file_path = f"./{repo_name}_backup.zip"
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    f.write(chunk)
            print(f"💾 Backup complete: {file_path}")
        else:
            print(f"❌ Backup failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"❌ Error backing up repo: {e}")

def rename_branch(repo_name: str, old_branch: str, new_branch: str):
    repo = github_client.get_user().get_repo(repo_name)
    if not repo:
        print(f"❌ Repo '{repo_name}' not found")
        return
    try:
        old_ref = repo.get_git_ref(f"heads/{old_branch}")
        sha = old_ref.object.sha

        # Create new ref with the same SHA
        repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=sha)

        # Delete the old ref
        old_ref.delete()

        print(f"🔀 Renamed branch '{old_branch}' → '{new_branch}'")
    except Exception as e:
        print(f"❌ Failed to rename branch: {e}")

def generate_code(request_prompt, email="service@codsy.ai"):
    """
    Generate code from a natural language prompt using the ChatGroq LLM.
    
    Args:
        request_prompt (str): Prompt for code generation (e.g., "Write an HTML contact form").
        email (str): Email of the user making the request, for API key lookup.
        
    Returns:
        str: Generated code, or an error message.
    """
    # Get API key for this email
    api_key = get_groq_api_key(email)
    if not api_key:
        logging.error("No GROQ API key available. Cannot generate code.")
        return "generate_code_error"

    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.5, api_key=api_key)
        prompt_template = PromptTemplate(
            template="""You are an expert programmer. Write clean, concise, and correct code based on the user's instructions.
            Your response must include only the final code with no explanations or formatting tags.
            For HTML files, ensure all CSS and JavaScript is properly embedded within the HTML file itself.
            Make sure all paths and resources are relative and self-contained.
            Create complete, standalone files that will work in a Docker container environment.

            User query: {request_prompt}""",
            input_variables=["request_prompt"],
        )
    
        prompt = prompt_template.format(request_prompt=request_prompt)

        response = llm.invoke(prompt)
        
        output = response.content.strip().lower()

        if output.startswith("```html"):
            output = output[7:]  # Remove ```json
        if output.endswith("```"):
            output = output[:-3]  # Remove ```

        return output

    except Exception as e:
        logging.error(f"Error generating code: {e}")
        return f"Error generating code: {e}"

def update_code(existing_code, instruction, email="service@codsy.ai"):
    """
    Modify the provided code intelligently based on a high-level natural language instruction.
    
    Args:
        existing_code (str): Current code.
        instruction (str): Instruction for modification.
        email (str): Email of the user making the request, for API key lookup.
        
    Returns:
        str: Updated code after modifications.
    """
    # Get API key for this email
    api_key = get_groq_api_key(email)
    if not api_key:
        logging.error("No GROQ API key available. Cannot update code.")
        return "update_code_error"

    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.5, api_key=api_key)
        prompt_template = PromptTemplate(
            template="""You are an expert programmer and code refiner.
        Analyze the provided code and modify it according to the instruction.
        Your response must contain only the final, updated code without any explanations or additional text.
        For HTML files, ensure all CSS and JavaScript is properly embedded within the HTML file itself.
        Make sure all paths and resources are relative and self-contained.
        Create complete, standalone files that will work in a Docker container environment.

        Current code: {existing_code}
        Instruction: {instruction}""",
        input_variables=["existing_code", "instruction"],
        )
        
        prompt = prompt_template.format(existing_code=existing_code, instruction=instruction)
        response = llm.invoke(prompt)
        
        updated_code = response.content.strip()

        if updated_code.startswith("```html"):
            updated_code = updated_code[7:]  # Remove ```json
        if updated_code.endswith("```"):
            updated_code = updated_code[:-3]  # Remove ```

        return updated_code
    except Exception as e:
        logger.error(f"Error in intelligent_code_modifier: {e}")
        #return f"Sorry, I encountered an error while modifying the code: {e}"

def update_existing_code(repo_name, file_path, instruction):
    """
    Modify a file from the local GitHub repo based on natural language instruction.
    
    Args:
        repo_name (str): Repository name (should already be cloned).
        file_path (str): Path to the file inside the repo.
        instruction (str): High-level natural language instruction.
        
    Returns:
        dict: Result containing success status and message.
    """
    try:
        repo_dir = f"./{sanitize_repo_name(repo_name)}"
        full_path = os.path.join(repo_dir, file_path)

        if not os.path.exists(full_path):
            print(f"File '{file_path}' does not exist in '{repo_dir}'.")
        
        with open(full_path, "r", encoding="utf-8") as f:
            existing_code = f.read()

        updated_code = update_code(existing_code, instruction)

        #with open(full_path, "w", encoding="utf-8") as f:
         #   f.write(updated_code)

        commit_changes(repo_name, file_path,"1st commit", updated_code)
        push_changes(repo_name)
        url = None # Initialize url
        if file_path.strip().lower().endswith(".html"):
            url = f"{PREVIEW_SERVER_URL}:{PREVIEW_SERVER_PORT}/{repo_name}/{file_path}"
        
        message_content = f"File '{file_path}' generated from prompt and pushed."
        if url:
            message_content += f"\n:globe_with_meridians: Live Preview: {url}"
            
        return {
            "success": True,
            "message": message_content
        }
    except Exception as e:
        logger.error(f"Error in update_existing_code : {e}")
        #return {"success": False, "message": f"Error: {e}"}




# ------------------ Workflow Functions ------------------


def generate_filename_from_code(
    code: str,
    prompt: str = None,
    extension: str = None
) -> str:
    """
    Generate a filename based on the code's main heading or title, or from the prompt.
    Falls back to timestamp+hash if nothing meaningful is found.
    
    Args:
        code:       The generated code (HTML, Python, etc.)
        prompt:     The original user prompt (optional)
        extension:  File extension (e.g. "html", "py"); inferred if not provided.
    """
    # 1) Try to infer extension from code content
    if not extension:
        lc = code.lower()
        if "<html" in lc or "<!doctype html" in lc:
            extension = "html"
        elif "def " in code or "import " in code:
            extension = "py"
        elif "class " in code and "{" in code:
            extension = "css"
        else:
            extension = "txt"

    # 2) Try to extract a main word from <title> or <h1> tags
    title_match = re.search(r"<title>([^<]+)</title>", code, re.IGNORECASE)
    h1_match    = re.search(r"<h1>([^<]+)</h1>", code, re.IGNORECASE)

    if title_match:
        base = title_match.group(1)
    elif h1_match:
        base = h1_match.group(1)
    # 3) Else, try to extract quoted phrase from the prompt
    elif prompt:
        # look for "…" or "…"
        m = re.search(r'"([^"]+)"', prompt) or re.search(r'"([^"]+)"', prompt)
        base = m.group(1) if m else prompt
    else:
        base = None

    # 4) Sanitize the base name
    if base:
        base = sanitize_basename(base)
    else:
        base = None

    # 5) Fallback to timestamp+hash if no base
    if not base:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        hash6 = hashlib.md5(code.encode()).hexdigest()[:6]
        base = f"file_{ts}_{hash6}"

    return f"{base}.{extension}"

def generate_and_push_code(repo_name: str,
                           filename: str,
                           prompt: str,
                           branch_name: str = "main"):
    
    """"You are a GitHub automation agent. "
    "When writing code into files, oulytput **on** the code content—no extra text, comments, or instructions. "
    "Use the available function tools (`write_code_to_file`, `commit_changes`, `push_changes`) to save, commit, and push.
    "IMPORTANT: The output must ALWAYS be a single .html file with all HTML, CSS, JavaScript, and assets fully contained.
    Do not use any external libraries or files."
    """

    # 1) Generate the code
    generated_code = generate_code(prompt)

    # 2) Auto-generate filename if needed
    if not filename:
        filename = generate_filename_from_code(generated_code)  # infers extension

    # 3) Prepare local clone
    safe = sanitize_repo_name(repo_name)
    local_dir = os.path.join(".", safe)
    if not os.path.exists(local_dir):
        clone_res = clone_repo(repo_name)
        if not clone_res.get("success"):
            return clone_res

    # 4) Checkout branch (create if needed)
    repo = Repo(local_dir)
    try:
        repo.git.checkout(branch_name)
    except GitCommandError:
        repo.git.checkout("-b", branch_name)
        repo.git.push("--set-upstream", "origin", branch_name)

    # 5) Write code to file
    full_path = os.path.join(local_dir, filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(generated_code)

    # 6) Commit changes
    try:
        commit_changes(repo_name, filename,
                       f"Initial commit via generate_and_push_code: {prompt}",
                       generated_code)
    except Exception as e:
        return {"success": False, "message": f"Error committing changes: {e}"}

    # 7) Push to GitHub
    push_res = push_changes(repo_name)
    url = None # Initialize url
    if filename.strip().lower().endswith(".html"):
        url = f"{PREVIEW_SERVER_URL}:{PREVIEW_SERVER_PORT}/{repo_name}/{filename}"
    
    message_content = (
        f"File '{filename}' generated from prompt and pushed to "
        f"branch '{branch_name}' in repo '{repo_name}'."
    )
    if url:
        message_content += f"\n:globe_with_meridians: Live Preview: {url}"
        
    return {
        "success": True,
        "message": message_content
    }

def intelligent_code_modifier(current_code: str, instruction: str, email="service@codsy.ai") -> str:
    """
    Uses Groq LLM to intelligently update existing code based on an instruction.
    The model receives full context and should only apply the specified change.
    
    Modify the provided code intelligently based on a high-level natural language instruction.
    
    Args:
        current_code (str): Current code.
        instruction (str): Instruction for modification.
        email (str): Email of the user making the request, for API key lookup.
        
    Returns:
        str: Updated code after modifications.
    """
    # Get API key for this email
    api_key = get_groq_api_key(email)
    if not api_key:
        logging.error("No GROQ API key available. Cannot modify code.")
        return "identify_function_error"
    
    try:
        llm = ChatGroq(model="llama3-70b-8192", temperature=0.5, api_key=api_key)
        prompt = PromptTemplate(
            template = """
        "You are an expert programmer and code refiner."
        "Analyze the provided code and modify it according to the instruction."
        " Output ONLY valid executable code. DO NOT explain anything. "
        "DO NOT describe your process. DO NOT add quotation marks, formatting, language identifiers, or any human text."
        Here is the current code:{current_code}
        Modify it as per the following instruction:{instruction}
        Provide only the final updated code.""",
        input_variables=["current_code", instruction],
        )


        formatted_prompt = prompt.format(current_code=current_code,instruction=instruction )
        response = llm.generate(formatted_prompt)
        return  response.content.strip().lower()

    except Exception as e:
        return f"<!-- Error from Groq LLM: {str(e)} -->\n\n{current_code}"
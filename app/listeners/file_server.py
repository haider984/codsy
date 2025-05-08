import os
import time
import http.server
import socketserver
import threading
from app.celery_app import celery_app

# Get base directory for serving files
BASE_DIR = os.getenv("GITHUB_REPOS_DIR", "./")  # Default to current directory
PORT = int(os.getenv("PREVIEW_SERVER_PORT"))

class GitHubRepoHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler that serves files from repo directory"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)
    
    def log_message(self, format, *args):
        print(f"[File Server] {format % args}")

def start_http_server():
    """Start the HTTP server in a separate thread"""
    handler = GitHubRepoHandler
    
    with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"🌐 Serving GitHub repos at http://0.0.0.0:{PORT}")
        httpd.serve_forever()

# Start HTTP server in a separate thread
server_thread = threading.Thread(target=start_http_server, daemon=True)

@celery_app.task(name='app.listeners.file_server.keep_alive')
def keep_alive():
    """Simple task to keep the file server container running"""
    return "File server is running"

def start_server():
    """Start the server thread if not already running"""
    if not server_thread.is_alive():
        server_thread.start()
    return "File server started"

# Start the server when this module is loaded
start_server()

if __name__ == "__main__":
    # For running directly (not as a Celery task)
    start_server()
    while True:
        time.sleep(60)  # Keep main thread alive
import os
from celery import Celery
# from dotenv import load_dotenv # Removed if using Docker env vars

# load_dotenv()

# Get broker URL - essential
# Make sure CELERY_BROKER_URL=redis://redis:6379/0 is in the .env file
broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0') # Keep default just in case
backend_url = os.getenv('CELERY_RESULT_BACKEND', broker_url)

print(f"--- [celery_app.py] Initializing Celery app with broker: {broker_url} ---")

# Minimal Celery App definition
celery_app = Celery(
    'tasks', # Application name
    broker=broker_url,
    backend=backend_url,
    # Ensure include points to the correct module where email.py resides
    include=['app.listeners.email']
)

print("--- [celery_app.py] Celery app initialized ---")

# Restore configurations if they were removed
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

celery_app.conf.task_routes = {
    'app.listeners.email.poll_inbox_task': {'queue': 'email_queue'},
}

celery_app.conf.beat_schedule = {
    'poll-email-every-30-seconds': { # Adjust interval as needed
        'task': 'app.listeners.email.poll_inbox_task',
        'schedule': 30.0, # e.g., every 30 seconds
    },
}

# Keep this for direct execution if needed, but Docker uses the command line
if __name__ == '__main__':
    print("--- [celery_app.py] Running as main script ---")
    celery_app.start()
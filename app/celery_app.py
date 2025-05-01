import os
from celery import Celery
from dotenv import load_dotenv

# Load .env file if it exists (useful for local development outside Docker)
load_dotenv()

# Get the broker URL from environment variable set in docker-compose
broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0') # Default for local dev
# Get the internal API URL for workers
internal_api_url = os.getenv("INTERNAL_BASE_API_URL", "http://web:8000")

# Define the Celery application instance
# The first argument is the name of the current module, useful for automatic task discovery
# The 'broker' argument points to our Redis instance
# The 'backend' argument is optional, used if you need to store task results (not strictly needed for this listener)
# Include specifies where Celery should look for task definitions
celery_app = Celery(
    'tasks', # Can be any name, often the project name
    broker=broker_url,
    backend=broker_url, # Using Redis as backend too (optional)
    # Include both email and slack listener modules
    include=['app.listeners.email', 'app.listeners.slack']
)

# Optional configuration settings
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],  # Ensure tasks use JSON
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Pass the internal API URL to tasks if needed via configuration
    # This isn't standard, passing via task args or env var is more common
    # worker_hijack_root_logger=False, # Might be needed depending on logging setup
    # Optional: configure result backend expiration if you store results
    # result_expires=3600,
)

# Optional: Add routing for specific tasks to specific queues
# This ensures our email task goes to the 'email_queue' that our workers listen to
celery_app.conf.task_routes = {
    'app.listeners.email_listener.poll_inbox_task': {'queue': 'email_queue'},
    'app.listeners.slack.process_slack_message_task': {'queue': 'slack_queue'},
    # Add routes for other tasks if needed
}

# Add Celery Beat schedule
celery_app.conf.beat_schedule = {
    'poll-email-every-5-seconds': { # A descriptive name for the schedule entry
        'task': 'app.listeners.email_listener.poll_inbox_task', # The name of the task to run
        'schedule': 5.0, # Run every 30 seconds
        'options': {'queue': 'email_queue'} # Ensure scheduled task goes to the right queue
    },
    # Add other scheduled tasks here if needed
}

if __name__ == '__main__':
    # This allows running the worker directly using: python -m app.celery_app worker ...
    celery_app.start()
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
    # Include all listener modules
    include=[
        'app.listeners.email',
        'app.listeners.slack',
        'app.listeners.intent_classifier',
        'app.listeners.reply',
        'app.listeners.git_jira',
        'app.listeners.reply_git_jira' # Add the new reply generator listener
    ]
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
# Define a new queue for the git/jira tasks
celery_app.conf.task_routes = {
    'app.listeners.email.poll_inbox_task': {'queue': 'email_queue'},
    'app.listeners.slack.process_slack_message_task': {'queue': 'slack_queue'},
    'app.listeners.intent_classifier.process_unprocessed_messages_task': {'queue': 'classifier_queue'},
    'app.listeners.reply.send_pending_replies_task': {'queue': 'reply_queue'},
    'app.listeners.git_jira.process_git_jira_tasks': {'queue': 'git_jira_queue'},
    'app.listeners.reply_git_jira.process_messages_for_reply': {'queue': 'reply_git_jira_queue'}, # Route new task
    # Add routes for other tasks if needed
}

# Add Celery Beat schedule
celery_app.conf.beat_schedule = {
    'poll-email-every-5-seconds': { # A descriptive name for the schedule entry
        'task': 'app.listeners.email.poll_inbox_task', # Changed from 'email_listener' to 'email'
        'schedule': 5.0, # Run every 5 seconds
        'options': {'queue': 'email_queue'} # Ensure scheduled task goes to the right queue
    },
    'classify-messages-every-10-seconds': { # Keep classifier less frequent due to rate limits
        'task': 'app.listeners.intent_classifier.process_unprocessed_messages_task',
        'schedule': 10.0,
        'options': {'queue': 'classifier_queue'}
    },
    'send-replies-every-5-seconds': { # Descriptive name
        'task': 'app.listeners.reply.send_pending_replies_task',
        'schedule': 5.0, # Run every 5 seconds
        'options': {'queue': 'reply_queue'} # Route scheduled task to the correct queue
    },
    'process-git-jira-tasks-every-10-seconds': { # Schedule for the new task
        'task': 'app.listeners.git_jira.process_git_jira_tasks',
        'schedule': 10.0, # Run every 10 seconds
        'options': {'queue': 'git_jira_queue'} # Route to its dedicated queue
    },
    'process-messages-for-reply-every-5-seconds': { # Schedule for the new reply generator task
        'task': 'app.listeners.reply_git_jira.process_messages_for_reply',
        'schedule': 5.0, # Run every 10 seconds
        'options': {'queue': 'reply_git_jira_queue'} # Route to its dedicated queue
    },
    # Add other scheduled tasks here if needed
}

if __name__ == '__main__':
    # This allows running the worker directly using: python -m app.celery_app worker ...
    celery_app.start()
from fastapi import FastAPI
from contextlib import asynccontextmanager
from .db.mongodb import close_mongo_connection, connect_to_mongo
# Make sure you import any routers you have defined, e.g.:
# from .routers import items
from .core.config import settings # Import settings

# Import ALL your router modules
from .routers import (
    projects, sessions, gittasks,
    jiratasks, feedbacks, meetings, users, messages
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Actions on startup
    print("Starting up...")
    await connect_to_mongo()
    # Modified print statement - Avoid accessing .port for SRV URIs
    # Extracts host from the raw URL string for logging
    host_part = settings.MONGODB_URL.split('@')[-1].split('/')[0]
    print(f"Connection to MongoDB host {host_part} initiated.")
    yield
    # Actions on shutdown
    print("Shutting down...")
    await close_mongo_connection()
    print("MongoDB connection closed.")

app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0", lifespan=lifespan)

# Include ALL routers
# app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(gittasks.router, prefix="/api/v1/gittasks", tags=["Git Tasks"])
app.include_router(jiratasks.router, prefix="/api/v1/jiratasks", tags=["Jira Tasks"])
app.include_router(feedbacks.router, prefix="/api/v1/feedbacks", tags=["Feedbacks"])
app.include_router(meetings.router, prefix="/api/v1/meetings", tags=["Meetings"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(messages.router, prefix="/api/v1/messages", tags=["Messages"])

@app.get("/")
async def root():
    """Root endpoint providing basic info."""
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

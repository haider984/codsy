import motor.motor_asyncio
from ..core.config import settings
from contextlib import contextmanager, asynccontextmanager
from urllib.parse import urlparse

class DataBase:
    client: motor.motor_asyncio.AsyncIOMotorClient | None = None
    db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None

db = DataBase()

async def get_database() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    if db.db is None:
        raise Exception("Database not initialized. Call connect_to_mongo first.")
    return db.db

async def connect_to_mongo():
    """Connects to MongoDB using the URL from settings."""
    print(f"Attempting to connect to MongoDB...")
    try:
        connection_string = str(settings.MONGODB_URL)
        db.client = motor.motor_asyncio.AsyncIOMotorClient(
            connection_string,
            # Optional: Add server selection timeout if needed
            # serverSelectionTimeoutMS=5000
        )

        parsed_uri = urlparse(connection_string)
        db_name = parsed_uri.path.lstrip('/')
        if not db_name:
            db_name = "codsy"
            print(f"No database name found in MONGODB_URL path, using default: {db_name}")

        db.db = db.client[db_name]

        print(f"Pinging MongoDB server...")
        await db.client.admin.command('ping')
        print(f"Successfully connected to MongoDB database: {db_name}")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        raise

async def close_mongo_connection():
    """Closes the MongoDB connection."""
    if db.client:
        print("Closing MongoDB connection...")
        db.client.close()
        db.client = None
        db.db = None
        print("MongoDB connection closed.")

# --- Example Usage in Routers/Services ---
# async def get_item_collection():
#     database = await get_database()
#     return database.get_collection("items")

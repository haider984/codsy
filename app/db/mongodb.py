import motor.motor_asyncio
from ..core.config import settings
from contextlib import contextmanager, asynccontextmanager
from urllib.parse import urlparse
import logging

# Get logger for this module
mongo_logger = logging.getLogger(__name__)
if not mongo_logger.handlers:
     # Configure basic logging if not already configured by Celery/FastAPI
     # Consider using Celery's logger setup if preferred for consistency
     logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

class DataBase:
    client: motor.motor_asyncio.AsyncIOMotorClient | None = None
    db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None

db = DataBase()

async def get_database() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    mongo_logger.info(">>> get_database CALLED")
    if db.db is None:
        mongo_logger.warning(">>> Database object is None, attempting connection...")
        try:
            await connect_to_mongo()
            if db.db is None:
                mongo_logger.error(">>> Connection attempted, but database object still None.")
                raise Exception("Database initialization failed after explicit connection attempt.")
            mongo_logger.info(">>> Connection successful after explicit attempt in get_database.")
        except Exception as e:
            mongo_logger.error(f">>> Exception during connect_to_mongo called from get_database: {e}", exc_info=True)
            raise # Re-raise the exception
    mongo_logger.info(f">>> Returning database object: {db.db.name if db.db else 'None'}")
    return db.db

def get_collection(
    database: motor.motor_asyncio.AsyncIOMotorDatabase, collection_name: str
) -> motor.motor_asyncio.AsyncIOMotorCollection:
    """Helper function to get a collection from the database object."""
    mongo_logger.debug(f">>> Getting collection: {collection_name}")
    return database.get_collection(collection_name)

async def connect_to_mongo():
    """Connects to MongoDB using the URL from settings."""
    mongo_logger.info(">>> connect_to_mongo CALLED")
    # Prevent reconnecting if already connected
    if db.client and db.db:
        try:
            mongo_logger.debug(">>> Pinging existing MongoDB connection...")
            await db.client.admin.command('ping')
            mongo_logger.debug(">>> Ping successful, connection already exists.")
            return
        except Exception as e:
            mongo_logger.warning(f">>> Connection ping failed: {e}. Attempting to reconnect...")
            await close_mongo_connection() # Close broken connection before reconnecting

    mongo_logger.info(f">>> Attempting new connection to MongoDB...")
    try:
        connection_string = str(settings.MONGODB_URL)
        mongo_logger.info(f">>> Using connection string (check if sensitive): {connection_string[:15]}...")
        db.client = motor.motor_asyncio.AsyncIOMotorClient(
            connection_string,
            serverSelectionTimeoutMS=5000 # Add a timeout
        )

        parsed_uri = urlparse(connection_string)
        db_name = parsed_uri.path.lstrip('/')
        if not db_name:
            db_name = "codsy" # Default from your previous code
            mongo_logger.warning(f">>> No database name in URL path, using default: {db_name}")

        db.db = db.client[db_name]

        mongo_logger.info(f">>> Pinging MongoDB server for new connection...")
        await db.client.admin.command('ping')
        mongo_logger.info(f">>> Successfully connected to MongoDB database: {db_name}")
    except Exception as e:
        mongo_logger.error(f">>> Error connecting to MongoDB: {e}", exc_info=True)
        db.client = None
        db.db = None
        raise

async def close_mongo_connection():
    """Closes the MongoDB connection."""
    if db.client:
        mongo_logger.info(">>> Closing MongoDB connection...")
        db.client.close()
        db.client = None
        db.db = None
        mongo_logger.info(">>> MongoDB connection closed.")

# --- Example Usage (Now Correct) ---
async def get_item_collection():
     database = await get_database()
     # Now this works because get_collection is defined in this module
     return get_collection(database, "items")

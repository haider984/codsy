from pydantic_settings import BaseSettings, SettingsConfigDict
# Remove MongoDsn import if not used elsewhere
# from pydantic import MongoDsn, Field
from pydantic import Field # Keep Field if used by other models
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "FastAPI MongoDB Project"
    MONGODB_URL: str # Changed from MongoDsn

    # Optional: Define other settings your app might need
    # API_V1_STR: str = "/api/v1"

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

settings = Settings()

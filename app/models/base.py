from __future__ import annotations

# app/models/base.py (or define in each model file)
from pydantic import (
    BaseModel, Field, ConfigDict,
    GetCoreSchemaHandler, GetJsonSchemaHandler
)
from pydantic_core import core_schema
from bson import ObjectId
from datetime import datetime
from typing import List, Optional, Any

class PyObjectId(ObjectId):
    """
    Custom Pydantic type for MongoDB ObjectId
    """
    @classmethod
    def validate(cls, v: Any, _: core_schema.ValidationInfo) -> ObjectId:
        """Validate input during parsing"""
        if isinstance(v, ObjectId):
            return v
        if ObjectId.is_valid(v):
            return ObjectId(v)
        # You could raise PydanticCustomError here for better error reporting
        raise ValueError("Invalid ObjectId")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """
        Define the core schema for ObjectId handling.
        Validates from Python ObjectId/str and JSON str, serializes to str.
        """
        from_python_schema = core_schema.with_info_plain_validator_function(cls.validate)

        # Define how to handle input specifically from JSON (expects a string)
        # We still use our validate function as it handles string conversion
        from_json_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(), # Expect a string from JSON
                from_python_schema,       # Then run our validation
            ]
        )

        return core_schema.json_or_python_schema(
            python_schema=from_python_schema, # How to validate from Python objects
            json_schema=from_json_schema,     # How to validate from JSON strings
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: str(instance) # Always serialize to string
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        """
        Explicitly define the JSON schema representation (a string).
        This overrides the generator's attempt to infer from the core schema's validator.
        """
        # Report the schema as a simple string type
        return {
            "type": "string",
            "format": "objectid", # Custom format identifier
            "example": "60c72b2f9b1e8a3f4c8a1b2c" # Example ObjectId string
        }

# Common Model Config for handling MongoDB _id and ObjectId serialization
common_config = ConfigDict(
    populate_by_name=True,
    arbitrary_types_allowed=True,
    json_encoders={ObjectId: str} # Add this for Pydantic v2, or if PyObjectId serialization isn't fully handling it
)

class BaseDocument(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id") # Use default=None for optional _id before creation
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = common_config

    # Optional: Add a pre-save hook to update `updated_at` if you're not using a database-level timestamp
    # This would require a custom save method or integration with an ODM like Beanie/MongoEngine
    # For Pydantic models used with Motor, this logic is usually handled in service layers before update operations.
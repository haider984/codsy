from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Path, HTTPException, status

def validate_object_id_sync(id_str: str) -> ObjectId:
    """
    Helper function to convert an ID string to a BSON ObjectId.
    Raises HTTPException 400 if the ID string is invalid.
    """
    if not id_str or not isinstance(id_str, str):
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID must be a non-empty string"
        )
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ObjectId format: {id_str}"
        )
    except Exception as e: # Catch other potential errors during conversion
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error converting ID: {e}"
        )

async def validate_object_id(id_str: str = Path(..., description="MongoDB ObjectId as a string")) -> ObjectId:
    """
    Dependency to convert any path parameter string to a BSON ObjectId.
    Raises HTTPException 400 if the ID string is invalid.
    """
    return validate_object_id_sync(id_str)

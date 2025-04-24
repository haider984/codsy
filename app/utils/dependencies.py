from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Path, HTTPException, status

async def get_object_id(id: str = Path(...)) -> ObjectId:
    """
    Dependency to convert a path parameter string to a BSON ObjectId.
    Raises HTTPException 400 if the ID is invalid.
    """
    try:
        return ObjectId(id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ObjectId format: {id}"
        )
    except Exception as e: # Catch other potential errors during conversion
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error converting ID: {e}"
        )

import uuid
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: uuid.UUID

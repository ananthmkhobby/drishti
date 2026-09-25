import uuid
from typing import Annotated
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.database import get_db
from app.exceptions import ACIError

security = HTTPBearer(auto_error=False)


async def get_current_teacher_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> uuid.UUID:
    if settings.skip_auth:
        return settings.dev_teacher_id

    if credentials is None:
        raise ACIError("UNAUTHORIZED", "Missing authorization token", 401)

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub claim")
        return uuid.UUID(sub)
    except (JWTError, ValueError):
        raise ACIError("INVALID_TOKEN", "Invalid or expired token", 401)


# Convenience type aliases for route signatures
CurrentTeacher = Annotated[uuid.UUID, Depends(get_current_teacher_id)]
DB = Annotated[AsyncSession, Depends(get_db)]

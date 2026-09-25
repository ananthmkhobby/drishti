import logging
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger(__name__)


class ACIError(Exception):
    def __init__(self, error: str, message: str, status_code: int = 400):
        self.error = error
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def aci_error_handler(request: Request, exc: ACIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "message": exc.message,
            "request_id": str(uuid.uuid4()),
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Before this handler existed, an unhandled exception (a full disk, a
    # locked SQLite database, anything not already wrapped as an ACIError)
    # fell through to Starlette's default 500 response — bare
    # "Internal Server Error" text, no request_id, and critically nothing
    # written to the server log, so a teacher reporting "sometimes upload
    # just fails" gave us no way to find out why. This gives every
    # unhandled failure the same friendly shape the frontend already knows
    # how to display, and logs the real exception (exc_info) so the actual
    # cause shows up in the backend logs instead of vanishing.
    request_id = str(uuid.uuid4())
    logger.error("Unhandled exception on %s %s [request_id=%s]", request.method, request.url.path, request_id, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "Something went wrong on our end — please try again.",
            "request_id": request_id,
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    message = first.get("msg", "Validation error")
    field = " → ".join(str(l) for l in first.get("loc", []))
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "message": f"{field}: {message}" if field else message,
            "request_id": str(uuid.uuid4()),
        },
    )

from typing import Any

from fastapi.responses import JSONResponse


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the stable API error envelope used by every endpoint."""
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "fields": fields or {},
        }
    }
    return JSONResponse(status_code=status_code, content=content, headers=headers)

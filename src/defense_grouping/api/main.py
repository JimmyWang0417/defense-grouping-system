import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response

from defense_grouping.api.errors import error_response
from defense_grouping.config import Settings, get_settings

RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated FastAPI application for production or tests."""
    active_settings = settings or get_settings()
    app = FastAPI(title="答辩分组系统", version="0.1.0")
    app.state.settings = active_settings

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(404)
    async def not_found(request: Request, _exc: Exception) -> Response:
        return error_response(
            status_code=404,
            code="not_found",
            message="资源不存在",
            request_id=request.state.request_id,
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        database = (
            "sqlite"
            if active_settings.database_url.startswith("sqlite")
            else "postgresql"
        )
        return {"status": "ok", "database": database}

    return app

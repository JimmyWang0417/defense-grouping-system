import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from defense_grouping.api.errors import APIError, error_response
from defense_grouping.auth.rate_limit import LoginRateLimiter
from defense_grouping.auth.routes import router as auth_router
from defense_grouping.config import Settings, get_settings
from defense_grouping.db.session import Database

RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated FastAPI application for production or tests."""
    active_settings = settings or get_settings()
    database = Database(active_settings.database_url)

    @asynccontextmanager
    async def lifespan(active_app: FastAPI) -> AsyncIterator[None]:
        yield
        active_database = getattr(active_app.state, "database", database)
        await active_database.dispose()

    app = FastAPI(title="答辩分组系统", version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.state.database = database
    app.state.login_rate_limiter = LoginRateLimiter()

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

    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError) -> Response:
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            request_id=request.state.request_id,
            fields=exc.fields,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        fields = {
            ".".join(str(part) for part in error["loc"][1:]): str(error["msg"])
            for error in exc.errors()
        }
        return error_response(
            status_code=422,
            code="validation_error",
            message="请求数据校验失败",
            request_id=request.state.request_id,
            fields=fields,
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        database = (
            "sqlite"
            if active_settings.database_url.startswith("sqlite")
            else "postgresql"
        )
        return {"status": "ok", "database": database}

    app.include_router(auth_router)
    return app

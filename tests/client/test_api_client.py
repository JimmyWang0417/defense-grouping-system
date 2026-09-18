from collections.abc import Callable
from typing import Any

import httpx
import pytest

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.feedback import format_api_error
from defense_grouping.client.session import MemoryRefreshTokenStore


def json_response(status_code: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def error_response(
    status_code: int,
    *,
    code: str,
    message: str,
    request_id: str,
    fields: dict[str, str] | None = None,
) -> httpx.Response:
    return json_response(
        status_code,
        {
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "fields": fields or {},
            }
        },
    )


def user_payload(*, must_change_password: bool = False) -> dict[str, Any]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "username": "academic-admin",
        "roles": ["academic_admin"],
        "department_ids": ["22222222-2222-2222-2222-222222222222"],
        "must_change_password": must_change_password,
    }


@pytest.mark.asyncio
async def test_login_and_first_password_change_rotate_tokens() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/auth/login":
            return json_response(
                200,
                {
                    "access_token": "access-one",
                    "refresh_token": "refresh-one-long-enough",
                    "token_type": "bearer",
                    "expires_in": 900,
                    "must_change_password": True,
                },
            )
        if request.url.path == "/api/v1/auth/change-password":
            assert request.headers["Authorization"] == "Bearer access-one"
            return json_response(
                200,
                {
                    "access_token": "access-two",
                    "refresh_token": "refresh-two-long-enough",
                    "token_type": "bearer",
                    "expires_in": 900,
                    "must_change_password": False,
                },
            )
        if request.url.path == "/api/v1/auth/me":
            token = request.headers["Authorization"]
            return json_response(200, user_payload(must_change_password=token.endswith("one")))
        raise AssertionError(request.url.path)

    store = MemoryRefreshTokenStore()
    client = ApiClient(
        "https://example.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    try:
        state = await client.login("academic-admin", "temporary-password")
        assert state.must_change_password is True
        assert state.roles == frozenset({"academic_admin"})
        assert store.get() == "refresh-one-long-enough"

        state = await client.change_password("temporary-password", "Permanent Password 2026")
        assert state.must_change_password is False
        assert store.get() == "refresh-two-long-enough"
        assert requests[-1].headers["Authorization"] == "Bearer access-two"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_401_refreshes_once_and_retries_original_request() -> None:
    counts = {"protected": 0, "refresh": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/protected":
            counts["protected"] += 1
            if request.headers.get("Authorization") == "Bearer renewed-access":
                return json_response(200, {"ok": True})
            return error_response(
                401,
                code="invalid_token",
                message="访问令牌无效",
                request_id="request-original",
            )
        if request.url.path == "/api/v1/auth/refresh":
            counts["refresh"] += 1
            return json_response(
                200,
                {
                    "access_token": "renewed-access",
                    "refresh_token": "renewed-refresh-long-enough",
                    "token_type": "bearer",
                    "expires_in": 900,
                    "must_change_password": False,
                },
            )
        raise AssertionError(request.url.path)

    store = MemoryRefreshTokenStore("stored-refresh-long-enough")
    client = ApiClient(
        "https://example.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await client.request("GET", "/api/v1/protected") == {"ok": True}
        assert counts == {"protected": 2, "refresh": 1}
        assert store.get() == "renewed-refresh-long-enough"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failed_refresh_clears_session_without_retry_loop() -> None:
    counts = {"protected": 0, "refresh": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/protected":
            counts["protected"] += 1
            return error_response(
                401,
                code="invalid_token",
                message="访问令牌无效",
                request_id="request-original",
            )
        counts["refresh"] += 1
        return error_response(
            401,
            code="invalid_refresh_token",
            message="刷新令牌无效",
            request_id="request-refresh",
        )

    store = MemoryRefreshTokenStore("stored-refresh-long-enough")
    client = ApiClient(
        "https://example.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ApiError) as captured:
            await client.request("GET", "/api/v1/protected")
        assert captured.value.code == "invalid_token"
        assert counts == {"protected": 1, "refresh": 1}
        assert store.get() is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_logout_clears_access_and_refresh_tokens_even_if_network_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    store = MemoryRefreshTokenStore("stored-refresh-long-enough")
    client = ApiClient(
        "https://example.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    client.set_access_token("access")
    with pytest.raises(ApiError, match="网络连接失败"):
        await client.logout()
    assert store.get() is None
    assert client.access_token is None
    await client.close()


@pytest.mark.asyncio
async def test_field_error_and_request_id_are_preserved_for_display() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return error_response(
            422,
            code="validation_error",
            message="请求数据校验失败",
            request_id="req-field-001",
            fields={"username": "字段不能为空"},
        )

    client = ApiClient(
        "https://example.test",
        token_store=MemoryRefreshTokenStore(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ApiError) as captured:
            await client.request("POST", "/api/v1/example", json={})
        assert captured.value.fields == {"username": "字段不能为空"}
        assert "req-field-001" in format_api_error(captured.value)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_factory", "expected_code", "expected_message"),
    [
        (
            lambda request: httpx.ReadTimeout("slow", request=request),
            "network_timeout",
            "请求超时",
        ),
        (
            lambda request: httpx.ConnectError("offline", request=request),
            "network_error",
            "网络连接失败",
        ),
    ],
)
async def test_network_errors_are_stable_api_errors(
    exception_factory: Callable[[httpx.Request], Exception],
    expected_code: str,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_factory(request)

    client = ApiClient(
        "https://example.test",
        token_store=MemoryRefreshTokenStore(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ApiError) as captured:
            await client.request("GET", "/api/v1/example")
        assert captured.value.code == expected_code
        assert expected_message in captured.value.message
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_refuses_paths_outside_versioned_api() -> None:
    client = ApiClient(
        "https://example.test",
        token_store=MemoryRefreshTokenStore(),
        transport=httpx.MockTransport(lambda _request: json_response(200, {})),
    )
    try:
        with pytest.raises(ValueError, match="/api/v1"):
            await client.request("GET", "/internal")
    finally:
        await client.close()

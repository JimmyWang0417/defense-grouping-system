from __future__ import annotations

from typing import Any

import httpx

from defense_grouping.client.session import RefreshTokenStore, SessionState


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        request_id: str,
        fields: dict[str, str] | None = None,
        *,
        status_code: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.fields = fields or {}
        self.status_code = status_code


class ApiClient:
    """Versioned async API client with one-shot refresh and stable errors."""

    def __init__(
        self,
        base_url: str,
        *,
        token_store: RefreshTokenStore,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=timeout,
        )
        self._token_store = token_store
        self._access_token: str | None = None

    @property
    def access_token(self) -> str | None:
        return self._access_token

    def set_access_token(self, token: str | None) -> None:
        self._access_token = token

    async def close(self) -> None:
        await self._flush_token_store()
        await self._client.aclose()

    def clear_tokens(self) -> None:
        self._access_token = None
        self._token_store.clear()

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._validate_path(path)
        response = await self._send(method, path, **kwargs)
        if response.status_code == 401 and self._token_store.get() is not None:
            original_response = response
            if await self._refresh():
                response = await self._send(method, path, **kwargs)
            else:
                self._raise_for_error(original_response)
        self._raise_for_error(response)
        if response.status_code == 204:
            return {}
        return self._json_object(response)

    async def request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        self._validate_path(path)
        response = await self._send(method, path, **kwargs)
        if response.status_code == 401 and self._token_store.get() is not None:
            original_response = response
            if await self._refresh():
                response = await self._send(method, path, **kwargs)
            else:
                self._raise_for_error(original_response)
        self._raise_for_error(response)
        return response.content

    async def request_list(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self._validate_path(path)
        response = await self._send(method, path, **kwargs)
        if response.status_code == 401 and self._token_store.get() is not None:
            original_response = response
            if await self._refresh():
                response = await self._send(method, path, **kwargs)
            else:
                self._raise_for_error(original_response)
        self._raise_for_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(
                "invalid_api_response",
                "服务返回了无法解析的响应",
                response.headers.get("X-Request-ID", "-"),
                status_code=502,
            ) from exc
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ApiError(
                "invalid_api_response",
                "服务返回了无效的列表",
                response.headers.get("X-Request-ID", "-"),
                status_code=502,
            )
        return payload

    async def login(
        self,
        username: str,
        password: str,
        *,
        device_info: str | None = None,
    ) -> SessionState:
        self.clear_tokens()
        await self._flush_token_store()
        response = await self._send(
            "POST",
            "/api/v1/auth/login",
            json={"username": username, "password": password, "device_info": device_info},
        )
        self._raise_for_error(response)
        self._apply_token_pair(self._json_object(response))
        await self._flush_token_store()
        try:
            return await self.current_user()
        except Exception:
            self.clear_tokens()
            raise

    async def bootstrap(self) -> SessionState:
        if self._token_store.get() is None or not await self._refresh():
            return SessionState()
        try:
            return await self.current_user()
        except ApiError:
            self.clear_tokens()
            return SessionState()

    async def current_user(self) -> SessionState:
        payload = await self.request("GET", "/api/v1/auth/me")
        try:
            return SessionState.from_payload(payload)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "invalid_api_response",
                str(exc),
                "-",
                status_code=502,
            ) from exc

    async def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> SessionState:
        response = await self.request(
            "POST",
            "/api/v1/auth/change-password",
            json={
                "current_password": current_password,
                "new_password": new_password,
            },
        )
        self._apply_token_pair(response)
        await self._flush_token_store()
        return await self.current_user()

    async def logout(self) -> None:
        refresh_token = self._token_store.get()
        try:
            if refresh_token is not None:
                response = await self._send(
                    "POST",
                    "/api/v1/auth/logout",
                    json={"refresh_token": refresh_token},
                )
                self._raise_for_error(response)
        finally:
            self.clear_tokens()
            await self._flush_token_store()

    async def _refresh(self) -> bool:
        refresh_token = self._token_store.get()
        if refresh_token is None:
            return False
        try:
            response = await self._send(
                "POST",
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token, "device_info": None},
                include_access_token=False,
            )
            self._raise_for_error(response)
            self._apply_token_pair(self._json_object(response))
            await self._flush_token_store()
        except ApiError:
            self.clear_tokens()
            await self._flush_token_store()
            return False
        return True

    async def _send(
        self,
        method: str,
        path: str,
        *,
        include_access_token: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        self._validate_path(path)
        headers = dict(kwargs.pop("headers", {}))
        if include_access_token and self._access_token is not None:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            return await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApiError("network_timeout", "请求超时，请稍后重试", "-") from exc
        except httpx.RequestError as exc:
            raise ApiError("network_error", "网络连接失败，请检查服务状态", "-") from exc

    def _apply_token_pair(self, payload: dict[str, Any]) -> None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ApiError(
                "invalid_api_response",
                "认证响应缺少令牌",
                "-",
                status_code=502,
            )
        self._access_token = access_token
        self._token_store.set(refresh_token)

    async def _flush_token_store(self) -> None:
        flush = getattr(self._token_store, "flush", None)
        if flush is not None:
            await flush()

    @staticmethod
    def _validate_path(path: str) -> None:
        if not path.startswith("/api/v1/") and path != "/api/v1":
            raise ValueError("客户端只允许访问 /api/v1")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(
                "invalid_api_response",
                "服务返回了无法解析的响应",
                response.headers.get("X-Request-ID", "-"),
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise ApiError(
                "invalid_api_response",
                "服务返回了无效的数据结构",
                response.headers.get("X-Request-ID", "-"),
                status_code=502,
            )
        return payload

    @classmethod
    def _raise_for_error(cls, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            payload = response.json()
            error = payload["error"]
            code = error["code"]
            message = error["message"]
            request_id = error["request_id"]
            fields = error.get("fields", {})
            if not all(isinstance(value, str) for value in (code, message, request_id)):
                raise TypeError
            if not isinstance(fields, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in fields.items()
            ):
                raise TypeError
        except (KeyError, TypeError, ValueError):
            raise ApiError(
                "http_error",
                f"服务请求失败（HTTP {response.status_code}）",
                response.headers.get("X-Request-ID", "-"),
                status_code=response.status_code,
            ) from None
        raise ApiError(
            code,
            message,
            request_id,
            fields,
            status_code=response.status_code,
        )

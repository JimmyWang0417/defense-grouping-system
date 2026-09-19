from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class RefreshTokenStore(Protocol):
    """Small synchronous boundary implemented by desktop and Web stores."""

    def get(self) -> str | None: ...

    def set(self, token: str) -> None: ...

    def clear(self) -> None: ...


class SessionStore(Protocol):
    def get(self, key: str) -> object: ...

    def set(self, key: str, value: object) -> None: ...

    def remove(self, key: str) -> None: ...


class SharedPreferencesStore(Protocol):
    async def get(self, key: str) -> str | int | float | bool | list[str] | None: ...

    async def set(self, key: str, value: str) -> bool: ...

    async def remove(self, key: str) -> bool: ...


class MemoryRefreshTokenStore:
    """In-memory store for tests and explicitly ephemeral sessions."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def get(self) -> str | None:
        return self._token

    def set(self, token: str) -> None:
        self._token = token

    def clear(self) -> None:
        self._token = None


class DesktopKeyringTokenStore:
    """Keep the desktop refresh token in the operating-system keyring."""

    def __init__(
        self,
        *,
        service_name: str = "defense-grouping-system",
        account_name: str = "refresh-token",
    ) -> None:
        self._service_name = service_name
        self._account_name = account_name

    def get(self) -> str | None:
        import keyring

        return keyring.get_password(self._service_name, self._account_name)

    def set(self, token: str) -> None:
        import keyring

        keyring.set_password(self._service_name, self._account_name, token)

    def clear(self) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self._service_name, self._account_name)
        except PasswordDeleteError:
            pass


class FletSessionTokenStore:
    """Keep Web refresh tokens only in Flet's server-side session store."""

    KEY = "defense_grouping.refresh_token"

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def get(self) -> str | None:
        value = self._store.get(self.KEY)
        return value if isinstance(value, str) else None

    def set(self, token: str) -> None:
        self._store.set(self.KEY, token)

    def clear(self) -> None:
        try:
            self._store.remove(self.KEY)
        except KeyError:
            pass


class BrowserRefreshTokenStore:
    """Persist only the rotating refresh token in this browser profile."""

    KEY = "defense_grouping.refresh_token"

    def __init__(
        self,
        preferences: SharedPreferencesStore,
        token: str | None,
    ) -> None:
        self._preferences = preferences
        self._token = token
        self._dirty = False

    @classmethod
    async def create(cls, preferences: SharedPreferencesStore) -> BrowserRefreshTokenStore:
        store = cls(preferences, None)
        await store.load()
        return store

    async def load(self) -> None:
        stored = await self._preferences.get(self.KEY)
        self._token = stored if isinstance(stored, str) else None
        self._dirty = False

    def get(self) -> str | None:
        return self._token

    def set(self, token: str) -> None:
        self._token = token
        self._dirty = True

    def clear(self) -> None:
        self._token = None
        self._dirty = True

    async def flush(self) -> None:
        if not self._dirty:
            return
        token = self._token
        if token is None:
            await self._preferences.remove(self.KEY)
        else:
            await self._preferences.set(self.KEY, token)
        self._dirty = False


@dataclass
class SessionState:
    user_id: str | None = None
    username: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    department_ids: frozenset[str] = field(default_factory=frozenset)
    must_change_password: bool = False
    selected_activity_id: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.user_id is not None

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> SessionState:
        raw_user_id = payload.get("id")
        raw_username = payload.get("username")
        raw_roles = payload.get("roles")
        raw_departments = payload.get("department_ids")
        if not isinstance(raw_user_id, str) or not isinstance(raw_username, str):
            raise TypeError("当前用户响应缺少身份字段")
        if not isinstance(raw_roles, list) or not all(isinstance(role, str) for role in raw_roles):
            raise TypeError("当前用户响应包含无效角色")
        if not isinstance(raw_departments, list) or not all(
            isinstance(department, str) for department in raw_departments
        ):
            raise TypeError("当前用户响应包含无效院系范围")
        return cls(
            user_id=raw_user_id,
            username=raw_username,
            roles=frozenset(raw_roles),
            department_ids=frozenset(raw_departments),
            must_change_password=payload.get("must_change_password") is True,
        )

    def clear(self) -> None:
        self.user_id = None
        self.username = None
        self.roles = frozenset()
        self.department_ids = frozenset()
        self.must_change_password = False
        self.selected_activity_id = None

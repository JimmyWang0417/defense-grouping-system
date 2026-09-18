from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol


class LoginRateLimitStore(Protocol):
    def retry_after(self, key: str, now: datetime, limit: int, window: timedelta) -> int | None: ...

    def record_failure(self, key: str, now: datetime, window: timedelta) -> None: ...

    def clear(self, key: str) -> None: ...


class InMemoryLoginRateLimitStore:
    def __init__(self) -> None:
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def _prune(self, key: str, now: datetime, window: timedelta) -> deque[datetime]:
        failures = self._failures[key]
        cutoff = now - window
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def retry_after(self, key: str, now: datetime, limit: int, window: timedelta) -> int | None:
        failures = self._prune(key, now, window)
        if len(failures) < limit:
            return None
        remaining = int((failures[0] + window - now).total_seconds())
        return max(1, remaining)

    def record_failure(self, key: str, now: datetime, window: timedelta) -> None:
        self._prune(key, now, window).append(now)

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


class LoginRateLimiter:
    def __init__(
        self,
        store: LoginRateLimitStore | None = None,
        *,
        limit: int = 5,
        window: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store or InMemoryLoginRateLimitStore()
        self.limit = limit
        self.window = window
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def key(username: str, client_ip: str) -> str:
        return f"{username.strip().casefold()}|{client_ip}"

    def retry_after(self, username: str, client_ip: str) -> int | None:
        return self.store.retry_after(self.key(username, client_ip), self.clock(), self.limit, self.window)

    def record_failure(self, username: str, client_ip: str) -> None:
        self.store.record_failure(self.key(username, client_ip), self.clock(), self.window)

    def clear(self, username: str, client_ip: str) -> None:
        self.store.clear(self.key(username, client_ip))

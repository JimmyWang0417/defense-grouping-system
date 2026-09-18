import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

password_hash = PasswordHash.recommended()


class InvalidTokenError(ValueError):
    """Raised when an access token is expired, malformed, or has the wrong type."""


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hash.verify(password, encoded)
    except PwdlibError:
        return False


def create_access_token(
    subject: str,
    secret: str,
    minutes: int = 15,
    *,
    expires_delta: timedelta | None = None,
    password_change_required: bool = False,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=minutes))
    return jwt.encode(
        {
            "sub": subject,
            "type": "access",
            "iat": now,
            "exp": expires_at,
            "password_change_required": password_change_required,
        },
        secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("invalid_access_token") from exc
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise InvalidTokenError("invalid_access_token")
    return payload


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def refresh_token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

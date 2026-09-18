from datetime import timedelta
from uuid import uuid4

import pytest

from defense_grouping.auth.permissions import Principal, ensure_department_access
from defense_grouping.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    new_refresh_token,
    verify_password,
)
from defense_grouping.models.identity import Role


def test_password_hash_uses_argon2_and_verifies() -> None:
    encoded = hash_password("Correct Horse Battery Staple 2026")

    assert encoded.startswith("$argon2")
    assert verify_password("Correct Horse Battery Staple 2026", encoded)
    assert not verify_password("wrong", encoded)


def test_access_token_round_trip_and_expiry() -> None:
    secret = "test-secret-with-at-least-32-characters"
    token = create_access_token("user-1", secret, minutes=15)

    assert decode_access_token(token, secret)["sub"] == "user-1"

    expired = create_access_token("user-1", secret, expires_delta=timedelta(seconds=-1))
    with pytest.raises(InvalidTokenError):
        decode_access_token(expired, secret)


def test_refresh_token_returns_only_digest_for_storage() -> None:
    raw, digest = new_refresh_token()

    assert raw != digest
    assert len(digest) == 64
    assert raw not in digest


def test_academic_admin_cannot_cross_department_scope() -> None:
    allowed_department = uuid4()
    principal = Principal(
        user_id=uuid4(),
        roles=frozenset({Role.ACADEMIC_ADMIN}),
        department_ids=frozenset({allowed_department}),
    )

    ensure_department_access(principal, allowed_department)
    with pytest.raises(PermissionError, match="department_scope_denied"):
        ensure_department_access(principal, uuid4())

from pathlib import Path

import pytest

from defense_grouping.client.router import (
    RouteDecision,
    decide_route,
    navigation_for,
)
from defense_grouping.client.session import SessionState


def state_for(*roles: str, must_change_password: bool = False) -> SessionState:
    return SessionState(
        user_id="11111111-1111-1111-1111-111111111111",
        username="test-user",
        roles=frozenset(roles),
        department_ids=frozenset(),
        must_change_password=must_change_password,
    )


def test_client_package_does_not_import_database_modules() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/defense_grouping/client").rglob("*.py")
    )
    assert "defense_grouping.db" not in source
    assert "defense_grouping.models" not in source


def test_teacher_navigation_is_read_only() -> None:
    items = navigation_for({"teacher"})
    assert [item.route for item in items] == ["/dashboard", "/my-schedule"]


def test_academic_admin_navigation_contains_workflows_but_not_system_admin() -> None:
    routes = [item.route for item in navigation_for({"academic_admin"})]
    assert routes == [
        "/dashboard",
        "/master-data",
        "/availability",
        "/imports",
        "/activities",
        "/scheduling",
        "/plans",
        "/approvals",
    ]
    assert "/system" not in routes
    assert "/audit" not in routes


def test_system_admin_navigation_contains_governance_pages() -> None:
    routes = [item.route for item in navigation_for({"system_admin"})]
    assert routes == ["/dashboard", "/master-data", "/audit", "/system"]


@pytest.mark.parametrize("path", ["/dashboard", "/master-data", "/plans"])
def test_unauthenticated_protected_route_redirects_without_rendering(path: str) -> None:
    decision = decide_route(path, SessionState())
    assert decision is RouteDecision.REDIRECT_LOGIN


def test_forbidden_route_returns_403_decision() -> None:
    assert decide_route("/system", state_for("teacher")) is RouteDecision.FORBIDDEN


def test_first_password_change_blocks_every_other_authenticated_page() -> None:
    state = state_for("academic_admin", must_change_password=True)
    assert decide_route("/dashboard", state) is RouteDecision.REDIRECT_CHANGE_PASSWORD
    assert decide_route("/change-password", state) is RouteDecision.ALLOW


def test_unknown_route_is_chinese_404() -> None:
    assert decide_route("/does-not-exist", state_for("system_admin")) is RouteDecision.NOT_FOUND

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import flet as ft

from defense_grouping.client.session import SessionState


@dataclass(frozen=True)
class NavigationItem:
    route: str
    label: str
    icon: ft.IconData
    roles: frozenset[str]


ALL_AUTHENTICATED = frozenset({"teacher", "academic_admin", "system_admin"})

NAVIGATION = (
    NavigationItem("/dashboard", "工作台", ft.Icons.DASHBOARD, ALL_AUTHENTICATED),
    NavigationItem(
        "/master-data",
        "基础数据",
        ft.Icons.PEOPLE,
        frozenset({"academic_admin", "system_admin"}),
    ),
    NavigationItem(
        "/availability",
        "可用性管理",
        ft.Icons.EVENT_BUSY,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/imports",
        "数据导入",
        ft.Icons.UPLOAD_FILE,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/activities",
        "答辩活动",
        ft.Icons.EVENT,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/scheduling",
        "自动排组",
        ft.Icons.SCHEDULE,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/plans",
        "方案管理",
        ft.Icons.VIEW_LIST,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/approvals",
        "例外审批",
        ft.Icons.FACT_CHECK,
        frozenset({"academic_admin"}),
    ),
    NavigationItem(
        "/my-schedule",
        "我的安排",
        ft.Icons.CALENDAR_MONTH,
        frozenset({"teacher"}),
    ),
    NavigationItem(
        "/audit",
        "审计中心",
        ft.Icons.POLICY,
        frozenset({"system_admin"}),
    ),
    NavigationItem(
        "/system",
        "系统管理",
        ft.Icons.ADMIN_PANEL_SETTINGS,
        frozenset({"system_admin"}),
    ),
)


class RouteDecision(StrEnum):
    ALLOW = "allow"
    REDIRECT_LOGIN = "redirect_login"
    REDIRECT_CHANGE_PASSWORD = "redirect_change_password"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"


def navigation_for(roles: set[str] | frozenset[str]) -> list[NavigationItem]:
    return [item for item in NAVIGATION if item.roles.intersection(roles)]


def _allowed_roles(path: str) -> frozenset[str] | None:
    for item in NAVIGATION:
        if item.route == path:
            return item.roles
    return None


def decide_route(path: str, session: SessionState) -> RouteDecision:
    if path == "/login":
        return RouteDecision.ALLOW
    if path == "/change-password":
        return RouteDecision.ALLOW if session.authenticated else RouteDecision.REDIRECT_LOGIN
    allowed_roles = _allowed_roles(path)
    if allowed_roles is None:
        return RouteDecision.NOT_FOUND
    if not session.authenticated:
        return RouteDecision.REDIRECT_LOGIN
    if session.must_change_password:
        return RouteDecision.REDIRECT_CHANGE_PASSWORD
    if not allowed_roles.intersection(session.roles):
        return RouteDecision.FORBIDDEN
    return RouteDecision.ALLOW

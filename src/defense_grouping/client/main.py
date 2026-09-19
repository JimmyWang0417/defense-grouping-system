from __future__ import annotations

import asyncio
import atexit
import os
import subprocess
import sys
from collections.abc import Callable
from urllib.parse import urlsplit

import flet as ft
import httpx

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.app_shell import app_shell
from defense_grouping.client.components.feedback import status_view
from defense_grouping.client.components.view_state import ActivityContext
from defense_grouping.client.router import NAVIGATION, RouteDecision, decide_route
from defense_grouping.client.session import (
    BrowserRefreshTokenStore,
    DesktopKeyringTokenStore,
    RefreshTokenStore,
    SessionState,
)
from defense_grouping.client.theme import build_theme
from defense_grouping.client.views.activity_wizard import activity_wizard_view
from defense_grouping.client.views.approvals import approvals_view
from defense_grouping.client.views.audit import audit_view
from defense_grouping.client.views.availability import availability_view
from defense_grouping.client.views.dashboard import dashboard_view, placeholder_view
from defense_grouping.client.views.imports import imports_view
from defense_grouping.client.views.login import change_password_view, login_view
from defense_grouping.client.views.master_data import master_data_view
from defense_grouping.client.views.my_schedule import my_schedule_view
from defense_grouping.client.views.plans import plans_view
from defense_grouping.client.views.scheduling import scheduling_view
from defense_grouping.client.views.system_admin import system_admin_view

LOCAL_API_URL = "http://127.0.0.1:8765"
_sidecar: subprocess.Popen[bytes] | None = None


async def _health_available(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/v1/health")
        return response.status_code == 200
    except httpx.RequestError:
        return False


def _stop_sidecar() -> None:
    global _sidecar
    if _sidecar is not None and _sidecar.poll() is None:
        _sidecar.terminate()
    _sidecar = None


def _spawn_sidecar() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "defense_grouping.api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def resolve_api_url(*, web: bool, page_url: str | None = None) -> str:
    configured = os.environ.get("DEFENSE_API_URL")
    if configured:
        return configured.rstrip("/")
    if web:
        parsed = urlsplit(page_url or "")
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        raise RuntimeError("Web 页面无法确定接口地址，请设置 DEFENSE_API_URL。")
    if await _health_available(LOCAL_API_URL):
        return LOCAL_API_URL
    global _sidecar
    _sidecar = await asyncio.to_thread(_spawn_sidecar)
    atexit.register(_stop_sidecar)
    for _attempt in range(40):
        if _sidecar.poll() is not None:
            break
        if await _health_available(LOCAL_API_URL):
            return LOCAL_API_URL
        await asyncio.sleep(0.25)
    _stop_sidecar()
    raise RuntimeError(
        "本地 API 启动失败。请检查 DEFENSE_JWT_SECRET 和数据库配置，或设置 DEFENSE_API_URL。"
    )


class ClientApplication:
    def __init__(
        self,
        page: ft.Page,
        client: ApiClient,
        session: SessionState,
    ) -> None:
        self.page = page
        self.client = client
        self.session = session
        self.activity_context = ActivityContext(session)
        self.page.on_route_change = self.render

    def render(self) -> None:
        path = self.page.route.split("?", 1)[0] or "/"
        if path == "/":
            destination = "/dashboard" if self.session.authenticated else "/login"
            self.page.navigate(destination)
            content: ft.Control = ft.ProgressRing()
        elif path == "/login":
            content = self._login()
        elif path == "/change-password":
            content = self._change_password()
        else:
            item = next((item for item in NAVIGATION if item.route == path), None)
            content = (
                self._protected_view(item.route, item.label)
                if item is not None
                else self._not_found()
            )
        self.page.clean()
        self.page.add(content)

    def _login(self) -> ft.Control:
        if self.session.authenticated:
            destination = "/change-password" if self.session.must_change_password else "/dashboard"
            self.page.navigate(destination)
            return ft.ProgressRing()
        return login_view(self.page, self.client, self.session, self.render)

    def _change_password(self) -> ft.Control:
        decision = decide_route("/change-password", self.session)
        if decision is RouteDecision.REDIRECT_LOGIN:
            self.page.navigate("/login")
            return ft.ProgressRing()
        return change_password_view(self.page, self.client, self.session, self.render)

    def _protected_view(self, path: str, label: str) -> ft.Control:
        decision = decide_route(path, self.session)
        if decision is RouteDecision.REDIRECT_LOGIN:
            self.page.navigate("/login")
            return ft.ProgressRing()
        if decision is RouteDecision.REDIRECT_CHANGE_PASSWORD:
            self.page.navigate("/change-password")
            return ft.ProgressRing()
        if decision is RouteDecision.FORBIDDEN:
            return status_view(403, "无权访问", "当前账号没有访问此页面的权限。")
        if decision is not RouteDecision.ALLOW:
            return self._not_found()
        content = self._workflow_content(path, label)
        if "academic_admin" in self.session.roles and not self.activity_context.loaded:
            self.page.run_task(self._load_activities)
        return app_shell(
            self.page,
            self.session,
            content,
            on_logout=self._logout,
            activity_context=(
                self.activity_context if "academic_admin" in self.session.roles else None
            ),
        )

    def _workflow_content(self, path: str, label: str) -> ft.Control:
        factories: dict[str, Callable[[], ft.Control]] = {
            "/dashboard": lambda: dashboard_view(self.session),
            "/master-data": lambda: master_data_view(self.page, self.client),
            "/availability": lambda: availability_view(self.page, self.client),
            "/imports": lambda: imports_view(self.page, self.client),
            "/activities": lambda: activity_wizard_view(self.page, self.client, self.session),
            "/scheduling": lambda: scheduling_view(self.page, self.client, self.session),
            "/plans": lambda: plans_view(self.page, self.client, self.session),
            "/approvals": lambda: approvals_view(self.page, self.client, self.session),
            "/my-schedule": lambda: my_schedule_view(self.page, self.client),
            "/audit": lambda: audit_view(self.page, self.client),
            "/system": lambda: system_admin_view(self.page, self.client),
        }
        factory = factories.get(path)
        return factory() if factory is not None else placeholder_view(label)

    async def _logout(self) -> None:
        try:
            await self.client.logout()
        except ApiError:
            pass
        self.session.clear()
        self.render()
        await self.page.push_route("/login")

    async def _load_activities(self) -> None:
        await self.activity_context.load(self.client)
        self.render()

    @staticmethod
    def _not_found() -> ft.Control:
        return status_view(404, "页面不存在", "请从左侧导航选择有效页面。")


async def main(page: ft.Page) -> None:
    page.title = "答辩分组系统"
    page.theme = build_theme()
    page.padding = 0
    # Mount an initial control before invoking browser services. Flet only
    # installs a service's client-side listener after the first page update.
    page.add(ft.ProgressRing())
    try:
        api_url = await resolve_api_url(web=page.web, page_url=page.url)
    except RuntimeError as error:
        message = str(error)
        page.clean()
        page.add(status_view(503, "无法连接服务", message))
        return
    token_store: RefreshTokenStore
    if page.web:
        preferences = ft.SharedPreferences()
        # A full page update is required by Flet 1.0 to mount newly created
        # browser services before their methods can be invoked.
        page.update()
        browser_store = BrowserRefreshTokenStore(preferences, None)
        token_store = browser_store
    else:
        token_store = DesktopKeyringTokenStore()
    client = ApiClient(api_url, token_store=token_store)
    session = SessionState()
    application = ClientApplication(page, client, session)

    async def close_client() -> None:
        await client.close()

    page.on_close = close_client
    if page.web:

        async def restore_browser_session() -> None:
            await browser_store.load()
            restored = await client.bootstrap()
            session.user_id = restored.user_id
            session.username = restored.username
            session.roles = restored.roles
            session.department_ids = restored.department_ids
            session.must_change_password = restored.must_change_password
            session.selected_activity_id = restored.selected_activity_id
            application.render()

        # Browser services become callable only after the initial page handler
        # returns, so restore the persisted login in a page task.
        page.run_task(restore_browser_session)
    else:
        restored = await client.bootstrap()
        session.user_id = restored.user_id
        session.username = restored.username
        session.roles = restored.roles
        session.department_ids = restored.department_ids
        session.must_change_password = restored.must_change_password
        session.selected_activity_id = restored.selected_activity_id
        application.render()

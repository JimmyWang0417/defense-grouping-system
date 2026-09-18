from __future__ import annotations

import asyncio
import atexit
import os
import subprocess
import sys
from collections.abc import Callable

import flet as ft
import httpx

from defense_grouping.client.api_client import ApiClient, ApiError
from defense_grouping.client.components.app_shell import app_shell
from defense_grouping.client.components.feedback import status_view
from defense_grouping.client.router import NAVIGATION, RouteDecision, decide_route
from defense_grouping.client.session import (
    DesktopKeyringTokenStore,
    FletSessionTokenStore,
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


async def resolve_api_url(*, web: bool) -> str:
    configured = os.environ.get("DEFENSE_API_URL")
    if configured:
        return configured.rstrip("/")
    if web:
        raise RuntimeError("Web 部署必须显式设置 DEFENSE_API_URL，且不会启动会话级 API。")
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

    def render(self) -> None:
        self.page.render(self._root)

    def _root(self) -> ft.Control:
        return ft.Router(self._routes(), not_found=self._not_found)

    def _routes(self) -> list[ft.Route]:
        routes = [
            ft.Route(index=True, component=self._root_redirect),
            ft.Route(path="login", component=self._login),
            ft.Route(path="change-password", component=self._change_password),
        ]
        for item in NAVIGATION:
            routes.append(
                ft.Route(
                    path=item.route.removeprefix("/"),
                    component=self._protected_component(item.route, item.label),
                )
            )
        return routes

    def _root_redirect(self) -> ft.Control:
        destination = "/dashboard" if self.session.authenticated else "/login"
        self.page.navigate(destination)
        return ft.ProgressRing()

    def _login(self) -> ft.Control:
        if self.session.authenticated:
            destination = (
                "/change-password" if self.session.must_change_password else "/dashboard"
            )
            self.page.navigate(destination)
            return ft.ProgressRing()
        return login_view(self.page, self.client, self.session, self.render)

    def _change_password(self) -> ft.Control:
        decision = decide_route("/change-password", self.session)
        if decision is RouteDecision.REDIRECT_LOGIN:
            self.page.navigate("/login")
            return ft.ProgressRing()
        return change_password_view(self.page, self.client, self.session, self.render)

    def _protected_component(self, path: str, label: str) -> Callable[[], ft.Control]:
        def component() -> ft.Control:
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
            return app_shell(
                self.page,
                self.session,
                content,
                on_logout=self._logout,
            )

        return component

    def _workflow_content(self, path: str, label: str) -> ft.Control:
        factories: dict[str, Callable[[], ft.Control]] = {
            "/dashboard": lambda: dashboard_view(self.session),
            "/master-data": lambda: master_data_view(self.client),
            "/availability": lambda: availability_view(self.client),
            "/imports": lambda: imports_view(self.client),
            "/activities": lambda: activity_wizard_view(self.client),
            "/scheduling": lambda: scheduling_view(self.client),
            "/plans": lambda: plans_view(self.client),
            "/approvals": lambda: approvals_view(self.client, self.session),
            "/my-schedule": lambda: my_schedule_view(self.client),
            "/audit": lambda: audit_view(self.client),
            "/system": lambda: system_admin_view(self.client),
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

    @staticmethod
    def _not_found() -> ft.Control:
        return status_view(404, "页面不存在", "请从左侧导航选择有效页面。")


async def main(page: ft.Page) -> None:
    page.title = "答辩分组系统"
    page.theme = build_theme()
    page.padding = 0
    try:
        api_url = await resolve_api_url(web=page.web)
    except RuntimeError as error:
        message = str(error)
        page.render(
            lambda: status_view(503, "无法连接服务", message),
        )
        return
    token_store = (
        FletSessionTokenStore(page.session.store)
        if page.web
        else DesktopKeyringTokenStore()
    )
    client = ApiClient(api_url, token_store=token_store)
    session = await client.bootstrap()
    application = ClientApplication(page, client, session)

    async def close_client() -> None:
        await client.close()

    page.on_close = close_client
    application.render()

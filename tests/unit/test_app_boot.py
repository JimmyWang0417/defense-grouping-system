from pathlib import Path

from fastapi.testclient import TestClient

from defense_grouping.api.main import create_app
from defense_grouping.config import Settings


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret-with-at-least-32-characters",
    )


def test_health_endpoint_reports_local_database(tmp_path: Path) -> None:
    response = TestClient(create_app(build_settings(tmp_path))).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "sqlite"}


def test_unknown_route_uses_error_envelope(tmp_path: Path) -> None:
    response = TestClient(create_app(build_settings(tmp_path))).get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"]


def test_supplied_request_id_is_returned(tmp_path: Path) -> None:
    response = TestClient(create_app(build_settings(tmp_path))).get(
        "/api/v1/health",
        headers={"X-Request-ID": "test-request-id"},
    )

    assert response.headers["X-Request-ID"] == "test-request-id"

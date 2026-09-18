"""Run the local API and Flet client as one supervised development process."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = PROJECT_ROOT / ".runtime" / "local.env"
HEALTH_TIMEOUT_SECONDS = 30.0


def _load_or_create_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    if RUNTIME_ENV.exists():
        for raw_line in RUNTIME_ENV.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name] = value

    defaults = {
        "DEFENSE_ENVIRONMENT": "local",
        "DEFENSE_DATABASE_URL": "sqlite+aiosqlite:///./data/defense_grouping.db",
        "DEFENSE_JWT_SECRET": secrets.token_urlsafe(48),
        "DEFENSE_API_HOST": "127.0.0.1",
        "DEFENSE_API_PORT": "8765",
        "DEFENSE_API_URL": "http://127.0.0.1:8765",
    }
    changed = False
    for name, value in defaults.items():
        if name not in values:
            values[name] = value
            changed = True

    if changed or not RUNTIME_ENV.exists():
        RUNTIME_ENV.parent.mkdir(parents=True, exist_ok=True)
        serialized = "".join(f"{name}={value}\n" for name, value in sorted(values.items()))
        RUNTIME_ENV.write_text(serialized, encoding="utf-8")
        RUNTIME_ENV.chmod(0o600)
    return values


def _wait_for_health(process: subprocess.Popen[bytes], url: str) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"FastAPI exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise TimeoutError(f"FastAPI did not become healthy within {HEALTH_TIMEOUT_SECONDS:g}s")


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    values = _load_or_create_environment()
    child_environment = os.environ.copy()
    child_environment.update(values)
    host = values["DEFENSE_API_HOST"]
    port = values["DEFENSE_API_PORT"]

    api_process: subprocess.Popen[bytes] | None = None
    client_process: subprocess.Popen[bytes] | None = None
    try:
        api_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "defense_grouping.api.main:create_app",
                "--factory",
                "--host",
                host,
                "--port",
                port,
            ],
            cwd=PROJECT_ROOT,
            env=child_environment,
        )
        _wait_for_health(api_process, f"http://{host}:{port}/api/v1/health")
        client_process = subprocess.Popen(
            [sys.executable, "-m", "flet", "run", "main.py"],
            cwd=PROJECT_ROOT,
            env=child_environment,
        )
        return client_process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        _stop(client_process)
        _stop(api_process)


if __name__ == "__main__":
    raise SystemExit(main())

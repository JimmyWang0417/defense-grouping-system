"""Safely synchronize the default-branch GitHub ruleset.

The command is a dry-run by default.  Applying is deliberately guarded by a
successful remote ``PR Gate`` check so a broken or missing workflow cannot lock
the repository owner out of the default branch.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type Runner = Callable[[list[str], str | None], str]

API_VERSION = "2026-03-10"
SERVER_FIELDS = {
    "_links",
    "created_at",
    "current_user_can_bypass",
    "id",
    "node_id",
    "source",
    "source_type",
    "updated_at",
}


class PreconditionError(RuntimeError):
    """Raised when a remote mutation would make the repository unsafe."""


def _canonicalize(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items())
            if str(key) not in SERVER_FIELDS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = [_canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise TypeError(f"unsupported ruleset value: {type(value).__name__}")


def normalize_ruleset(ruleset: Mapping[str, Any]) -> JsonValue:
    """Remove GitHub-owned fields and canonicalize unordered collections."""

    public_fields = {
        key: value
        for key, value in ruleset.items()
        if key in {"name", "target", "enforcement", "bypass_actors", "conditions", "rules"}
    }
    return _canonicalize(public_fields)


def _api_arguments(method: str, endpoint: str, *, input_payload: bool = False) -> list[str]:
    arguments = [
        "--method",
        method,
        endpoint,
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
    ]
    if input_payload:
        arguments.extend(["--input", "-"])
    return arguments


def _default_runner(arguments: list[str], payload: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", "api", *arguments],
        input=payload,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _request_json(
    runner: Runner,
    method: str,
    endpoint: str,
    payload: Mapping[str, Any] | None = None,
) -> Any:
    serialized = None if payload is None else json.dumps(payload, ensure_ascii=False)
    response = runner(
        _api_arguments(method, endpoint, input_payload=payload is not None), serialized
    )
    return json.loads(response) if response.strip() else None


def _find_remote_ruleset(repository: str, name: str, runner: Runner) -> dict[str, Any] | None:
    summaries = _request_json(runner, "GET", f"repos/{repository}/rulesets?includes_parents=false")
    for summary in summaries:
        if summary.get("name") == name:
            detail = _request_json(runner, "GET", f"repos/{repository}/rulesets/{summary['id']}")
            if not isinstance(detail, dict):
                raise RuntimeError("GitHub returned an invalid ruleset response")
            return detail
    return None


def _has_successful_pr_gate(repository: str, runner: Runner) -> bool:
    runs = _request_json(
        runner,
        "GET",
        f"repos/{repository}/actions/runs?branch=main&status=success&per_page=30",
    )
    for workflow_run in runs.get("workflow_runs", []):
        jobs = _request_json(
            runner,
            "GET",
            f"repos/{repository}/actions/runs/{workflow_run['id']}/jobs?per_page=100",
        )
        if any(
            job.get("name") == "PR Gate"
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
            for job in jobs.get("jobs", [])
        ):
            return True
    return False


def _diff(remote: Mapping[str, Any] | None, local: Mapping[str, Any]) -> str:
    before = json.dumps(
        {} if remote is None else normalize_ruleset(remote),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).splitlines()
    after = json.dumps(
        normalize_ruleset(local), ensure_ascii=False, indent=2, sort_keys=True
    ).splitlines()
    return "\n".join(
        difflib.unified_diff(before, after, fromfile="github", tofile="local", lineterm="")
    )


def synchronize_ruleset(
    repository: str,
    local: dict[str, Any],
    *,
    apply: bool,
    runner: Runner = _default_runner,
    output: Callable[[str], None] = print,
) -> str:
    """Compare or apply a ruleset, returning the performed/planned action."""

    remote = _find_remote_ruleset(repository, str(local["name"]), runner)
    if remote is not None and normalize_ruleset(remote) == normalize_ruleset(local):
        return "unchanged"

    planned = "create" if remote is None else "update"
    if not apply:
        output(_diff(remote, local))
        return planned

    if not _has_successful_pr_gate(repository, runner):
        raise PreconditionError(
            "refusing to enable the ruleset before a successful remote PR Gate run"
        )

    if remote is None:
        endpoint = f"repos/{repository}/rulesets"
        method = "POST"
    else:
        endpoint = f"repos/{repository}/rulesets/{remote['id']}"
        method = "PUT"
    _request_json(runner, method, endpoint, local)
    return "created" if planned == "create" else "updated"


def _repository_from_remote() -> str:
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if url.startswith("git@github.com:"):
        slug = url.removeprefix("git@github.com:")
    elif "github.com/" in url:
        slug = url.split("github.com/", maxsplit=1)[1]
    else:
        raise ValueError("origin is not a GitHub repository")
    return slug.removesuffix(".git").strip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="GitHub owner/repository")
    parser.add_argument("--ruleset", type=Path, default=Path(".github/rulesets/main.json"))
    parser.add_argument(
        "--apply", action="store_true", help="apply after verifying a successful PR Gate"
    )
    arguments = parser.parse_args()
    local = json.loads(arguments.ruleset.read_text(encoding="utf-8"))
    repository = arguments.repo or _repository_from_remote()
    try:
        action = synchronize_ruleset(repository, local, apply=arguments.apply)
    except PreconditionError as error:
        parser.error(str(error))
    print(f"ruleset {action}: {repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

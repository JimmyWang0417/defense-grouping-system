from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.configure_github_rules import (
    PreconditionError,
    normalize_ruleset,
    synchronize_ruleset,
)

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_ruleset() -> dict[str, Any]:
    return json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text())


def rule(ruleset: dict[str, Any], rule_type: str) -> dict[str, Any]:
    return next(item for item in ruleset["rules"] if item["type"] == rule_type)


def test_main_ruleset_requires_stable_pr_gate_for_solo_owner() -> None:
    ruleset = load_ruleset()
    pull_request = rule(ruleset, "pull_request")["parameters"]
    checks = rule(ruleset, "required_status_checks")["parameters"]
    assert ruleset["target"] == "branch"
    assert ruleset["enforcement"] == "active"
    assert ruleset["bypass_actors"] == []
    assert ruleset["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert {item["type"] for item in ruleset["rules"]} >= {
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    assert pull_request["required_approving_review_count"] == 0
    assert pull_request["required_review_thread_resolution"] is True
    assert pull_request["require_extra_approval_for_unattributed_changes"] is False
    assert pull_request["required_reviewers"] == []
    assert set(pull_request["allowed_merge_methods"]) == {"squash", "rebase"}
    assert checks["strict_required_status_checks_policy"] is True
    assert checks["required_status_checks"] == [{"context": "PR Gate"}]


def test_ci_has_all_events_gates_and_least_privilege() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for event in ("pull_request:", "push:", "merge_group:", "workflow_dispatch:"):
        assert event in ci
    for command in (
        "uv sync --locked",
        "ruff format --check",
        "ruff check",
        "mypy src",
        "tests/unit",
        "tests/integration",
        "tests/client",
        "test_postgres.py",
        "flet build web --yes",
    ):
        assert command in ci
    assert re.search(r"name:\s*PR Gate", ci)
    assert "if: always()" in ci
    assert "contents: read" in ci
    assert "cancel-in-progress: true" in ci
    assert "contents: write" not in ci


def test_all_third_party_actions_are_pinned_to_full_commit_shas() -> None:
    uses_lines = []
    for workflow in WORKFLOWS.glob("*.yml"):
        uses_lines.extend(
            line.strip()
            for line in workflow.read_text(encoding="utf-8").splitlines()
            if re.match(r"\s*-?\s*uses:", line)
        )
    assert uses_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#.*)?$", line) for line in uses_lines)


def test_performance_is_nightly_and_not_part_of_pr_gate() -> None:
    performance = (WORKFLOWS / "performance.yml").read_text(encoding="utf-8")
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "schedule:" in performance
    assert "workflow_dispatch:" in performance
    assert "test_department_scale.py" in performance
    assert "test_department_scale.py" not in ci
    assert "contents: read" in performance


def test_release_requires_ci_and_only_publishes_github_assets() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "push:" in release and "branches: [main]" in release
    assert "PR Gate" in release
    assert "secrets.RELEASE_PLEASE_TOKEN" in release
    assert "release-please-config.json" in release
    assert "uv build" in release
    assert "dist/*.whl" in release
    assert "dist/*.tar.gz" in release
    assert "gh release upload" in release
    assert "pypi" not in release.casefold()
    assert "twine" not in release.casefold()

    config = json.loads((ROOT / "release-please-config.json").read_text())
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert config["packages"]["."]["release-type"] == "python"
    assert manifest == {".": "0.1.0"}


def test_pull_request_template_requires_validation_and_conventional_title() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "Conventional Commits" in template
    assert "- [ ]" in template
    assert "uv run pytest" in template
    assert "migration" in template.casefold()
    assert "security" in template.casefold()


def test_plain_language_wiki_covers_the_complete_user_journey() -> None:
    wiki = ROOT / "docs" / "wiki"
    expected = {
        "Home.md",
        "_Sidebar.md",
        "名词说明.md",
        "安装与首次登录.md",
        "角色与权限.md",
        "数据准备与导入.md",
        "活动排组与发布.md",
        "例外审批、审计与导出.md",
        "常见问题.md",
    }
    assert expected <= {path.name for path in wiki.glob("*.md")}
    combined = "\n".join((wiki / name).read_text(encoding="utf-8") for name in expected)
    for required in ("首次登录", "Excel", "排组", "发布", "例外", "备份", "PR Gate"):
        assert required in combined
    for empty_phrase in ("TODO", "TBD", "赋能", "抓手", "方法论"):
        assert empty_phrase not in combined
    assert all((wiki / name).stat().st_size >= 100 for name in expected)


class FakeRunner:
    def __init__(
        self,
        local: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
        gate_succeeded: bool = False,
    ) -> None:
        self.local = local
        self.existing = existing
        self.gate_succeeded = gate_succeeded
        self.mutations: list[tuple[list[str], str | None]] = []

    def __call__(self, arguments: list[str], payload: str | None = None) -> str:
        endpoint = next(item for item in arguments if item.startswith("repos/"))
        method = arguments[arguments.index("--method") + 1]
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            self.mutations.append((arguments, payload))
            return json.dumps(self.local)
        if endpoint.endswith("/rulesets?includes_parents=false"):
            return json.dumps(
                [] if self.existing is None else [{"id": 42, "name": self.existing["name"]}]
            )
        if endpoint.endswith("/rulesets/42"):
            assert self.existing is not None
            return json.dumps(self.existing)
        if "/actions/runs?" in endpoint:
            return json.dumps({"workflow_runs": [{"id": 7}]})
        if endpoint.endswith("/actions/runs/7/jobs?per_page=100"):
            jobs = (
                [{"name": "PR Gate", "status": "completed", "conclusion": "success"}]
                if self.gate_succeeded
                else []
            )
            return json.dumps({"jobs": jobs})
        raise AssertionError((method, endpoint))


def test_rules_script_dry_run_never_mutates() -> None:
    local = load_ruleset()
    runner = FakeRunner(local)
    result = synchronize_ruleset("owner/repo", local, apply=False, runner=runner)
    assert result == "create"
    assert runner.mutations == []


def test_rules_script_is_idempotent_after_normalization() -> None:
    local = load_ruleset()
    remote = copy.deepcopy(local)
    remote.update({"id": 42, "node_id": "RRS_1", "source": "owner/repo"})
    assert normalize_ruleset(remote) == normalize_ruleset(local)
    runner = FakeRunner(local, existing=remote)
    assert synchronize_ruleset("owner/repo", local, apply=True, runner=runner) == "unchanged"
    assert runner.mutations == []


def test_rules_script_refuses_apply_before_successful_pr_gate() -> None:
    local = load_ruleset()
    runner = FakeRunner(local)
    with pytest.raises(PreconditionError, match="PR Gate"):
        synchronize_ruleset("owner/repo", local, apply=True, runner=runner)
    assert runner.mutations == []


def test_rules_script_applies_only_after_successful_pr_gate() -> None:
    local = load_ruleset()
    runner = FakeRunner(local, gate_succeeded=True)
    assert synchronize_ruleset("owner/repo", local, apply=True, runner=runner) == "created"
    assert len(runner.mutations) == 1
    arguments, payload = runner.mutations[0]
    assert arguments[arguments.index("--method") + 1] == "POST"
    assert payload is not None
    assert normalize_ruleset(json.loads(payload)) == normalize_ruleset(local)

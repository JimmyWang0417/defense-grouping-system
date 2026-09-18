# 仓库治理与自动发布

## PR 规则

默认分支 ruleset 的版本化来源是 `.github/rulesets/main.json`：

- 禁止删除默认分支和 non-fast-forward/force push；
- 所有变更必须经过 Pull Request；
- 单人 owner 仓库不要求强制批准，但所有 review conversation 必须解决；
- 只允许 squash 或 rebase 合并；
- 分支必须为最新，并通过唯一稳定门禁 `PR Gate`；
- 没有 bypass actor。

PR 标题必须遵循 Conventional Commits，例如 `fix(api): reject expired exception`。CI 在
Python 3.12、3.13、3.14 验证测试，并检查格式、Ruff、mypy、PostgreSQL、Flet Web build
与治理契约；夜间工作流另跑 500 学生规模性能测试。

## 首次启用 ruleset

先把 workflow commit 推送到 GitHub，等待该 commit 的第一次 `PR Gate` 成功。脚本默认仅
显示规范化差异，不修改远端：

```bash
uv run python scripts/configure_github_rules.py \
  --repo JimmyWang0417/defense-grouping-system
```

确认 diff 后应用：

```bash
uv run python scripts/configure_github_rules.py \
  --repo JimmyWang0417/defense-grouping-system --apply
```

`--apply` 会再次查询近期成功 workflow 的 jobs；找不到成功的 `PR Gate` 时，在任何远端
写入前失败。重复运行会返回 `unchanged`。

API 回读：

```bash
gh api 'repos/JimmyWang0417/defense-grouping-system/rulesets?includes_parents=false'
gh api repos/JimmyWang0417/defense-grouping-system/actions/runs \
  -f branch=main -f status=success
```

若错误规则阻塞工作，owner 先在 GitHub Rules 页面临时禁用对应 ruleset，或用 ruleset ID
调用 `gh api --method PUT` 把 `enforcement` 改为 `disabled`；修复 workflow 并获得成功
`PR Gate` 后，再用版本化 JSON 恢复。禁止通过 force push 或长期 bypass 规避故障。

## 自动发布

在仓库 Actions secrets 中创建 `RELEASE_PLEASE_TOKEN`。推荐 fine-grained PAT，只授权该仓库：

- Contents: Read and write
- Pull requests: Read and write

使用 PAT 而非默认 `GITHUB_TOKEN`，使 release-please 创建的发布 PR 能触发 CI。token 只存于
GitHub secret，不写入日志、`.env` 或仓库。

合并到 main 后，Release workflow 先等待同一 commit 的 `PR Gate`，再由 release-please 根据
Conventional Commits 创建或更新发布 PR。发布 PR 通过门禁并合并后，workflow 创建 GitHub
Release，执行 `uv build`，上传 wheel 与 source archive。流程不发布 PyPI、不部署服务，
也不自动增加许可证。

发布故障时保留 tag/Release 证据，修复后重跑失败 job；不要复用或泄露 token。定期轮换
PAT，并在 owner 离开项目或权限变化时立即吊销。

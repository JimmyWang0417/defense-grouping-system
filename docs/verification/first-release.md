# 首版完成证据

验证日期：2026-09-18（Asia/Shanghai）  
实现基线：`6b093e7cbce76082feafd16d1e82200d80b11084`
平台：Manjaro Linux 6.12.108-1-MANJARO x86_64，glibc 2.44  
运行时：Python 3.13.9，SQLite 3.50.4，PostgreSQL 17（testcontainers），Docker 29.7.2  
关键库：Flet 1.0.0，SQLAlchemy 2.0.54，OR-Tools 9.15.6755

## 自动化证据

| 完成定义 | 证据 |
| --- | --- |
| 新环境安装、初始化、启动、登录 | README 与 `docs/operations/local-development.md`；CLI、迁移、认证及启动 smoke 测试 |
| 三级角色与院系隔离 | `tests/integration/test_auth_api.py`、`test_master_data_api.py`、客户端导航测试 |
| 六类 Excel 模板与事务导入 | `tests/integration/test_imports.py` |
| 完整排组方案 | 17 个 solver/precheck/validator 测试和 schedule job 集成测试 |
| 硬约束不可绕过 | solver、validator、人工调整和发布回滚测试 |
| 双人例外、撤销、审计、导出 | approvals、audit/export 集成测试 |
| 方案比较、调整、复检、发布、导出 | plan lifecycle 与 E2E 测试 |
| 院系性能 | 500 学生、50 教师、20 组、8 时段、24 教室；23.48 s wall、21.90 s solver、719.8 MiB peak RSS |
| 后端、客户端、迁移 | 完整套件 90 passed、1 conditional skip；PostgreSQL 专项另行 1 passed |
| SQLite/PostgreSQL 运维 | `docs/operations/` 五份操作指南 |
| PR、ruleset、性能、Release | repository contract 11 passed；远端 ruleset 已启用并通过实际 PR 验证 |
| 中文 Wiki | 9 个页面、696 行；仓库内源文件已合并，GitHub Wiki 等待 owner 创建首张页面 |

执行记录：

```text
uv run ruff format --check .      131 files already formatted
uv run ruff check .               All checks passed
uv run mypy src                   Success: 73 source files
uv run pytest tests/unit tests/integration tests/client tests/e2e -q
                                    90 passed, 1 skipped, 1 warning in 71.31s
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration/test_postgres.py -q
                                    1 passed in 67.16s
uv run pytest tests/repository -q  11 passed
uv run pytest tests/performance/test_department_scale.py -q -m performance -s
                                    1 passed in 24.62s
uv run alembic check               No new upgrade operations detected
uv run flet build web --yes        Successfully built build/web
uv build                           wheel and source distribution built
```

唯一测试警告来自 Starlette `TestClient` 对 AnyIO 旧别名的上游弃用提示，不影响行为。
普通完整套件中的一个 skip 是显式 Docker 条件；同一 PostgreSQL 测试已在启用条件后实测通过。

## 界面证据

Web 启动页真实 smoke 截图（无头 Firefox 在首次画面捕获 Flet bootstrap）：

![Flet Web 启动画面](web-login.png)

桌面模式已完成启动/退出 smoke；当前 Linux 验收机未把临时桌面窗口截图纳入仓库。
各目标 OS 的最终桌面安装包及截图必须在该 OS 上构建和发布验收，因为 PyInstaller
不是交叉编译器。

## 远端检查点

workflow commit `cb8884154dcb7b9c58a70dfceb2f384025d4bc35` 的 CI run
`35336511018` 全部成功。随后创建并启用 ruleset `23652785`，名称为
`main-branch-protection`，目标为默认分支。第一次 API 回读发现 GitHub 为新版 Pull Request
规则补入两个默认字段，因此修正通过该 ruleset 保护下的 Pull Request #1 提交。

Pull Request #1 的 CI run `35337598697` 全部成功，包含最终 `PR Gate`。PR 以 squash 方式
合并为 `6b093e7cbce76082feafd16d1e82200d80b11084`；该 main commit 的 CI run
`35338000686` 也全部成功。之后应用最终 ruleset 并再次 dry-run，输出为：

```text
ruleset unchanged: JimmyWang0417/defense-grouping-system
```

API 最终回读确认 ruleset 为 `active`，无 bypass actor，要求 Pull Request、解决全部审查对话、
严格通过 `PR Gate`，仅允许 squash/rebase，并禁止删除默认分支与强推。单 owner 仓库不强制
他人批准，也不要求“无法归属的修改”额外批准。

自动发布流程本身已通过配置测试。首次 Release run `35338000680` 先成功等待同一 main
commit 的 `PR Gate`，随后因仓库没有 Actions secret 而停止。仓库 owner 仍需创建最小权限
`RELEASE_PLEASE_TOKEN`（Contents 与 Pull requests 读写）。当前仓库 secret 名称列表为空；
为避免把本机 GitHub CLI 的宽权限 token 复制到 Actions，本次不代造该凭据。

中文 Wiki 的 9 个页面已保存在 `docs/wiki/` 并合入 main。仓库的 Wiki 开关已开启，当前账号
也具有管理员权限，但 GitHub 在首张 Wiki 页面创建前不会建立
`defense-grouping-system.wiki.git`。直接 `git ls-remote` 和首次 push 均返回
`Repository not found`。owner 需先在仓库的 Wiki 标签页创建一张 `Home` 页面；完成后按
`docs/operations/repository-governance.md` 的命令批量发布其余页面。

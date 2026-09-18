# 首版完成证据

验证日期：2026-09-18（Asia/Shanghai）  
实现基线：`b1a0ea9530b14f737893750b6c7c0e98170d2931`  
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
| PR、ruleset、性能、Release | repository contract 10 passed；远端启用遵循“首次 PR Gate 成功后 apply”检查点 |

执行记录：

```text
uv run ruff format --check .      121 files already formatted
uv run ruff check .               All checks passed
uv run mypy src                   Success: 73 source files
uv run pytest tests/unit tests/integration tests/client tests/e2e -q
                                    90 passed, 1 skipped, 1 warning in 71.31s
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration/test_postgres.py -q
                                    1 passed in 67.16s
uv run pytest tests/repository -q  10 passed in 0.37s
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

应用 ruleset 前的只读 dry-run 显示远端无同名规则，将创建
`main-branch-protection`。配置脚本会在任何写入前查询成功的 `PR Gate` job；远端 workflow
尚未出现时拒绝 apply。最终推送、run ID、ruleset ID 和 API 规范化回读结果记录在本次交付
回执中。

自动发布流程本身已通过配置测试，但仓库 owner 仍需创建最小权限
`RELEASE_PLEASE_TOKEN`（Contents 与 Pull requests 读写）。当前仓库 secret 名称列表为空；
为避免把本机 GitHub CLI 的宽权限 token 复制到 Actions，本次不代造该凭据。

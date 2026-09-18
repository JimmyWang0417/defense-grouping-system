# 答辩分组系统

面向学校教务工作的师生答辩分组系统，支持导师回避、课表冲突、请假特例、教师组规则、标准时段与教室安排、人工调整、例外审批、方案发布和审计追踪。

项目采用 Flet 多平台客户端、FastAPI 后端、SQLAlchemy 数据访问层和 OR-Tools CP-SAT 求解器。本机模式使用 SQLite，服务器模式可迁移到 PostgreSQL。

首版本机实现、院系级性能验收和仓库治理已完成：

- [系统设计规格](docs/superpowers/specs/2026-09-18-defense-grouping-system-design.md)
- [实施计划](docs/superpowers/plans/2026-09-18-defense-grouping-system.md)
- [可直接使用的 `/goal` 提示词](GOAL_PROMPT.md)
- [本地开发](docs/operations/local-development.md)
- [桌面与 Web 打包](docs/operations/desktop-packaging.md)
- [PostgreSQL 服务器迁移](docs/operations/server-migration.md)
- [备份与恢复](docs/operations/backup-recovery.md)
- [PR 规则与自动发布](docs/operations/repository-governance.md)

## 仓库关系

本项目是独立仓库，并以 Git submodule 形式挂载到 Classwork：

```text
Courses/软件系统分析与设计/答辩分组软件
```

克隆 Classwork 后初始化项目：

```bash
git submodule update --init --recursive
```

## 当前状态

- [x] 完成需求分析与系统设计
- [x] 完成实施计划
- [x] 完成 `/goal` 实施提示词
- [x] 建立项目依赖、API 启动骨架与质量门禁
- [x] 完成首版本机实现
- [x] 完成院系级性能验收（500 学生、50 教师、20 组）
- [x] 配置 PR Gate、默认分支 ruleset 与 GitHub Release 自动化

## 开发环境

需要 Python 3.12–3.14 和 [uv](https://docs.astral.sh/uv/)。安装锁定依赖、初始化数据库并启动：

```bash
uv sync --locked
uv run alembic upgrade head
uv run defense-grouping init-admin --username admin
uv run python scripts/dev.py
```

`scripts/dev.py` 会为本地开发生成权限受限的 `.runtime/local.env`。生产或分别启动服务时，
复制 `.env.example` 为 `.env` 并替换随机密钥：

```bash
uv run uvicorn defense_grouping.api.main:create_app --factory --port 8765
```

健康检查位于 `http://127.0.0.1:8765/api/v1/health`。完整门禁：

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run alembic check
uv run flet build web --yes
```

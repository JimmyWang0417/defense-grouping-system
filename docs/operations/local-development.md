# 本地开发

## 前置条件

- Python 3.12–3.14
- `uv`
- Git

从仓库根目录安装锁定依赖：

```bash
uv sync --locked
```

首次启动前创建配置和数据库：

```bash
cp .env.example .env
# 将 DEFENSE_JWT_SECRET 替换为至少 32 字符的随机值
uv run alembic upgrade head
uv run defense-grouping init-admin --username admin
```

管理员临时密码只显示一次，首次登录后必须修改。不要提交 `.env`、运行时数据库或
`data/storage` 中的导入文件。

## 一键启动

```bash
uv run python scripts/dev.py
```

该命令在 `127.0.0.1:8765` 启动 FastAPI，健康检查通过后再启动 Flet 客户端；
`Ctrl+C` 会同时停止两者。首次运行生成权限为 `0600` 的 `.runtime/local.env`。

也可分别启动：

```bash
uv run uvicorn defense_grouping.api.main:create_app --factory --port 8765
DEFENSE_API_URL=http://127.0.0.1:8765 uv run flet run main.py
```

## 日常验证

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run alembic check
```

性能测试不属于每次 PR 的快速门禁，应单独运行：

```bash
uv run pytest tests/performance/test_department_scale.py -q -m performance
```

PostgreSQL 兼容测试需要 Docker：

```bash
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration/test_postgres.py -q
```

若端口被占用，停止旧进程或同时修改 `DEFENSE_API_PORT` 和 `DEFENSE_API_URL`。
数据库结构变化必须新增 Alembic revision，并在 SQLite 与 PostgreSQL 上验证。

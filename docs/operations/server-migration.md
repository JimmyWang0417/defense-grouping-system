# PostgreSQL 服务器迁移

## 数据库与迁移

生产连接串使用 asyncpg：

```text
postgresql+asyncpg://defense_app:URL_ENCODED_PASSWORD@db.example.edu:5432/defense_grouping
```

数据库账号仅授予该数据库所需的连接、schema 和表权限。通过 secret manager 注入配置：

```bash
export DEFENSE_ENVIRONMENT=production
export DEFENSE_DATABASE_URL='postgresql+asyncpg://...'
export DEFENSE_JWT_SECRET='至少 32 字符的随机密钥'
export DEFENSE_STORAGE_DIR='/srv/defense-grouping/storage'
uv sync --locked
uv run alembic upgrade head
uv run defense-grouping init-admin --username admin
```

上线前先在同版本 PostgreSQL 的临时库执行：

```bash
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration/test_postgres.py -q
uv run alembic check
```

## 服务边界

使用进程管理器运行 Uvicorn，并只监听内网地址。Nginx/Caddy 等反向代理负责 TLS、
HTTP 安全头、请求体上限和 `/api/` 转发；公网入口必须为 HTTPS。推荐 Web 客户端与 API
同源。若未来加入 FastAPI CORS middleware，allowlist 必须逐项列出受管域名，不允许生产
环境通配符。

当前 `TaskExecutor` 是进程内的本机实现，数据库与求解器之间仅传递可序列化的
`SchedulingInput`/`SolveOutcome`。扩展到多节点时，应在这一边界替换为持久任务队列，
保持 API、领域模型和求解器契约不变；在替换前不要用多个 API 实例争抢本机任务。

## 迁移步骤

1. 公告维护窗口，停止写入并创建 SQLite 备份及 SHA-256 manifest。
2. 在隔离环境创建 PostgreSQL 数据库，执行 `alembic upgrade head`。
3. 用经审计的迁移程序按外键顺序复制数据，统一 UUID、UTC 时间和 JSON 值。
4. 比较每张表行数、关键业务汇总和已发布方案导出；抽样登录与权限隔离。
5. 切换 `DEFENSE_DATABASE_URL`，单实例启动并运行健康、登录、导入、求解、发布、导出 smoke。
6. 验收后开放流量，保留只读 SQLite 原库直到回滚窗口结束。

## 备份、回滚与监控

- 每日 `pg_dump --format=custom`，至少每周恢复演练；备份需加密、异地保存并设置保留期。
- 迁移前保存数据库备份、应用镜像/commit、Alembic revision 和环境配置摘要。
- 若 smoke 或数据核对失败，立即停止新服务，恢复旧连接串并重新启动只读保留的 SQLite
  服务；不要尝试把失败切换后的部分写入自动合并回旧库。
- 若已接受生产写入，应进入事故流程：冻结两端、导出差异，经人工确认后再恢复。
- 监控 `/api/v1/health`、5xx、登录限流、排组失败、任务积压、磁盘与数据库连接数；日志不得
  包含密码、token、JWT secret 或导入文件内容。

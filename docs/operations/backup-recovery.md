# 备份与恢复

## SQLite 本机模式

API 运行时可创建一致性在线备份：

```bash
uv run defense-grouping backup
```

默认在 `data/storage/backups` 生成 `.sqlite3` 与同名 manifest。manifest 记录 SHA-256、
大小、时间和 Alembic revision。将两者一起复制到受控的异地存储。

恢复会替换当前数据库，必须先停止 API：

```bash
uv run defense-grouping restore data/storage/backups/<backup>.sqlite3 --yes
```

恢复程序先校验 hash 与 schema revision，再自动备份当前库、原子替换并执行只读完整性检查。
任何校验失败都应保留现状，不要手工绕过 manifest。

## PostgreSQL 服务器模式

建议每日逻辑备份并由平台提供时间点恢复：

```bash
pg_dump --format=custom --file defense-grouping.dump "$DATABASE_URL"
pg_restore --clean --if-exists --no-owner --dbname "$RECOVERY_DATABASE_URL" defense-grouping.dump
```

不要直接在生产库演练恢复。先恢复到隔离库，执行 Alembic revision、表行数、登录、权限、
已发布方案导出和审计日志抽查；每周记录一次可恢复性演练结果。

## 事故恢复顺序

1. 停止 API 和后台任务，记录故障时间、当前 commit 与 schema revision。
2. 复制现有损坏数据作为取证快照。
3. 选择故障前最近且已验证的备份，在隔离环境恢复并验证。
4. 切换连接前再次确认数据损失窗口并获得 owner 批准。
5. 启动单个实例，执行健康、登录、查询、导出 smoke，再逐步开放流量。
6. 记录恢复点、丢失范围、校验结果和后续措施。

备份目录和数据库转储包含个人信息，应限制访问、加密传输/存储并按学校数据政策销毁。

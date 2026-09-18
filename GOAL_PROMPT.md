# `/goal` 实施提示词

进入本仓库根目录后，将下面整段提示词粘贴到 Codex。官方 OpenAI 文档建议让持久目标明确必读材料、验证命令和可验证的停止条件；本提示词已经包含这些信息。

```text
/goal 在当前 defense-grouping-system 仓库中完整实现“答辩分组系统”首版。在达到下述可验证完成状态之前持续推进，不要把设计文档、空壳页面、模拟返回值或少量冒烟测试当作完成。

开始前必须完整阅读：
1. docs/superpowers/specs/2026-09-18-defense-grouping-system-design.md
2. docs/superpowers/plans/2026-09-18-defense-grouping-system.md
3. 当前目录及上级目录中适用的 AGENTS.md

以设计规格为产品需求的唯一权威，以实施计划为默认执行顺序。从 Task 1 开始，按 Task 1 至 Task 12 逐项实现；每个任务都采用测试先行，先确认测试因缺少行为而失败，再完成最小但真实的实现，运行该任务的 pytest、Ruff 和 mypy 验证，并按计划创建独立 Git 提交。不要删除、跳过、弱化或伪造测试来获得通过结果。若计划中的示例与当前依赖的真实 API 不一致，先核对官方文档，保持设计需求和公共接口不变，做最小必要修订，并在对应计划文件中记录修订原因。

必须交付真实可运行的完整纵向功能：Flet 桌面/Web 客户端、FastAPI API、三级权限和院系隔离、SQLite/Alembic、六类 Excel 模板及两阶段事务导入、课程和请假可用性、答辩活动配置、OR-Tools CP-SAT 自动排组、独立硬约束复检、持久任务、方案版本、人工调整、双人例外审批、发布与教师确认、审计、Excel 导出、SQLite 备份恢复、PostgreSQL 兼容测试、演示数据、CI、打包与运维文档。客户端不得直接访问数据库。未审批硬约束在自动求解、人工调整和发布三个入口都不得被突破。发布方案不可原地修改。

每完成一个任务：
- 更新计划复选框和简短进度记录；
- 运行该任务声明的验证命令；
- 检查 git diff，避免修改父 Classwork 仓库或无关文件；
- 创建计划规定的本地提交；
- 继续下一个任务，不因单个里程碑通过而停止。

最终必须执行并保存真实输出：
uv sync --locked
uv run ruff check .
uv run mypy src
uv run pytest tests/unit tests/integration tests/client tests/e2e -q
uv run pytest tests/performance/test_department_scale.py -q -m performance
uv run alembic check
uv run flet build web --yes

还必须在本机实际启动 FastAPI 与 Flet，分别验证桌面模式和 Web 模式的登录、Excel 导入、活动配置、自动排组、方案发布、教师查看确认与导出流程；使用演示数据保存必要截图或运行证据。将最终提交号、系统与 Python 版本、数据库版本、全部命令结果、500 名学生/50 名教师/20 个组的耗时与峰值内存、构建产物位置、人工流程验证结果写入 docs/verification/first-release.md。

只有在以下条件全部有证据时才能结束目标：
1. 设计规格第 16 节的 10 项完成定义逐项有测试、命令输出或运行证据；
2. 上述静态检查、自动测试、性能测试、迁移检查和 Web 构建全部通过；
3. 参考环境中 500 名学生、50 名教师、20 个答辩组在 60 秒内得到有效方案，求解进程峰值内存低于 2 GB；
4. README 从全新环境安装到首次登录的命令已实际验证；
5. docs/verification/first-release.md 完整且没有占位内容；
6. git status 只包含有意变更，所有实现任务均有本地提交。

不得自动 push、创建 Pull Request、部署服务器、写入真实教务数据或添加开源许可证；这些外部操作需要我另行明确授权。如果遇到依赖下载或沙箱权限问题，按环境提供的审批机制请求完成该必要动作；如果遇到实现困难，先缩小复现、查阅官方文档并继续修复，不要以降低需求或只写说明文档代替实现。
```

## `/goal` 使用说明

- 查看当前状态：`/goal`
- 暂停：`/goal pause`
- 恢复：`/goal resume`
- 清除：`/goal clear`

如果客户端没有显示 `/goal`，在 Codex CLI 中运行：

```bash
codex features enable goals
```

也可以在 Codex 配置中启用：

```toml
[features]
goals = true
```

官方说明：<https://developers.openai.com/zh-Hans/use-cases/follow-goals>


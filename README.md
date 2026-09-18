# 答辩分组系统

面向学校教务工作的师生答辩分组系统，支持导师回避、课表冲突、请假特例、教师组规则、标准时段与教室安排、人工调整、例外审批、方案发布和审计追踪。

项目计划采用 Flet 多平台客户端、FastAPI 后端、SQLAlchemy 数据访问层和 OR-Tools CP-SAT 求解器。本机模式使用 SQLite，服务器模式可迁移到 PostgreSQL。

当前处于实施准备阶段：

- [系统设计规格](docs/superpowers/specs/2026-09-18-defense-grouping-system-design.md)
- [实施计划](docs/superpowers/plans/2026-09-18-defense-grouping-system.md)
- [可直接使用的 `/goal` 提示词](GOAL_PROMPT.md)

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
- [ ] 完成首版本机实现
- [ ] 完成院系级性能验收

# 答辩分组系统使用手册

这套系统用于整理答辩所需的学生、教师、时间和教室数据，生成答辩安排，并在发布前检查冲突。

如果是第一次使用，按下面的顺序阅读：

1. [名词说明](名词说明.md)：先查阅手册中出现的技术词和业务状态。
2. [安装与首次登录](安装与首次登录.md)：完成本机安装、数据库初始化和管理员创建。
3. [角色与权限](角色与权限.md)：确认系统管理员、教务管理员和教师分别可以做什么。
4. [数据准备与导入](数据准备与导入.md)：下载模板，填写并检查六类 Excel 数据。
5. [活动、排组与发布](活动排组与发布.md)：创建答辩活动、设置规则、生成和发布安排。
6. [例外审批、审计与导出](例外审批、审计与导出.md)：处理确实需要放行的冲突，并保存操作记录。
7. [常见问题](常见问题.md)：根据页面提示和错误代码排查问题。

维护人员还应阅读仓库内的操作说明：

- [本地开发](https://github.com/JimmyWang0417/defense-grouping-system/blob/main/docs/operations/local-development.md)
- [桌面与 Web 打包](https://github.com/JimmyWang0417/defense-grouping-system/blob/main/docs/operations/desktop-packaging.md)
- [PostgreSQL 服务器迁移](https://github.com/JimmyWang0417/defense-grouping-system/blob/main/docs/operations/server-migration.md)
- [备份与恢复](https://github.com/JimmyWang0417/defense-grouping-system/blob/main/docs/operations/backup-recovery.md)
- [仓库规则与自动发布](https://github.com/JimmyWang0417/defense-grouping-system/blob/main/docs/operations/repository-governance.md)

## 一次完整业务流程

下面是一轮答辩安排从准备到结束的实际顺序：

1. 系统管理员创建院系和教务管理员账号。
2. 教务管理员录入专业、方向、教师、学生和教室，也可以使用 Excel 批量导入。
3. 教务管理员创建答辩活动，设置每组学生数、每组教师数、组长职称要求、教师工作量上限、答辩时段和可用教室。
4. 系统先检查数据是否足够，例如教师数量、时间容量和教室数量是否满足要求。
5. 检查通过后提交排组任务，在任务页面查看进度和结果。
6. 教务管理员查看冲突说明，必要时复制一个方案再手工调整。
7. 如果确实需要允许某个冲突，先提交例外申请，再由另一名有审批权限的教务管理员审批。
8. 重新检查方案。检查通过后发布。
9. 教师登录后查看自己的答辩安排并确认。
10. 教务管理员导出发布方案，保存分组总表、教师安排、学生安排、教室时段、冲突与例外以及方案信息。

## 使用时需要记住的三点

- Excel 的“检查”只读取文件并列出问题；点击“确认导入”后才会写入数据库。
- 自动排组成功不等于可以直接发布。发布时系统会再次检查完整方案。
- 已发布方案不能直接修改。需要变更时复制为新版本，调整、检查并重新发布；旧版本会保留。

# 桌面与 Web 打包

打包前先执行完整质量门禁，并确认客户端连接地址指向目标 API。

## 桌面应用

```bash
uv sync --locked
uv run flet pack main.py --name defense-grouping-system
```

产物位于 Flet/PyInstaller 输出目录。Windows、macOS 与 Linux 的桌面产物必须分别在
对应目标操作系统上构建；Flet/PyInstaller 不是跨平台交叉编译器。发布前应在干净机器
上检查启动、登录、密钥环存储、导入、排组与导出，并记录操作系统和 Python 版本。

桌面包不应内置 JWT secret、管理员密码、GitHub token、数据库文件或生产 API 凭据。
`DEFENSE_API_URL` 应由部署环境注入。

## Web 客户端

```bash
uv run flet build web --yes
```

将生成的静态文件部署到 HTTPS 站点，并通过同源反向代理把 `/api/` 转发到 FastAPI。
同源部署不需要宽泛 CORS。若客户端和 API 必须跨源，只允许明确的生产源，禁止使用
`*` 搭配凭据。

GitHub 的 `PR Gate` 会执行 Web build smoke test；桌面安装包仍需在各目标系统手工验收。

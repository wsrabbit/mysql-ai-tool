# 安装与使用

## Windows 发布包（普通使用者）

1. 获取 `mysql-ai-tools-0.3.0-windows-x64.zip` 和对应 SHA-256 文件，从可信来源核对哈希。
2. 解压完整 ZIP，保留 `app/_internal`，在解压目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

安装到 `%LOCALAPPDATA%\mysql-ai-tools\versions\0.3.0`；配置位于
`%LOCALAPPDATA%\mysql-ai-tools\config\connections.json`，日志在 `logs`。
无需 Python、uv、Node、MySQL CLI 或管理员权限。宿主的文件/网络审批仍按该电脑策略执行。
安装会备份变更前的 Codex 配置，仅管理 `mcp_servers.mysql-ai`，保留其他服务器与设置。

3. 推荐使用交互式向导配置专用只读账号：

```powershell
$mysqlAi = Join-Path $env:LOCALAPPDATA 'mysql-ai-tools/versions/0.3.0/app/mysql-ai.exe'
& $mysqlAi config wizard
```

按步骤新建或修改连接，选择 TLS、隐藏输入密码、逐库验证并确认保存。操作说明见 [连接向导](docs/WIZARD.md)。
安装不会自动进入向导，保持无人值守安装兼容。也可继续使用参数命令：


```powershell
$mysqlAi = Join-Path $env:LOCALAPPDATA 'mysql-ai-tools/versions/0.3.0/app/mysql-ai.exe'
& $mysqlAi config add dev --host db.example.internal --user ai_reader --database shop --ssl-ca C:\certs\mysql-ca.pem
& $mysqlAi doctor --connection dev
```

`db.example.internal`、`shop`、用户名和证书路径为示例，请替换。
同一账号有多个业务库时重复传 `--database`。默认 TLS 校验证书和主机名。
仅对明确选择的本机/测试连接可使用 `--tls disabled`；证书错误不会自动降级。

密码保存到当前 Windows 用户的 Credential Locker，配置仅存随机凭据标识。
可运行 `doctor --credential-check` 用一条临时记录验证凭据读写，测试后自动删除该记录。
参数命令重配连接需 `--replace`；新配置保存成功后才清理不再被引用的旧凭据。向导修改连接可选择保留原密码。
不要将密码放入聊天、命令参数或仓库。

4. 新建 Codex 会话，确认 MCP 工具加载后尝试：

> 使用 dev 连接查看 shop 数据库的表结构，再统计已付款订单金额。说明状态过滤和金额单位。

安装不代表当前已打开的会话立即获得新工具。doctor 不会伪装成实际 Codex 集成验证。

## 从源码运行（当前开发电脑）

支持 Python 3.12/3.13；当前开发机实际验证版本记录见测试报告。
安装 uv 后，在项目根目录执行：

```powershell
uv sync --locked --group build
.\.venv\Scripts\python.exe -m mysql_ai doctor
.\.venv\Scripts\python.exe -m mysql_ai config add dev --host 127.0.0.1 --user ai_reader --database shop --tls disabled
.\.venv\Scripts\python.exe -m mysql_ai doctor --connection dev
.\.venv\Scripts\python.exe -m mysql_ai register --skill-source .\plugins\mysql-ai-tools\skills\mysql-assistant
```

没有 uv 时先使用 `python -m pip install uv`。首次生成/修改依赖锁用 `uv lock`，发布与日常安装使用 `--locked`。
注册保存 `.venv` 解释器的本机绝对路径；项目移动后重新注册，换电脑需要重新创建虚拟环境。
不要复制其他电脑的 `.venv`，不要把依赖安装到系统 Python 的全局环境。

`--home PATH` 可在子命令之前指定独立配置与日志目录。
`register --codex-home PATH --skills-dir PATH` 可用于隔离验证；默认使用当前用户的 `.codex` 与 `.agents/skills`。
本工具不在工具调用期间下载安装依赖，不使用 PATH 自动选择未知解释器。

## 环境变量凭据（自动化/测试）

`config add ... --password-env MYSQL_AI_PASSWORD` 仅记录环境变量名称。
启动 MCP 的宿主必须提供该环境变量。不要把值写进 `.mcp.json`、config.toml 或日志。
Windows 日常使用优先选 Credential Locker，避免依赖 GUI 程序的环境变量继承行为。

## 验证与打包

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\scripts\smoke_mcp.py
powershell -ExecutionPolicy Bypass -File .\scripts\test-docker.ps1
.\.venv\Scripts\python.exe .\scripts\build_release.py
```

Docker 脚本需要本机 Docker Desktop 引擎和首次镜像下载权限。它生成随机测试账号，
仅绑定 `127.0.0.1` 的随机端口，测试后删除本次容器、匿名卷和生成的凭据文件。
不连接或改动现有 MySQL。可用 `-Image mysql:8.0 -ReportName mysql80-integration` 验证另一版本。
默认 pytest 未启用集成环境时会明确跳过真实数据库测试。

build_release 在 Windows x64 构建，使用 PyInstaller onedir。冻结程序需通过 doctor 和实际 MCP 握手才生成 ZIP。
发布文件位于 `outputs`；构建缓存位于 `work`。未验证的操作系统或 Python 版本不做兼容保证。

## 升级、回退与卸载

新版本解压后运行它的 install.ps1。新程序自检通过后才切换 Codex 注册，旧版本保留。
新旧版本不能共用覆盖式文件更新；先结束正在运行的旧 MCP，再清理旧文件。
要回退程序版本，可重新运行旧版 exe 的 `register --skill-source ...` 并新建会话。
schema_version=1 配置可共用；未来不兼容配置迁移需要配套恢复步骤。

在**已安装版本目录**运行（示例）：

```powershell
$uninstaller = Join-Path $env:LOCALAPPDATA 'mysql-ai-tools/versions/0.3.0/uninstall.ps1'
powershell -ExecutionPolicy Bypass -File $uninstaller
```

默认仅移除 MCP 注册。需要删除该版本程序文件时加 `-RemoveProgramFiles`，先关闭相关 MCP 会话。
配置、凭据、日志与 Skill 默认保留，避免丢失用户资料。可通过 `config remove NAME --delete-password`
明确删除连接和对应凭据；Skill 的位置是 `%USERPROFILE%\.agents\skills\mysql-assistant`，确认不用后手动删除。
卸载发现 MCP 配置已被其他工具修改时停止，不擅自覆盖。

## 可选插件包

源码中的 `plugins/mysql-ai-tools` 包含清单、Skill 与 MCP 声明。
源码声明使用 `mysql-ai` 命令，需要该命令可用；发布包安装程序会在安装目录为插件生成本机绝对启动路径。
默认安装流程使用直接注册 MCP + Skill，避免依赖个人 marketplace 的全局配置。
不要同时启用直接注册和该插件中的同一 MCP。marketplace 发布与 Codex 插件目录的实际安装测试不包含在默认自动安装中。

## 故障排查

| 错误 | 处理 |
|---|---|
| DEPENDENCY_MISSING | 源码模式执行锁定同步；发布包重新获取完整目录 |
| CREDENTIAL_MISSING / CREDENTIAL_BACKEND | 在同一 Windows 用户的终端重新配置凭据 |
| TLS_FAILED | 检查 CA 文件和证书主机名，保持验证开启 |
| CONNECTION_FAILED | 检查数据库地址、端口、网络、超时和 TLS |
| AUTH_FAILED / PERMISSION_DENIED | 检查账号密码和最小权限，不要发送聊天中的密码 |
| SQL_REJECTED / SQL_UNSUPPORTED | 使用文档支持的 SELECT 子集与 :name 参数 |
| QUERY_TIMEOUT / BUSY | 缩小查询范围，等待清理结束；不要无限重试 |
| REGISTRATION_CONFLICT / SKILL_CONFLICT | 保留已有配置，检查同名资源归属后手动处理 |

日志按大小滚动，总计约 8 MB，默认不记录原始 SQL、参数或结果。请求编号用于对应错误与日志。

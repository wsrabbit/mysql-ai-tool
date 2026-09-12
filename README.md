# MySQL AI Tools

让 AI 通过本地 MCP 安全地查看 MySQL 表结构、运行只读查询和解释执行计划。Python 3 开发，提供 Windows x64 安装包与配套 Skill。

[![CI](https://github.com/wsrabbit/mysql-ai-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/wsrabbit/mysql-ai-tool/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wsrabbit/mysql-ai-tool)](https://github.com/wsrabbit/mysql-ai-tool/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**[下载最新版本](https://github.com/wsrabbit/mysql-ai-tool/releases/latest)** · [安装文档](INSTALL.md) · [接口与限制](docs/USAGE.md) · [更新记录](CHANGELOG.md) · [自动测试](https://github.com/wsrabbit/mysql-ai-tool/actions/workflows/ci.yml)

## 可以做什么

| 能力 | MCP 工具 |
|---|---|
| 查看已配置连接、诊断网络/TLS/权限 | `list_connections`、`test_connection` |
| 查看允许访问的数据库、表和视图 | `list_databases`、`list_tables` |
| 读取字段、索引和外键 | `describe_table` |
| 参数化 SELECT：过滤、JOIN、分组、聚合、排序、子查询 | `query` |
| 查看普通 SELECT 执行计划 | `explain_query` |

例如：“使用 dev 连接查看 shop 数据库的表结构，再按月份统计已付款订单金额。”

## Windows 快速开始

需要 Windows x64、Codex，以及可访问的 MySQL 和专用只读账号。**安装包已包含 Python 运行时，不需要额外安装 Python、uv、Node 或 MySQL CLI。**

1. 在 [Releases](https://github.com/wsrabbit/mysql-ai-tool/releases/latest) 下载 `mysql-ai-tools-<版本>-windows-x64.zip` 和同名 `.zip.sha256` 文件。源码 ZIP 供开发者使用。
2. 使用 `Get-FileHash .\mysql-ai-tools-<版本>-windows-x64.zip -Algorithm SHA256` 核对结果与校验文件一致。完整解压 ZIP，保留 `app/_internal`。
3. 在解压目录打开普通 PowerShell，执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
   ```

4. 按安装输出启动交互式连接向导：

   ```powershell
   $mysqlAi = Join-Path $env:LOCALAPPDATA 'mysql-ai-tools/versions/0.2.0/app/mysql-ai.exe'
   & $mysqlAi config wizard
   ```

   向导逐步输入地址、账号、数据库和 TLS 设置，隐藏输入密码，逐库验证后确认保存。
   已有连接可选择修改并保留原密码；失败可重试或明确选择未验证保存。
   详细操作见 [连接向导](docs/WIZARD.md)，自动化脚本仍可使用 [config add](INSTALL.md)。
5. 新建 Codex 会话，确认 `mysql-ai` 工具加载后开始查询。

安装会备份并保留其他 Codex 配置。已打开的会话不会自动加载新工具。自定义安装目录、升级、回退与卸载见 [INSTALL.md](INSTALL.md)。

## 边界与默认限制

- **只读**：不支持 INSERT、UPDATE、DELETE、DDL、存储过程和锁定读取。
- SQL 子集：当前不支持 CTE、UNION、窗口函数和任意自定义函数，未知语法默认拒绝。
- 默认返回最多 200 行，可请求最多 1,000 行；响应默认最多 1 MiB，查询服务端默认限制 10 秒。
- 金额 DECIMAL 和超出安全整数范围的 BIGINT 用字符串返回，避免精度丢失。
- 数据库白名单、SQL 语法树校验与只读会话共同限制访问；请仍使用专用只读账号。
- 查询结果会进入 AI 会话；日志默认不记录原始 SQL、参数或结果。
- 当前二进制发布目标为 Windows x64。Linux CI 验证数据库协议，不代表提供 Linux 桌面安装包。

完整行为和超时、内存边界见 [工具契约](docs/USAGE.md)。有问题可 [提交 Issue](https://github.com/wsrabbit/mysql-ai-tool/issues)，附版本号与脱敏后的错误码即可。

## 从源码开发

支持 Python 3.12 / 3.13，使用锁定依赖：

```powershell
git clone https://github.com/wsrabbit/mysql-ai-tool.git
cd mysql-ai-tool
python -m pip install uv==0.12.10
uv sync --locked --group build
uv run --no-sync pytest -q -m "not integration"
uv run --no-sync ruff check src tests scripts
uv run --no-sync python scripts/smoke_mcp.py
```

本机 Docker Desktop 启动后，可运行真实数据库测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-docker.ps1
```

脚本创建临时数据库、随机账号和仅本机可访问的端口，测试后清理本次容器与凭据文件。不会使用你的业务库。

## 自动测试与发布

每次分支提交或 Pull Request 自动执行：

1. Windows Python 3.12 / 3.13：代码检查、版本校验、单元测试和实际 MCP 握手。
2. MySQL 8.0 / 8.4：Linux 临时 Docker 数据库中的集成测试。
3. 前述检查通过后构建 Windows x64 包，验证冻结 MCP、凭据存储、隔离安装、重复安装和卸载。

推送 `vX.Y.Z` 标签后重新执行同样的检查，全部通过才自动发布安装包、源码包及各自的 SHA-256 文件。
普通 CI 附件保留 14 天，正式下载请使用 Releases。发布失败不会跳过检查或覆盖已有正式版本。

维护者操作步骤见 [发布指南](docs/RELEASING.md)。本项目使用 [Apache-2.0](LICENSE) 许可证。

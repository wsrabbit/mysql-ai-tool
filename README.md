# MySQL AI Tools 0.1

Python 3 编写的本地只读 MySQL MCP。提供连接诊断、表结构读取、参数化查询和普通 EXPLAIN。

安装与使用见 [INSTALL.md](INSTALL.md)。接口与限制见 [docs/USAGE.md](docs/USAGE.md)。

这是第一版：不提供数据写入、DDL、存储过程、递归 CTE 或远程 HTTP 服务。
使用独立只读数据库账号；查询结果会返回到 AI 会话。

开发：使用 Python 3.12/3.13、uv 和项目内虚拟环境。运行 `uv sync --locked --group build`，
然后运行 `uv run pytest` 和 `uv run ruff check .`。集成测试需显式配置独立测试数据库。

项目安装不要求开发者将数据库密码发给 AI，也不要求安装 MySQL 命令行客户端。

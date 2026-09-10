# Changelog

## 0.1.1

- 首页增加 Windows 下载入口、功能、限制和快速安装说明。
- GitHub Actions 自动执行双 Python 版本测试、MySQL 8.0/8.4 集成测试和 Windows 打包自检。
- 版本标签触发 Release 发布，生成安装包、源码包及 SHA-256，校验版本与附件完整性。
- 发布包补充许可证和构建提交记录；源码包包含工作流。
- 新增隔离安装、重复安装和卸载自测；Docker 脚本支持 Linux CI。
- 数据库工具保持只读，未扩展 SQL 方言。

## 0.1.0

- Python 3 本地 STDIO MCP，7 个只读工具。
- SQLGlot MySQL 语法树白名单、参数化、连接范围限制。
- 独立连接与有界并发、服务端和客户端超时、结果截断、精度保留。
- Windows Credential Locker、显式环境变量凭据、配置/自检命令。
- 保留其他配置的 Codex 注册和卸载、随包分发 Skill 与可选插件。
- PyInstaller onedir 发布脚本、哈希清单、源码与冻结 MCP 握手测试。
- 独立 Docker MySQL 集成测试脚本。

本版不提供数据库写入和结构变更，不将尚未运行的环境验证标记为通过。

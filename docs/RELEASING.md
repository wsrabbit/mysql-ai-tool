# 自动测试与发布指南

## 工作流

| 文件 | 触发或用途 |
|---|---|
| `.github/workflows/ci.yml` | 分支 push、Pull Request、手动运行 CI |
| `.github/workflows/checks.yml` | 复用 Windows Python 3.12/3.13 和 MySQL 8.0/8.4 检查 |
| `.github/workflows/package.yml` | 复用 Windows 打包、冻结程序及安装维护自测 |
| `.github/workflows/release.yml` | 推送 v 开头的标签后测试、打包并发布 Release |

工作流固定使用官方 Actions 的提交 SHA，并固定 uv 版本；依赖安装使用 `uv sync --locked`。
常规检查只有 contents:read 权限，仅最终 publish job 使用 contents:write。
不使用 pull_request_target，不向 PR 测试提供发布令牌，不需要额外设置个人访问令牌或数据库密码。

参考：[GitHub 工作流权限说明](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)、[GitHub CLI Release 命令](https://cli.github.com/manual/gh_release_create)。

## 发布一个新版本

1. 更新以下四处版本号；使用 X.Y.Z 格式：
   - `pyproject.toml`
   - `src/mysql_ai/__init__.py`
   - `plugins/mysql-ai-tools/.codex-plugin/plugin.json`
   - 执行 `uv lock` 更新 `uv.lock` 中的项目版本。
2. 在 CHANGELOG.md 新增该版本的 `## X.Y.Z` 小节，更新 README 和 INSTALL 中的版本示例。
3. 提交并推送，等待该提交的 CI 全部通过。
4. 在同一提交打标签并推送，例如：

   ```powershell
   git tag -a v0.3.0 -m "MySQL AI Tools 0.3.0"
   git push origin v0.3.0
   ```

5. 到 [Release 工作流](https://github.com/wsrabbit/mysql-ai-tool/actions/workflows/release.yml) 查看结果。
   成功后 [Releases](https://github.com/wsrabbit/mysql-ai-tool/releases) 自动出现正式发布页。

未来发布请替换示例版本，不复用或移动已经发布的标签。
本流程仅发布稳定的 X.Y.Z 版本，预发布版本需要另行扩展版本校验与发布参数。

## 发布门禁与附件

标签必须与 Python 项目、模块、插件和依赖锁版本一致，CHANGELOG 必须包含该版本。
`scripts/check_release.py` 负责校验，且不依赖项目第三方包。

每个正式 Release 包含以下 4 个附件：

- `mysql-ai-tools-X.Y.Z-windows-x64.zip`
- `mysql-ai-tools-X.Y.Z-windows-x64.zip.sha256`
- `mysql-ai-tools-X.Y.Z-source.zip`
- `mysql-ai-tools-X.Y.Z-source.zip.sha256`

Windows 包包含许可证、版本/构建提交记录及内部文件哈希。
发布前核对两个 ZIP 的完整性、版本、许可证及 SHA-256；发布说明从 CHANGELOG 自动提取，
附版本固定的下载入口与安装步骤。构建过程执行 doctor、真实 STDIO 握手，以及隔离安装维护验证。

工作流测试数据库使用随机凭据。报告和待发布附件作为 Actions artifacts 保留 14 天，
正式 Release 附件长期保留，除非仓库维护者主动删除。

## 排查失败

- **版本或锁定校验失败**：同步版本号并执行 uv lock；不要禁用 --locked。
- **测试失败**：查看失败 job 日志和测试 XML。修复后发布新的版本标签。
- **Windows 凭据自检失败**：核对运行账号是否有可用的 Windows 凭据存储；不跳过该检查发布。
- **附件上传或 API 暂时失败**：先检查是否已经创建 Release。尚未创建时可重新运行失败的 job；
  若已经存在，请在发布页核对附件再处理，流程不会自动覆盖已有 Release。
- **推送工作流被拒绝**：本机 GitHub 登录凭据可能需要工作流写入权限，由账号持有者完成授权；
  不要把个人令牌写入工作流或聊天。
- **Actions 被禁用**：在仓库 Actions 页面查看 GitHub 提示。组织/账号策略由仓库所有者处理。

## 验证范围

自动测试证明指定 runner 上的测试结果，不等于所有 Windows 电脑或业务环境都已验收。
发布包暂未代码签名；SHA-256 用于核对下载完整性。
第二台物理电脑的网络、证书、账号、Codex 会话加载仍需真实验收。

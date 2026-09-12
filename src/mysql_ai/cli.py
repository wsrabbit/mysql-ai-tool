import argparse
import asyncio
import getpass
import json
import os
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from mysql_ai import __version__
from mysql_ai.config import config_path, data_home, load_settings, load_snapshot, save_settings
from mysql_ai.errors import ToolError
from mysql_ai.models import ConnectionProfile, Settings


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def parser():
    root = argparse.ArgumentParser(prog="mysql-ai", description="本地只读 MySQL MCP")
    root.add_argument("--home", type=Path, help="配置与日志目录；默认用户数据目录")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="启动 STDIO MCP 服务")
    commands.add_parser("version")
    doctor = commands.add_parser("doctor", help="本机环境与可选数据库自检")
    doctor.add_argument("--connection")
    doctor.add_argument(
        "--credential-check",
        action="store_true",
        help="通过临时记录验证 Windows 凭据读写，完成后删除测试记录",
    )
    config = commands.add_parser("config").add_subparsers(dest="action", required=True)
    config.add_parser("list")
    config.add_parser("wizard", help="交互式新建或修改数据库连接")
    add = config.add_parser("add")
    add.add_argument("name")
    add.add_argument("--host", required=True)
    add.add_argument("--port", type=int, default=3306)
    add.add_argument("--user", required=True)
    add.add_argument("--database", action="append", required=True)
    add.add_argument("--environment", default="dev")
    add.add_argument("--tls", choices=("verify", "disabled"), default="verify")
    add.add_argument("--ssl-ca")
    add.add_argument("--password-env", help="仅记录变量名称，不读取或存储变量值")
    add.add_argument("--replace", action="store_true")
    remove = config.add_parser("remove")
    remove.add_argument("name")
    remove.add_argument("--delete-password", action="store_true")
    for name in ("register", "unregister"):
        command = commands.add_parser(name)
        command.add_argument(
            "--codex-home",
            type=Path,
            default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        )
        if name == "register":
            command.add_argument("--skill-source", type=Path)
            command.add_argument("--skills-dir", type=Path)
    return root


def configure(args):
    if args.action == "wizard":
        from mysql_ai.wizard import run_wizard

        return run_wizard()
    settings, snapshot = load_snapshot()
    if args.action == "list":
        return {
            "ok": True,
            "config_path": str(config_path()),
            "connections": [
                {
                    "name": name,
                    "host": profile.host,
                    "port": profile.port,
                    "user": profile.user,
                    "databases": profile.databases,
                    "tls": profile.tls,
                    "credential_source": "environment"
                    if profile.password_env
                    else "Windows Credential Locker",
                }
                for name, profile in settings.connections.items()
            ],
        }
    if args.action == "remove":
        profile = settings.connections.get(args.name)
        if profile is None:
            raise ToolError("CONNECTION_UNKNOWN", "连接别名不存在。")
        del settings.connections[args.name]
        save_settings(settings, expected=snapshot)
        if args.delete_password and not profile.password_env:
            from mysql_ai.credentials import delete_password

            if not any(
                p.credential_id == profile.credential_id for p in settings.connections.values()
            ):
                delete_password(profile.credential_id)
        return {"ok": True, "removed": args.name}
    if args.name in settings.connections and not args.replace:
        raise ToolError("CONFIG_EXISTS", "连接已存在；如需替换请显式传入 --replace。")
    profile = ConnectionProfile(
        host=args.host,
        port=args.port,
        user=args.user,
        databases=args.database,
        environment=args.environment,
        tls=args.tls,
        ssl_ca=str(Path(args.ssl_ca).resolve()) if args.ssl_ca else None,
        password_env=args.password_env,
        credential_id=f"{args.name}-{uuid.uuid4().hex}",
    )
    settings.connections[args.name] = profile
    # Validate alias and entire configuration before touching credential storage.
    Settings.model_validate_json(settings.model_dump_json())
    secret = None
    if not args.password_env:
        if not sys.stdin.isatty():
            raise ToolError(
                "INTERACTIVE_REQUIRED", "请在本机交互终端运行此命令输入密码；或显式使用环境变量。"
            )
        secret = getpass.getpass("MySQL 密码（隐藏输入）: ")
    from mysql_ai.connections import save_connection

    messages = save_connection(config_path(), snapshot, args.name, profile, secret)
    return {
        "ok": True,
        "warnings": messages,
        "connection": args.name,
        "config_path": str(config_path()),
        "next": "运行 doctor --connection 检查连接；已运行的 MCP 需要重启读取配置。",
    }


def doctor(connection=None, credential_check=False):
    from importlib.metadata import version

    from mysql_ai.policy import prepare_query
    from mysql_ai.server import create_server
    from mysql_ai.service import DatabaseService

    settings = load_settings()
    versions = {
        name: version(name) for name in ("mcp", "PyMySQL", "sqlglot", "pydantic", "keyring")
    }
    prepare_query("SELECT :value AS value", {"value": 1}, ["example"])
    service = DatabaseService(settings)
    try:
        create_server(service)
        result = {
            "ok": True,
            "version": __version__,
            "python": sys.version.split()[0],
            "frozen": bool(getattr(sys, "frozen", False)),
            "dependencies": versions,
            "config_path": str(config_path()),
            "connection_count": len(settings.connections),
            "checks": ["config", "imports", "sql_policy", "mcp_registration"],
            "warnings": ["本机初始化成功不代表 Codex 新会话已连接；请另做 MCP 握手检查。"],
        }
        if credential_check:
            from mysql_ai.credentials import check_storage

            check_storage()
            result["checks"].append("credential_roundtrip")
        if connection:
            database_result = asyncio.run(service.dispatch("test_connection", connection))
            result["database_check"] = database_result
            result["ok"] = database_result["ok"]
        else:
            result["warnings"].append("未指定连接，本次没有验证真实数据库。")
        return result
    finally:
        service.close()


def main(argv=None):
    # MCP framing uses UTF-8 even on legacy Windows console codepages.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    if args.home:
        os.environ["MYSQL_AI_HOME"] = str(args.home.resolve())
    try:
        if args.command == "serve":
            from mysql_ai.server import serve

            serve()
            return 0
        if args.command == "version":
            emit({"version": __version__, "python": sys.version.split()[0]})
            return 0
        if args.command == "config":
            result = configure(args)
        elif args.command == "doctor":
            result = doctor(args.connection, args.credential_check)
        elif args.command == "register":
            from mysql_ai.registration import register

            env = {"MYSQL_AI_HOME": str(data_home())}
            # Pass variable names only; secrets are inherited from the host at launch.
            result = register(args.codex_home, args.skill_source, args.skills_dir, env)
        else:
            from mysql_ai.registration import unregister

            result = unregister(args.codex_home)
        emit(result)
        return 0 if result.get("ok") else 1
    except ToolError as exc:
        output = exc.payload()
    except ValidationError:
        output = ToolError(
            "CONFIG_INVALID", "配置参数无效；请检查名称、数据库、端口和允许值。"
        ).payload()
    except (OSError, ValueError):
        output = ToolError(
            "LOCAL_ERROR", "无法读写本机文件或配置；请检查路径、权限和格式。"
        ).payload()
    except ImportError:
        output = ToolError(
            "DEPENDENCY_MISSING", "项目依赖缺失；请按 INSTALL.md 安装完整依赖。"
        ).payload()
    except KeyboardInterrupt:
        return 130
    if args.command == "serve":
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
    else:
        emit(output)
    return 1

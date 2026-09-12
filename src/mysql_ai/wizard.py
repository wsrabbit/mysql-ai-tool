"""Interactive terminal connection wizard. No secrets in output or configuration."""

import getpass
import re
import sys
import uuid
import warnings
from pathlib import Path

from pydantic import ValidationError

from mysql_ai.config import config_path, load_snapshot
from mysql_ai.connections import check_connection, save_connection
from mysql_ai.errors import ToolError
from mysql_ai.models import ConnectionProfile


class Terminal:
    def ask(self, prompt):
        return input(prompt)

    def secret(self, prompt):
        # Never allow getpass to fall back to echoing a password.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                return getpass.getpass(prompt)
            except getpass.GetPassWarning as exc:
                raise ToolError(
                    "INTERACTIVE_REQUIRED", "当前终端无法隐藏密码，请使用普通终端。"
                ) from exc

    def show(self, message):
        print(message)


def ask(io, label, default="", validate=None):
    while True:
        suffix = f" [{default}]" if default else ""
        value = io.ask(f"{label}{suffix}: ").strip() or default
        try:
            return validate(value) if validate else value
        except (ValueError, ValidationError):
            io.show("输入无效，请检查格式后重试。")


def choice(io, label, options, default):
    return ask(io, label, default, lambda v: v if v in options else invalid())


def invalid():
    raise ValueError("Invalid input")


def field(data, name, value):
    candidate = dict(data, **{name: value})
    ConnectionProfile.model_validate(candidate)
    return value


def edit_basics(io, data):
    for key, label in (
        ("host", "服务器地址"),
        ("port", "端口"),
        ("user", "用户名"),
        ("environment", "环境名称"),
    ):

        def validate(value, key=key):
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                return invalid()
            if key == "host" and (any(c.isspace() for c in value) or "://" in value):
                return invalid()
            return field(data, key, int(value) if key == "port" else value)

        data[key] = ask(io, label, str(data.get(key, "")), validate)


def edit_databases(io, data):
    data["databases"] = ask(
        io,
        "允许访问的数据库（逗号分隔）",
        ",".join(data["databases"]),
        lambda v: field(data, "databases", [s.strip() for s in v.replace("，", ",").split(",")]),
    )


def edit_tls(io, data):
    default = "3" if data["tls"] == "disabled" else "2" if data.get("ssl_ca") else "1"
    while True:
        mode = choice(
            io,
            "TLS：1 系统信任证书 / 2 自定义 CA / 3 禁用（仅明确选择的本机测试）",
            {"1", "2", "3"},
            default,
        )
        if mode == "3":
            default = "1"
            if data["host"].lower() not in {"localhost", "127.0.0.1", "::1"}:
                io.show("向导仅允许本机测试连接禁用 TLS，请使用证书验证。")
                continue
            if choice(io, "本机测试将不加密，确认禁用？y/n", {"y", "n"}, "n") != "y":
                continue
            data.update(tls="disabled", ssl_ca=None)
        else:
            ca = None
            if mode == "2":

                def ca_path(value):
                    path = Path(value).expanduser()
                    if not path.is_file():
                        return invalid()
                    return str(path.resolve())

                ca = ask(io, "CA 文件路径", data.get("ssl_ca") or "", ca_path)
            data.update(tls="verify", ssl_ca=ca)
        return data


def edit_password(io, data, original):
    if original:
        if choice(io, "密码：1 保留原凭据来源 / 2 输入新密码", {"1", "2"}, "1") == "1":
            data.update(credential_id=original.credential_id, password_env=original.password_env)
            return None
    while True:
        password = io.secret("MySQL 密码（隐藏输入）: ")
        confirm = io.secret("再次输入密码（隐藏输入）: ")
        if password == confirm:
            data.update(credential_id=f"wizard-{uuid.uuid4().hex}", password_env=None)
            return password
        io.show("两次密码不一致，请重新输入。")


def display(io, name, data, checked):
    io.show("\n连接摘要（密码不显示）")
    for label, value in (
        ("别名", name),
        ("服务器", f"{data['host']}:{data['port']}"),
        ("用户名", data["user"]),
        ("数据库", ", ".join(data["databases"])),
        ("环境", data["environment"]),
        ("TLS", data["tls"]),
        ("CA", data.get("ssl_ca") or "系统信任"),
        ("凭据来源", "环境变量（保留）" if data.get("password_env") else "Windows 凭据存储"),
        ("本次验证", "通过" if checked else "未验证/验证未通过"),
    ):
        io.show(f"  {label}: {value}")


def run_wizard(io=None, path=None):
    if io is None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ToolError("INTERACTIVE_REQUIRED", "请在普通交互终端运行 config wizard。")
        io = Terminal()
    path = path or config_path()
    password = None
    saved_result = None
    try:
        settings, snapshot = load_snapshot(path)
        io.show("MySQL 连接向导：确认保存前不修改连接。Ctrl+C 随时取消。")
        original = None
        if settings.connections:
            io.show("已有连接：" + ", ".join(settings.connections))
            operation = choice(io, "1 新建 / 2 修改 / 0 取消", {"0", "1", "2"}, "1")
            if operation == "0":
                return cancelled()
            if operation == "2":
                name = ask(
                    io,
                    "修改哪个连接",
                    validate=lambda v: v if v in settings.connections else invalid(),
                )
                original = settings.connections[name]
        if original is None:
            if len(settings.connections) >= 32:
                raise ToolError("CONFIG_LIMIT", "连接数量已达上限，请先修改或移除已有连接。")
            name = ask(
                io,
                "连接别名",
                validate=lambda v: (
                    v
                    if re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", v) and v not in settings.connections
                    else invalid()
                ),
            )
        data = (
            original.model_dump()
            if original
            else ConnectionProfile(
                host="localhost", user="ai_reader", databases=["shop"], credential_id="pending"
            ).model_dump()
        )
        edit_basics(io, data)
        edit_databases(io, data)
        data = edit_tls(io, data)
        password = edit_password(io, data, original)
        checked = False
        action = "5"
        while True:
            if action == "5":
                io.show("正在验证每个指定数据库的连接与权限…")
                report = check_connection(
                    ConnectionProfile.model_validate(data), settings.limits, password
                )
                checked = report["ok"]
                for item in report["databases"]:
                    if item["ok"]:
                        io.show(f"{item['database']}: 连接验证通过")
                        for message in item.get("warnings", []):
                            io.show(f"  {message}")
                    else:
                        error = item["error"]
                        io.show(f"{item['database']}: {error['code']} — {error['message']}")
                if not checked:
                    io.show("失败时可修改地址/端口、数据库、TLS 或密码，再重试。TLS 不会自动降级。")
            display(io, name, data, checked)
            action = choice(
                io,
                "1 修改基础信息 / 2 数据库 / 3 TLS / 4 密码 / 5 重试验证 / 6 保存 / 0 取消",
                {"0", "1", "2", "3", "4", "5", "6"},
                "6" if checked else "5",
            )
            if action == "0":
                return cancelled()
            if action == "6":
                if not checked:
                    if (
                        choice(io, "当前未验证通过，仍保存为未验证配置？y/n", {"y", "n"}, "n")
                        != "y"
                    ):
                        continue
                if choice(io, "确认保存以上配置？y/n", {"y", "n"}, "n") != "y":
                    continue
                messages = save_connection(
                    path, snapshot, name, ConnectionProfile.model_validate(data), password
                )
                saved_result = {
                    "ok": True,
                    "connection": name,
                    "verified": checked,
                    "config_path": str(path),
                    "warnings": messages,
                    "next": "本次验证结果仅反映当前连接；后续可运行 doctor --connection 检查。",
                }
                io.show("已保存。请重启 MCP 或新建 Codex 会话。")
                io.show(f"使用示例：使用 {name} 连接查看 {data['databases'][0]} 的表结构。")
                return saved_result
            if action != "5":
                checked = False
            if action == "1":
                edit_basics(io, data)
            elif action == "2":
                edit_databases(io, data)
            elif action == "3":
                data = edit_tls(io, data)
            elif action == "4":
                password = edit_password(io, data, original)
    except (KeyboardInterrupt, EOFError):
        if saved_result is not None:
            return saved_result
        io.show("\n已取消；未保存连接。")
        return cancelled()
    finally:
        # Python does not guarantee zeroing immutable strings; retain no long-lived secret state.
        password = None


def cancelled():
    return {"ok": True, "cancelled": True, "message": "已取消；未保存连接。"}

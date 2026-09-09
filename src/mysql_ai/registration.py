"""Edit only our MCP entry; preserve other entries and fail on ownership conflicts."""

import json
import shutil
import sys
import uuid
from pathlib import Path

import tomlkit

from mysql_ai.config import atomic_write, write_json
from mysql_ai.errors import ToolError

NAME = "mysql-ai"


def launch_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ["serve"]
    return str(Path(sys.executable).resolve()), ["-m", "mysql_ai", "serve"]


def register(
    codex_home: Path,
    skill_source: Path | None = None,
    skills_dir: Path | None = None,
    environment: dict | None = None,
) -> dict:
    codex_home = codex_home.expanduser().resolve()
    path = codex_home / "config.toml"
    receipt_path = codex_home / "mysql-ai-registration.json"
    before = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    document = tomlkit.parse(before)
    servers = document.get("mcp_servers", {})
    old = dict(servers[NAME]) if NAME in servers else None
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
    command, args = launch_command()
    entry = {"command": command, "args": args, "startup_timeout_sec": 30, "tool_timeout_sec": 60}
    if environment:
        entry["env"] = environment
    if old is not None and old != entry and old != receipt.get("entry"):
        raise ToolError(
            "REGISTRATION_CONFLICT", "同名 MCP 配置不属于本工具；请保留并手动处理冲突。"
        )
    if "mcp_servers" not in document:
        document["mcp_servers"] = tomlkit.table()
    document["mcp_servers"][NAME] = entry
    skill_target = None
    if skill_source is not None:
        source = skill_source.resolve()
        target = (
            skills_dir or Path.home() / ".agents/skills"
        ).expanduser().resolve() / "mysql-assistant"
        if not (source / "SKILL.md").is_file():
            raise ToolError("SKILL_MISSING", "找不到随程序发布的 SKILL.md。")
        if target.exists() and not (target / ".mysql-ai-managed").is_file():
            raise ToolError("SKILL_CONFLICT", "同名 Skill 已存在且不属于本工具；未覆盖。")
        target.mkdir(parents=True, exist_ok=True)
        # Only this known file is installed; no arbitrary recursive source copy.
        shutil.copy2(source / "SKILL.md", target / "SKILL.md")
        atomic_write(target / ".mysql-ai-managed", "mysql-ai-tools\n")
        skill_target = str(target)
    backup = None
    if before and tomlkit.dumps(document) != before:
        backup = path.with_name(f"config.toml.mysql-ai-{uuid.uuid4().hex[:12]}.bak")
        atomic_write(backup, before)
    atomic_write(path, tomlkit.dumps(document))
    try:
        write_json(
            receipt_path,
            {"entry": entry, "skill_target": skill_target or receipt.get("skill_target")},
        )
    except Exception:
        atomic_write(path, before)
        raise
    return {
        "ok": True,
        "config": str(path),
        "backup": str(backup) if backup else None,
        "skill": skill_target,
        "next": "在新会话中检查 MCP 工具；当前会话不会自动获得新工具。",
    }


def unregister(codex_home: Path) -> dict:
    codex_home = codex_home.expanduser().resolve()
    path = codex_home / "config.toml"
    receipt_path = codex_home / "mysql-ai-registration.json"
    if not receipt_path.exists():
        return {"ok": True, "removed": False, "message": "没有本工具的注册记录。"}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    current_command, current_args = launch_command()
    if (
        receipt.get("entry", {}).get("command") != current_command
        or receipt.get("entry", {}).get("args") != current_args
    ):
        raise ToolError("REGISTRATION_CONFLICT", "当前注册指向另一个程序版本；请使用该版本卸载。")
    before = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    document = tomlkit.parse(before)
    servers = document.get("mcp_servers", {})
    if NAME in servers:
        if dict(servers[NAME]) != receipt["entry"]:
            raise ToolError("REGISTRATION_CONFLICT", "MCP 配置已被修改，未自动删除。")
        del servers[NAME]
        backup = path.with_name(f"config.toml.mysql-ai-{uuid.uuid4().hex[:12]}.bak")
        atomic_write(backup, before)
        atomic_write(path, tomlkit.dumps(document))
    # Keep installed skill/data by default; do not recursively delete user paths.
    receipt_path.unlink()
    return {
        "ok": True,
        "removed": True,
        "message": "已移除 MCP 注册；数据库凭据、配置、日志与 Skill 保留。",
    }

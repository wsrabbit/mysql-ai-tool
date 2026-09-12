"""Connection editing transactions and checks shared by CLI and wizard."""

from mysql_ai import credentials, db
from mysql_ai.config import configuration_lock, load_snapshot, write_settings
from mysql_ai.errors import ToolError
from mysql_ai.models import Settings


def check_connection(profile, limits, password=None):
    results = []
    for database in profile.databases:
        try:
            result = db.probe(profile, database, limits, password=password)
            results.append(dict(result, database=database))
        except ToolError as exc:
            results.append(dict(exc.payload(), database=database))
    return {"ok": all(r["ok"] for r in results), "databases": results}


def save_connection(path, expected, name, profile, password=None):
    """Publish fresh credentials and settings under a cooperative cross-process lock."""
    warnings = []
    with configuration_lock(path):
        settings, current = load_snapshot(path)
        if current != expected:
            raise ToolError("CONFIG_CHANGED", "配置已被其他进程修改；请重新启动向导。")
        old = settings.connections.get(name)
        if password is not None and (
            profile.password_env
            or any(p.credential_id == profile.credential_id for p in settings.connections.values())
        ):
            raise ToolError("CONFIG_INVALID", "新密码必须使用独立的新凭据标识。")
        settings.connections[name] = profile
        Settings.model_validate_json(settings.model_dump_json())
        stored = False
        try:
            if password is not None:
                stored = True
                credentials.set_password(profile.credential_id, password)
            write_settings(settings, path)
        except BaseException as exc:
            # An interrupt can arrive immediately after os.replace published the file.
            # Never delete a credential that an already-committed configuration uses.
            try:
                committed = load_snapshot(path)[0] == settings
            except ToolError:
                raise ToolError(
                    "SAVE_UNCERTAIN", "无法确认配置保存状态；已保留凭据，请检查配置后再操作。"
                ) from exc
            if committed:
                warnings.append("保存过程中发生中断，但已确认新配置保存成功。")
            else:
                if stored:
                    try:
                        credentials.delete_password(profile.credential_id)
                    except BaseException:
                        raise ToolError(
                            "CREDENTIAL_CLEANUP",
                            "配置未保存；新建凭据清理失败，请在本机凭据管理器检查本工具记录。",
                        ) from exc
                raise
        # Configuration is committed. Never undo it merely because old-secret cleanup failed.
        if old and not old.password_env and old.credential_id != profile.credential_id:
            if not any(
                p.credential_id == old.credential_id and not p.password_env
                for p in settings.connections.values()
            ):
                try:
                    credentials.delete_password(old.credential_id)
                except (ToolError, KeyboardInterrupt):
                    warnings.append("新配置已保存，但旧凭据清理失败，可在本机凭据管理器清理。")
    return warnings

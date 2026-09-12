import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from mysql_ai.errors import ToolError
from mysql_ai.models import Settings


def data_home() -> Path:
    if override := os.environ.get("MYSQL_AI_HOME"):
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "mysql-ai-tools"
        )
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "mysql-ai-tools"


def config_path() -> Path:
    return data_home() / "config" / "connections.json"


def load_snapshot(path: Path | None = None) -> tuple[Settings, bytes | None]:
    path = path or config_path()
    try:
        with path.open("rb") as handle:
            raw = handle.read(131073)
        if len(raw) > 131072:
            raise ValueError("oversized")
        return Settings.model_validate_json(raw.decode("utf-8-sig")), raw
    except FileNotFoundError:
        return Settings(), None
    except (OSError, ValueError, ValidationError) as exc:
        raise ToolError("CONFIG_INVALID", "配置无效；请在本机检查配置格式，不要发送凭据。") from exc


def load_settings(path: Path | None = None) -> Settings:
    return load_snapshot(path)[0]


@contextmanager
def configuration_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep this file: unlinking a lock file can split concurrent writers across inodes.
    with path.with_suffix(path.suffix + ".lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ToolError("CONFIG_BUSY", "其他进程正在保存配置，请稍后重试。") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mysql-ai-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_settings(settings: Settings, path: Path) -> None:
    settings = Settings.model_validate_json(settings.model_dump_json())
    atomic_write(path, settings.model_dump_json(indent=2) + "\n")


ANY_REVISION = object()


def save_settings(settings: Settings, path: Path | None = None, *, expected=ANY_REVISION) -> None:
    path = path or config_path()
    with configuration_lock(path):
        if expected is not ANY_REVISION and load_snapshot(path)[1] != expected:
            raise ToolError("CONFIG_CHANGED", "配置已被其他进程修改，请重新读取后操作。")
        write_settings(settings, path)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

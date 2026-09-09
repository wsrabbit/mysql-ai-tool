import json
import os
import tempfile
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


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_path()
    if not path.exists():
        return Settings()
    try:
        if path.stat().st_size > 131072:
            raise ValueError("oversized")
        return Settings.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, ValidationError) as exc:
        raise ToolError("CONFIG_INVALID", "配置无效；请在本机检查配置格式，不要发送凭据。") from exc


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


def save_settings(settings: Settings, path: Path | None = None) -> None:
    settings = Settings.model_validate_json(settings.model_dump_json())
    atomic_write(path or config_path(), settings.model_dump_json(indent=2) + "\n")


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

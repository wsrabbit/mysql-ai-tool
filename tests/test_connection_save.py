import subprocess
import sys

import pytest

from mysql_ai import config, connections
from mysql_ai.errors import ToolError


@pytest.fixture
def state(tmp_path, settings, monkeypatch):
    path = tmp_path / "connections.json"
    old = settings.connections["dev"]
    old.password_env = None
    old.credential_id = "old"
    config.save_settings(settings, path)
    snapshot = path.read_bytes()
    values = {"old": "old-secret"}
    monkeypatch.setattr(
        "mysql_ai.credentials.set_password", lambda key, value: values.update({key: value})
    )
    monkeypatch.setattr("mysql_ai.credentials.delete_password", lambda key: values.pop(key, None))
    new = old.model_copy(update={"credential_id": "new"})
    return path, snapshot, values, new


def test_replace_publishes_new_secret_then_cleans_old(state):
    path, snapshot, values, new = state
    assert connections.save_connection(path, snapshot, "dev", new, "new-secret") == []
    assert values == {"new": "new-secret"}
    assert config.load_settings(path).connections["dev"].credential_id == "new"


@pytest.mark.parametrize("error", [OSError("private"), KeyboardInterrupt()])
def test_write_failure_rolls_back_new_credential(state, monkeypatch, error):
    path, snapshot, values, new = state

    def fail(*args):
        raise error

    monkeypatch.setattr(connections, "write_settings", fail)
    with pytest.raises(type(error)):
        connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert path.read_bytes() == snapshot and values == {"old": "old-secret"}


def test_credential_failure_preserves_configuration(state, monkeypatch):
    path, snapshot, values, new = state

    def fail(*args):
        raise ToolError("CREDENTIAL_BACKEND", "无法保存")

    monkeypatch.setattr("mysql_ai.credentials.set_password", fail)
    with pytest.raises(ToolError):
        connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert path.read_bytes() == snapshot and values == {"old": "old-secret"}


def test_changed_configuration_rejected_before_secret_write(state):
    path, snapshot, values, new = state
    updated = config.load_settings(path)
    updated.connections["dev"].host = "updated.example"
    config.save_settings(updated, path)
    with pytest.raises(ToolError) as error:
        connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert error.value.code == "CONFIG_CHANGED" and values == {"old": "old-secret"}
    assert config.load_settings(path).connections["dev"].host == "updated.example"


def test_old_credential_cleanup_failure_does_not_undo_save(state, monkeypatch):
    path, snapshot, values, new = state

    def fail(*args):
        raise ToolError("CREDENTIAL_BACKEND", "无法删除")

    monkeypatch.setattr("mysql_ai.credentials.delete_password", fail)
    messages = connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert messages and config.load_settings(path).connections["dev"].credential_id == "new"
    assert values["new"] == "new-secret"


def test_shared_old_credential_is_retained(state):
    path, _, values, new = state
    settings = config.load_settings(path)
    settings.connections["other"] = settings.connections["dev"].model_copy()
    config.save_settings(settings, path)
    connections.save_connection(path, path.read_bytes(), "dev", new, "new-secret")
    assert values == {"old": "old-secret", "new": "new-secret"}


def test_cli_saving_stale_settings_is_rejected(state):
    path, snapshot, _, _ = state
    settings = config.load_settings(path)
    path.write_bytes(snapshot + b"\n")
    with pytest.raises(ToolError) as error:
        config.save_settings(settings, path, expected=snapshot)
    assert error.value.code == "CONFIG_CHANGED"


def test_lock_excludes_other_process(state):
    path, _, _, _ = state
    code = (
        "import sys; from pathlib import Path; "
        "from mysql_ai.config import save_settings; from mysql_ai.models import Settings; "
        "from mysql_ai.errors import ToolError; "
        "\ntry: save_settings(Settings(), Path(sys.argv[1]))"
        "\nexcept ToolError as e: print(e.code)"
        "\nelse: raise SystemExit(1)"
    )
    with config.configuration_lock(path):
        result = subprocess.run(
            [sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=15
        )
    assert result.returncode == 0 and "CONFIG_BUSY" in result.stdout


def test_interrupt_after_atomic_commit_retains_active_secret(state, monkeypatch):
    path, snapshot, values, new = state

    def commit_then_interrupt(settings, path):
        config.write_settings(settings, path)
        raise KeyboardInterrupt()

    monkeypatch.setattr(connections, "write_settings", commit_then_interrupt)
    messages = connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert messages
    assert config.load_settings(path).connections["dev"].credential_id == "new"
    assert values == {"new": "new-secret"}


def test_failed_credential_write_cleans_partial_record(state, monkeypatch):
    path, snapshot, values, new = state

    def partial_write(key, value):
        values[key] = value
        raise ToolError("CREDENTIAL_BACKEND", "保存失败")

    monkeypatch.setattr("mysql_ai.credentials.set_password", partial_write)
    with pytest.raises(ToolError):
        connections.save_connection(path, snapshot, "dev", new, "new-secret")
    assert values == {"old": "old-secret"} and path.read_bytes() == snapshot

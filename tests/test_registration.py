import tomllib

import pytest

from mysql_ai.errors import ToolError
from mysql_ai.registration import register, unregister


def test_install_preserves_other_config_and_is_idempotent(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('# user comment\nmodel="test"\n[mcp_servers.other]\ncommand="other"\n')
    register(tmp_path)
    once = path.read_text()
    register(tmp_path)
    assert path.read_text() == once
    assert "# user comment" in once
    assert tomllib.loads(once)["mcp_servers"]["other"]["command"] == "other"
    unregister(tmp_path)
    assert "mysql-ai" not in tomllib.loads(path.read_text())["mcp_servers"]


def test_refuses_unowned_server(tmp_path):
    path = tmp_path / "config.toml"
    original = '[mcp_servers.mysql-ai]\ncommand="someone-else"\n'
    path.write_text(original)
    with pytest.raises(ToolError):
        register(tmp_path)
    assert path.read_text() == original


def test_refuses_uninstall_after_user_modification(tmp_path):
    register(tmp_path)
    path = tmp_path / "config.toml"
    path.write_text(path.read_text().replace('"serve"', '"modified"'))
    with pytest.raises(ToolError):
        unregister(tmp_path)


def test_old_executable_cannot_unregister_new_version(tmp_path, monkeypatch):
    register(tmp_path)
    monkeypatch.setattr(
        "mysql_ai.registration.launch_command", lambda: ("old-version.exe", ["serve"])
    )
    with pytest.raises(ToolError):
        unregister(tmp_path)

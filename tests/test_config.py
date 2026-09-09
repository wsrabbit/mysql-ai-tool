import json

import pytest

from mysql_ai.config import load_settings, save_settings
from mysql_ai.credentials import password_for
from mysql_ai.errors import ToolError


def test_roundtrip_no_password(tmp_path, settings):
    path = tmp_path / "connections.json"
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert "password" not in json.loads(path.read_text())["connections"]["dev"]


def test_invalid_config_does_not_echo_secret(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"password":"SECRET_STRING"}')
    with pytest.raises(ToolError) as error:
        load_settings(path)
    assert "SECRET_STRING" not in str(error.value)


def test_env_password(settings, monkeypatch):
    monkeypatch.setenv("MYSQL_AI_TEST_PASSWORD", "test-value")
    assert password_for(settings.connections["dev"]) == "test-value"
    monkeypatch.delenv("MYSQL_AI_TEST_PASSWORD")
    with pytest.raises(ToolError, match="缺少密码"):
        password_for(settings.connections["dev"])

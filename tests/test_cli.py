import json

from mysql_ai.cli import main
from mysql_ai.config import load_settings


def test_env_connection_can_be_configured_without_reading_secret(tmp_path, capsys):
    code = main(
        [
            "--home",
            str(tmp_path),
            "config",
            "add",
            "dev",
            "--host",
            "127.0.0.1",
            "--user",
            "reader",
            "--database",
            "shop",
            "--tls",
            "disabled",
            "--password-env",
            "MYSQL_AI_TEST_PASSWORD",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["ok"]
    assert load_settings().connections["dev"].password_env == "MYSQL_AI_TEST_PASSWORD"


def test_invalid_alias_does_not_write(tmp_path, capsys):
    code = main(
        [
            "--home",
            str(tmp_path),
            "config",
            "add",
            "../bad",
            "--host",
            "127.0.0.1",
            "--user",
            "reader",
            "--database",
            "shop",
            "--password-env",
            "MYSQL_AI_TEST_PASSWORD",
        ]
    )
    assert code == 1 and "CONFIG_INVALID" in capsys.readouterr().out
    assert not (tmp_path / "config/connections.json").exists()

import pytest

from mysql_ai.models import ConnectionProfile, Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("MYSQL_AI_HOME", str(tmp_path / "data"))
    return Settings(
        connections={
            "dev": ConnectionProfile(
                host="127.0.0.1",
                user="reader",
                databases=["shop"],
                credential_id="test",
                password_env="MYSQL_AI_TEST_PASSWORD",
                tls="disabled",
            )
        }
    )

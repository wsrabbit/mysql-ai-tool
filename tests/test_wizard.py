import json

import pytest

from mysql_ai import connections
from mysql_ai.config import load_settings, save_settings
from mysql_ai.errors import ToolError
from mysql_ai.wizard import Terminal, run_wizard

PASSWORD = "fixture-secret"
NEW = ["dev", "127.0.0.1", "3306", "reader", "dev", "shop", "1"]


class IO:
    def __init__(self, answers, secrets=(PASSWORD, PASSWORD)):
        self.answers = iter(answers)
        self.secrets = iter(secrets)
        self.output = []

    def ask(self, prompt):
        self.output.append(prompt)
        value = next(self.answers)
        if isinstance(value, BaseException):
            raise value
        return value

    def secret(self, prompt):
        self.output.append(prompt)
        return next(self.secrets)

    def show(self, message):
        self.output.append(message)


def good(profile, limits, password):
    return {
        "ok": True,
        "databases": [
            {"ok": True, "database": database, "warnings": []} for database in profile.databases
        ],
    }


@pytest.fixture
def storage(monkeypatch):
    values = {}
    monkeypatch.setattr(
        "mysql_ai.credentials.set_password", lambda key, value: values.update({key: value})
    )
    monkeypatch.setattr("mysql_ai.credentials.delete_password", lambda key: values.pop(key, None))
    monkeypatch.setattr("mysql_ai.wizard.check_connection", good)
    return values


def test_new_connection_only_commits_on_confirmation(tmp_path, storage):
    path = tmp_path / "connections.json"
    io = IO(NEW + ["6", "y"])
    result = run_wizard(io, path)
    assert result["verified"] and result["ok"]
    profile = load_settings(path).connections["dev"]
    assert storage[profile.credential_id] == PASSWORD
    assert PASSWORD not in path.read_text()
    assert PASSWORD not in "\n".join(io.output)
    assert result["connection"] == "dev"


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), EOFError()])
def test_cancel_never_persists(tmp_path, storage, interruption):
    path = tmp_path / "connections.json"
    result = run_wizard(IO(NEW + [interruption]), path)
    assert result["cancelled"] and not path.exists() and not storage


def test_decline_confirmation_then_cancel(tmp_path, storage):
    path = tmp_path / "connections.json"
    assert run_wizard(IO(NEW + ["6", "n", "0"]), path)["cancelled"]
    assert not path.exists() and not storage


def test_noninteractive_fails_before_input(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ToolError) as error:
        run_wizard(path=tmp_path / "connections.json")
    assert error.value.code == "INTERACTIVE_REQUIRED"


def test_password_echo_fallback_is_rejected(monkeypatch):
    import getpass
    import warnings

    def fallback(prompt):
        warnings.warn("fixture", getpass.GetPassWarning, stacklevel=2)
        return PASSWORD

    monkeypatch.setattr("getpass.getpass", fallback)
    with pytest.raises(ToolError):
        Terminal().secret("Password: ")


def test_invalid_inputs_and_password_mismatch(tmp_path, storage):
    answers = [
        "../invalid",
        "dev",
        "https://host",
        "localhost",
        "0",
        "3306",
        "reader",
        "dev",
        "mysql",
        "shop",
        "invalid",
        "1",
        "6",
        "y",
    ]
    io = IO(answers, ("first", "second", PASSWORD, PASSWORD))
    assert run_wizard(io, tmp_path / "connections.json")["verified"]
    assert any("两次密码不一致" in s for s in io.output)


def test_failed_check_requires_explicit_unverified_save(tmp_path, storage, monkeypatch):
    monkeypatch.setattr(
        "mysql_ai.wizard.check_connection",
        lambda *args: {
            "ok": False,
            "databases": [
                {
                    "ok": False,
                    "database": "shop",
                    "error": {"code": "AUTH_FAILED", "message": "检查账号和密码"},
                }
            ],
        },
    )
    path = tmp_path / "connections.json"
    result = run_wizard(IO(NEW + ["6", "n", "6", "y", "y"]), path)
    assert result["ok"] and not result["verified"]


def test_failure_password_retry_then_success(tmp_path, storage, monkeypatch):
    seen = []

    def checker(profile, limits, password):
        seen.append(password)
        return (
            good(profile, limits, password)
            if len(seen) > 1
            else {
                "ok": False,
                "databases": [
                    {
                        "ok": False,
                        "database": "shop",
                        "error": {"code": "AUTH_FAILED", "message": "密码错误"},
                    }
                ],
            }
        )

    monkeypatch.setattr("mysql_ai.wizard.check_connection", checker)
    io = IO(NEW + ["4", "5", "6", "y"], ("bad", "bad", PASSWORD, PASSWORD))
    assert run_wizard(io, tmp_path / "connections.json")["verified"]
    assert seen == ["bad", PASSWORD] and list(storage.values()) == [PASSWORD]


def test_edit_preserves_existing_env_source(tmp_path, storage, settings):
    path = tmp_path / "connections.json"
    save_settings(settings, path)
    old = settings.connections["dev"]
    io = IO(["2", "dev", "", "", "", "", "", "1", "1", "6", "y"], ())
    assert run_wizard(io, path)["verified"]
    new = load_settings(path).connections["dev"]
    assert new.credential_id == old.credential_id and new.password_env == old.password_env
    assert not storage


def test_edit_invalidates_previous_verification(tmp_path, storage):
    io = IO(NEW + ["2", "other", "6", "y", "y"])
    result = run_wizard(io, tmp_path / "connections.json")
    assert not result["verified"]


def test_check_all_databases_with_in_memory_password(settings, monkeypatch):
    profile = settings.connections["dev"]
    profile.databases = ["shop", "reports"]
    seen = []

    def probe(profile, database, limits, *, password=None):
        seen.append((database, password))
        if database == "reports":
            raise ToolError("PERMISSION_DENIED", "没有权限")
        return {"ok": True, "warnings": []}

    monkeypatch.setattr("mysql_ai.db.probe", probe)
    result = connections.check_connection(profile, settings.limits, PASSWORD)
    assert not result["ok"]
    assert seen == [("shop", PASSWORD), ("reports", PASSWORD)]
    assert result["databases"][1]["error"]["code"] == "PERMISSION_DENIED"
    assert PASSWORD not in json.dumps(result)


def test_remote_tls_disabled_is_not_accepted(tmp_path, storage):
    io = IO(["dev", "remote.example", "3306", "reader", "dev", "shop", "3", "1", "6", "y"])
    run_wizard(io, tmp_path / "connections.json")
    assert load_settings(tmp_path / "connections.json").connections["dev"].tls == "verify"
    assert any("仅允许本机测试" in s for s in io.output)


def test_existing_windows_credential_can_be_preserved(tmp_path, storage, settings):
    profile = settings.connections["dev"]
    profile.password_env = None
    storage[profile.credential_id] = PASSWORD
    path = tmp_path / "connections.json"
    save_settings(settings, path)
    result = run_wizard(IO(["2", "dev", "", "", "", "", "", "1", "1", "6", "y"], ()), path)
    assert result["verified"] and storage == {profile.credential_id: PASSWORD}


def test_existing_password_can_be_replaced(tmp_path, storage, settings):
    profile = settings.connections["dev"]
    profile.password_env = None
    storage[profile.credential_id] = "old-value"
    path = tmp_path / "connections.json"
    save_settings(settings, path)
    result = run_wizard(IO(["2", "dev", "", "", "", "", "", "1", "2", "6", "y"]), path)
    assert result["verified"] and profile.credential_id not in storage
    assert list(storage.values()) == [PASSWORD]


def test_ca_path_reprompt(tmp_path, storage):
    ca = tmp_path / "fixture-ca.pem"
    ca.write_text("test-only-placeholder")
    answers = NEW[:-1] + ["2", str(tmp_path / "absent.pem"), str(ca), "6", "y"]
    path = tmp_path / "connections.json"
    run_wizard(IO(answers), path)
    assert load_settings(path).connections["dev"].ssl_ca == str(ca.resolve())


def test_interrupt_after_save_is_not_reported_as_cancelled(tmp_path, storage):
    class InterruptedOutput(IO):
        def show(self, message):
            if message.startswith("已保存"):
                raise KeyboardInterrupt()
            super().show(message)

    path = tmp_path / "connections.json"
    result = run_wizard(InterruptedOutput(NEW + ["6", "y"]), path)
    assert result["ok"] and result["verified"] and not result.get("cancelled")
    assert path.exists()

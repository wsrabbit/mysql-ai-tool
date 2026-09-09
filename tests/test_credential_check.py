from unittest.mock import Mock

import pytest

from mysql_ai.credentials import check_storage
from mysql_ai.errors import ToolError


def test_credential_roundtrip_only_uses_own_record(monkeypatch):
    values = {}
    store = Mock()
    store.set_password.side_effect = lambda service, key, value: values.update(
        {(service, key): value}
    )
    store.get_password.side_effect = lambda service, key: values[service, key]
    store.delete_password.side_effect = lambda service, key: values.pop((service, key))
    monkeypatch.setattr("mysql_ai.credentials.backend", lambda: store)
    check_storage()
    assert not values
    key = store.set_password.call_args.args[1]
    assert key.startswith("self-test-")
    store.delete_password.assert_called_once_with("mysql-ai-tools", key)


def test_credential_cleanup_even_when_verification_fails(monkeypatch):
    store = Mock()
    store.get_password.return_value = "wrong"
    monkeypatch.setattr("mysql_ai.credentials.backend", lambda: store)
    with pytest.raises(ToolError):
        check_storage()
    store.delete_password.assert_called_once()

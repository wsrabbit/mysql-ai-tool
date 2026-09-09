from unittest.mock import Mock

import pymysql
import pytest

from mysql_ai import db
from mysql_ai.errors import ToolError


@pytest.mark.parametrize(
    "code,expected",
    [
        (1045, "AUTH_FAILED"),
        (1142, "PERMISSION_DENIED"),
        (3024, "QUERY_TIMEOUT"),
        (2003, "CONNECTION_FAILED"),
        (2026, "TLS_FAILED"),
        (1146, "SCHEMA_CHANGED"),
    ],
)
def test_raw_driver_errors_are_not_exposed(code, expected):
    error = db.safe_db_error(pymysql.OperationalError(code, "private-password-private-sql"))
    assert error.code == expected
    assert "private" not in error.message


def test_connection_closed_on_execution_error(settings, monkeypatch):
    connection = Mock()
    connection.cursor.return_value.execute.side_effect = pymysql.OperationalError(3024, "private")
    monkeypatch.setattr(db, "connect", lambda *args: connection)
    with pytest.raises(ToolError):
        db.execute(settings.connections["dev"], "shop", settings.limits, "SELECT 1", {}, 1)
    connection.close.assert_called_once()
    connection.cursor.return_value.close.assert_not_called()
    assert connection._result.unbuffered_active is False
    assert connection.cursor.return_value.connection is None

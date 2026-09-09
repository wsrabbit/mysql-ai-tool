import datetime as dt
import time
from decimal import Decimal

from mysql_ai.models import Limits
from mysql_ai.results import collect_rows, encode_value, json_bytes


class Cursor:
    description = [("value", 246)]

    def __init__(self, rows):
        self.rows = iter(rows)

    def fetchone(self):
        return next(self.rows, None)


def test_precision_and_types():
    assert encode_value(Decimal("123.4500"), 100)[0] == "123.4500"
    assert encode_value(2**63, 100)[0] == str(2**63)
    assert encode_value(None, 100)[0] is None
    assert encode_value(dt.datetime(2026, 1, 1, 12), 100)[0] == "2026-01-01T12:00:00"
    assert encode_value("中文" * 100, 9) == ("中文中", True)


def test_row_limit_and_empty_result():
    result = collect_rows(Cursor([[1], [2], [3]]), Limits(), 2, time.monotonic() + 2)
    assert result["returned_rows"] == 2 and result["truncated"]
    assert collect_rows(Cursor([]), Limits(), 2, time.monotonic() + 2)["rows"] == []
    assert not collect_rows(Cursor([[1], [2]]), Limits(), 2, time.monotonic() + 2)["truncated"]


def test_byte_budget():
    limits = Limits(max_bytes=4096, field_bytes=1024)
    result = collect_rows(Cursor([["x" * 1000]] * 100), limits, 100, time.monotonic() + 2)
    assert result["truncated"]
    assert json_bytes(result) < limits.max_bytes


def test_duplicate_column_names_preserved():
    cursor = Cursor([[1, 2]])
    cursor.description = [("id", 3), ("id", 3)]
    result = collect_rows(cursor, Limits(), 2, time.monotonic() + 2)
    assert result["rows"] == [[1, 2]]
    assert [c["name"] for c in result["columns"]] == ["id", "id"]

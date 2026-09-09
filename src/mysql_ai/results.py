import base64
import datetime as dt
import decimal
import json
import math
import time

from mysql_ai.errors import ToolError
from mysql_ai.models import Limits


def json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def encode_value(value, field_bytes: int) -> tuple[object, bool]:
    if value is None or type(value) is bool:
        return value, False
    if type(value) is int:
        return (str(value) if abs(value) > 2**53 - 1 else value), False
    if isinstance(value, decimal.Decimal):
        return str(value), False
    if isinstance(value, float):
        return (value if math.isfinite(value) else str(value)), False
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat(), False
    if isinstance(value, dt.timedelta):
        return str(value), False
    if isinstance(value, bytes):
        part = value[: field_bytes // 2]
        return {"encoding": "base64", "value": base64.b64encode(part).decode("ascii")}, len(
            part
        ) < len(value)
    encoded = str(value).encode("utf-8")
    truncated = len(encoded) > field_bytes
    return encoded[:field_bytes].decode("utf-8", errors="ignore"), truncated


def collect_rows(cursor, limits: Limits, max_rows: int, deadline: float) -> dict:
    from pymysql.constants import FIELD_TYPE

    types = {value: name for name, value in vars(FIELD_TYPE).items() if isinstance(value, int)}
    columns = [
        {"name": str(col[0])[:256], "mysql_type": types.get(col[1], str(col[1]))}
        for col in (cursor.description or [])
    ]
    if len(columns) > 256:
        raise ToolError("RESULT_TOO_WIDE", "结果超过 256 列；请明确选择所需字段。")
    result = {
        "columns": columns,
        "rows": [],
        "returned_rows": 0,
        "truncated": False,
        "warnings": [],
    }
    size = json_bytes(result) + 2048  # reserve envelope + warnings
    if size > limits.max_bytes:
        raise ToolError("RESULT_TOO_WIDE", "字段定义超过响应体上限。")
    truncated_fields = False
    while True:
        if time.monotonic() > deadline:
            raise ToolError("QUERY_TIMEOUT", "查询超过时间预算；结果未作为完整数据返回。")
        row = cursor.fetchone()
        if row is None:
            break
        if len(result["rows"]) >= max_rows:
            result["truncated"] = True
            break
        encoded = []
        for value in row:
            safe, shortened = encode_value(value, limits.field_bytes)
            encoded.append(safe)
            truncated_fields |= shortened
        row_size = json_bytes(encoded) + 2
        if size + row_size > limits.max_bytes:
            result["truncated"] = True
            break
        result["rows"].append(encoded)
        size += row_size
    result["returned_rows"] = len(result["rows"])
    if result["truncated"]:
        result["warnings"].append("结果因行数或响应大小上限截断，不能当作完整数据。")
    if truncated_fields:
        result["warnings"].append("部分长文本或二进制字段已截断。")
        result["fields_truncated"] = True
    return result

"""Fail-closed MySQL SELECT subset; database grants remain an independent boundary."""

import hashlib
import math
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from mysql_ai.errors import ToolError

# An allowlist intentionally excludes table functions, user variables, hints and commands.
ALLOWED_NODES = frozenset(
    "Select From Table Identifier Column Star Alias TableAlias Join Where Group Having Order "
    "Ordered Limit Offset Literal Null Boolean Paren Subquery Distinct And Or Not EQ NEQ GT "
    "GTE LT LTE Is In Between Like ILike Add Sub Mul Div IntDiv Mod Neg Tuple Placeholder "
    "Case If Count Sum Avg Min Max Coalesce Abs Round Ceil Floor Upper Lower Length "
    "Trim Substring Concat Cast DataType DataTypeParam Date DateAdd DateSub DateDiff "
    "CurrentDate CurrentTimestamp Extract Interval Var Year Month Day TimeToStr "
    "StrToDate TimestampTrunc DateTrunc TsOrDsToDate Nullif".split()
)
SAFE_VARS = frozenset({"DAY", "WEEK", "MONTH", "QUARTER", "YEAR", "HOUR", "MINUTE", "SECOND"})


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    params: dict
    fingerprint: str


def reject(message: str = "SQL 超出第一版支持的只读语法范围。") -> None:
    raise ToolError("SQL_REJECTED", message)


def prepare_query(sql: str, params: dict | None, allowed_databases: list[str]) -> QueryPlan:
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode("utf-8")) > 65536:
        reject("SQL 为空或超过 64 KiB。")
    # Conservative by design: also rejects these sequences inside quoted literals.
    # Bind such string values as parameters instead of weakening the lexer boundary.
    if any(mark in sql for mark in ("/*", "--", "#", "@", "\x00", "\\")):
        reject("请移除 SQL 注释、变量和反斜杠；字符串值通过 :name 参数传入。")
    if "__mysql_ai_param_" in sql.lower():
        reject()
    params = {} if params is None else params
    if not isinstance(params, dict) or len(params) > 128:
        reject("params 必须是最多 128 个标量参数的对象。")
    for key, value in params.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", key):
            reject("参数名必须由字母开头，且仅包含字母、数字、下划线。")
        if type(value) not in (str, int, float, bool, type(None)):
            reject("仅支持字符串、数字、布尔值和 null 参数。")
        if isinstance(value, float) and not math.isfinite(value):
            reject("不支持非有限浮点参数。")
        if isinstance(value, str) and len(value.encode("utf-8")) > 65536:
            reject("单个参数超过 64 KiB。")
        if type(value) is int and not -(2**63) <= value < 2**64:
            reject("大整数请使用字符串参数。")
    try:
        trees = sqlglot.parse(sql, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
        if len(trees) != 1 or not isinstance(trees[0], exp.Select):
            reject("第一版仅支持单条 SELECT；CTE、UNION 和写入语句暂不开放。")
        tree = trees[0]
        nodes = list(tree.walk())
        if len(nodes) > 2000:
            reject("SQL 过于复杂。")
        used = set()
        for node in nodes:
            if type(node).__name__ not in ALLOWED_NODES:
                reject()
            if isinstance(node, exp.Identifier) and (len(node.name) > 64 or "\x00" in node.name):
                reject()
            if isinstance(node, exp.Table):
                if node.catalog or not isinstance(node.this, exp.Identifier):
                    reject()
                if node.db and node.db not in allowed_databases:
                    reject("SQL 引用了未允许的数据库。")
                if any(node.args.get(key) for key in ("pivots", "hints", "version", "sample")):
                    reject()
            if isinstance(node, exp.Column):
                if node.catalog or (node.db and node.db not in allowed_databases):
                    reject("字段引用了未允许的数据库。")
            if isinstance(node, exp.Var) and str(node.this).upper() not in SAFE_VARS:
                reject()
            if isinstance(node, exp.Placeholder):
                if not isinstance(node.this, str) or node.this not in params:
                    reject("请使用 :name 占位符，并在 params 中提供同名参数。")
                used.add(node.this)
            if isinstance(node, exp.Select) and any(
                node.args.get(key) for key in ("into", "locks", "hint", "operation_modifiers")
            ):
                reject()
        if used != set(params):
            reject("params 中含有 SQL 未使用的参数。")

        # Replace typed placeholders only; never interpolate values into the SQL text.
        def marker(node):
            if isinstance(node, exp.Placeholder):
                return exp.Var(this=f"__mysql_ai_param_{node.this}__")
            return node

        compiled = tree.transform(marker).sql(
            dialect="mysql", unsupported_level=sqlglot.ErrorLevel.RAISE
        )
        compiled = compiled.replace("%", "%%")
        for name in used:
            compiled = compiled.replace(f"__mysql_ai_param_{name}__", f"%({name})s")
        # Hash a literal-free shape, never SQL or parameter values in logs.
        normalized = tree.transform(
            lambda node: exp.Placeholder() if isinstance(node, exp.Literal) else node
        ).sql(dialect="mysql")
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return QueryPlan(compiled, params, fingerprint)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("SQL_UNSUPPORTED", "SQL 无法按支持的 MySQL 语法解析。") from exc

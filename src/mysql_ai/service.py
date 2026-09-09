import asyncio
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from mysql_ai import db
from mysql_ai.audit import record
from mysql_ai.config import load_settings
from mysql_ai.errors import ToolError
from mysql_ai.models import Settings
from mysql_ai.policy import prepare_query


class DatabaseService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mysql-ai")
        limits = self.settings.limits
        self.active = {
            alias: threading.BoundedSemaphore(limits.concurrency)
            for alias in self.settings.connections
        }
        self.admitted = {
            alias: threading.BoundedSemaphore(limits.concurrency + limits.queue_size)
            for alias in self.settings.connections
        }

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)

    def profile(self, connection: str, database: str | None = None):
        profile = self.settings.connections.get(connection)
        if profile is None:
            raise ToolError("CONNECTION_UNKNOWN", "连接别名不存在；请先列出连接并在本机配置。")
        if database is not None and database not in profile.databases:
            raise ToolError("DATABASE_DENIED", "目标数据库不在该连接的允许列表中。")
        return profile

    def list_connections(self):
        return {
            "ok": True,
            "connections": [
                {
                    "name": alias,
                    "environment": profile.environment,
                    "databases": profile.databases,
                    "mode": "read-only",
                }
                for alias, profile in self.settings.connections.items()
            ],
        }

    async def dispatch(
        self,
        operation: str,
        connection: str,
        database: str | None = None,
        sql: str | None = None,
        params: dict | None = None,
        max_rows: int | None = None,
        table: str | None = None,
    ) -> dict:
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        fingerprint = None
        try:
            profile = self.profile(connection, database)
            limits = self.settings.limits
            row_limit = min(limits.default_rows, limits.max_rows) if max_rows is None else max_rows
            if type(row_limit) is not int or not 1 <= row_limit <= limits.max_rows:
                raise ToolError("INVALID_LIMIT", f"max_rows 必须介于 1 和 {limits.max_rows} 之间。")
            plan = None
            if operation in ("query", "explain_query"):
                if database is None:
                    raise ToolError("DATABASE_REQUIRED", "请明确指定数据库。")
                plan = prepare_query(sql, params, profile.databases)
                fingerprint = plan.fingerprint
            if operation == "describe_table":
                if not table or len(table) > 64 or "\x00" in table:
                    raise ToolError("INVALID_TABLE", "表名必须是 1–64 个有效字符。")

            if not self.admitted[connection].acquire(blocking=False):
                raise ToolError("BUSY", "连接的查询与等待队列已满，请稍后重试。")
            cancelled = threading.Event()

            def work():
                acquired = False
                try:
                    remaining = limits.queue_seconds - (time.monotonic() - started)
                    if remaining <= 0 or not self.active[connection].acquire(timeout=remaining):
                        raise ToolError("BUSY", "等待查询配额超时。")
                    acquired = True
                    if cancelled.is_set():
                        raise ToolError("CANCELLED", "请求在执行前已取消。")
                    return self._perform(operation, profile, database, plan, row_limit, table)
                finally:
                    if acquired:
                        self.active[connection].release()
                    self.admitted[connection].release()

            try:
                future = asyncio.get_running_loop().run_in_executor(self.executor, work)
            except Exception:
                self.admitted[connection].release()
                raise
            # Consume late exceptions without claiming a cancelled thread has stopped.
            future.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=limits.queue_seconds
                    + limits.connect_seconds
                    + limits.query_seconds
                    + 2,
                )
            except TimeoutError as exc:
                cancelled.set()
                raise ToolError(
                    "QUERY_TIMEOUT", "请求超时；后台连接清理完成前仍占用配额。"
                ) from exc
            except asyncio.CancelledError:
                cancelled.set()
                record(
                    request_id=request_id,
                    operation=operation,
                    connection=connection,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    code="CANCELLED",
                )
                raise
            result.update(
                ok=True,
                request_id=request_id,
                connection=connection,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            if database is not None:
                result["database"] = database
            record(
                request_id=request_id,
                operation=operation,
                connection=connection,
                elapsed_ms=result["elapsed_ms"],
                returned_rows=result.get("returned_rows"),
                fingerprint=fingerprint,
                code="OK",
            )
            return result
        except ToolError as exc:
            result = exc.payload()
        except Exception:
            result = ToolError(
                "INTERNAL_ERROR", "工具运行失败；请用请求编号检查本机诊断日志。"
            ).payload()
        result["request_id"] = request_id
        record(
            request_id=request_id,
            operation=operation,
            connection=connection,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            fingerprint=fingerprint,
            code=result["error"]["code"],
        )
        return result

    def _perform(self, operation, profile, database, plan, row_limit, table):
        limits = self.settings.limits
        target = database or profile.databases[0]
        if operation == "test_connection":
            return db.probe(profile, target, limits)
        if operation in ("query", "explain_query"):
            sql = ("EXPLAIN " if operation == "explain_query" else "") + plan.sql
            result = db.execute(profile, target, limits, sql, plan.params, row_limit)
            result["timezone"] = "UTC (TIMESTAMP); DATETIME retains stored wall time"
            return result
        if operation == "list_databases":
            placeholders = ",".join(["%s"] * len(profile.databases))
            return db.execute(
                profile,
                target,
                limits,
                "SELECT SCHEMA_NAME AS database_name FROM information_schema.SCHEMATA "
                f"WHERE SCHEMA_NAME IN ({placeholders}) ORDER BY SCHEMA_NAME",
                tuple(profile.databases),
                row_limit,
            )
        if operation == "list_tables":
            return db.execute(
                profile,
                target,
                limits,
                "SELECT TABLE_NAME AS table_name,TABLE_TYPE AS table_type,TABLE_COMMENT AS comment "
                "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                (target,),
                row_limit,
            )
        if operation == "describe_table":
            # One query returns tagged records; one shared response budget for all metadata.
            statement = """
SELECT 'column' AS kind, COLUMN_NAME AS name, COLUMN_TYPE AS detail,
       IS_NULLABLE AS nullable, COLUMN_DEFAULT AS default_value,
       COLUMN_COMMENT AS comment, ORDINAL_POSITION AS position
FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
UNION ALL
SELECT 'index', INDEX_NAME, CONCAT(COLUMN_NAME, ':unique=', 1-NON_UNIQUE),
       NULL, NULL, INDEX_TYPE, SEQ_IN_INDEX
FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
UNION ALL
SELECT 'foreign_key', CONSTRAINT_NAME,
       CONCAT(COLUMN_NAME, ' -> ', REFERENCED_TABLE_SCHEMA, '.',
              REFERENCED_TABLE_NAME, '.', REFERENCED_COLUMN_NAME),
       NULL, NULL, NULL, ORDINAL_POSITION
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY kind, position
"""
            result = db.execute(profile, target, limits, statement, (target, table) * 3, row_limit)
            if result["returned_rows"] == 0:
                result["warnings"].append("表不存在或账号无权查看该表。")
            return result
        raise ToolError("UNKNOWN_TOOL", "未知数据库操作。")

import ssl
import time

import pymysql

from mysql_ai.credentials import password_for
from mysql_ai.errors import ToolError
from mysql_ai.models import ConnectionProfile, Limits
from mysql_ai.results import collect_rows

SQL_MODE = "STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION"


def safe_db_error(exc: Exception) -> ToolError:
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, ssl.SSLError):
        return ToolError("TLS_FAILED", "TLS 验证失败；请检查 CA、主机名和证书。")
    code = exc.args[0] if isinstance(exc, pymysql.MySQLError) and exc.args else None
    if code in (1045, 1698):
        return ToolError("AUTH_FAILED", "数据库认证失败；请在本机检查账号和密码。")
    if code in (1044, 1142, 1143, 1227, 1370):
        return ToolError("PERMISSION_DENIED", "数据库账号缺少所需权限。")
    if code in (3024, 1205, 1317):
        return ToolError("QUERY_TIMEOUT", "数据库查询超时或已被取消。")
    if code == 2026 or (code == 2003 and "SSL" in str(exc).upper()):
        return ToolError("TLS_FAILED", "TLS 连接失败；请检查证书配置。")
    if code in (2002, 2003, 2006, 2013, 2055):
        return ToolError("CONNECTION_FAILED", "连接失败或中断；检查网络、端口、TLS 和超时设置。")
    if code in (1049, 1146, 1054):
        return ToolError("SCHEMA_CHANGED", "数据库、表或字段不存在；请重新读取结构。")
    return ToolError("DATABASE_ERROR", "数据库拒绝该操作；请检查 SQL 支持范围和数据库设置。")


def connect(profile: ConnectionProfile, database: str, limits: Limits, *, password=None):
    options = dict(
        host=profile.host,
        port=profile.port,
        user=profile.user,
        password=password_for(profile) if password is None else password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=limits.connect_seconds,
        read_timeout=limits.query_seconds,
        write_timeout=limits.query_seconds,
        local_infile=False,
        ssl_disabled=profile.tls == "disabled",
        sql_mode=SQL_MODE,
    )
    if profile.tls == "verify":
        try:
            context = ssl.create_default_context(cafile=profile.ssl_ca)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            options["ssl"] = context
        except (OSError, ssl.SSLError) as exc:
            raise ToolError("TLS_FAILED", "无法读取或解析 CA 证书。") from exc
    conn = pymysql.connect(**options)
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION MAX_EXECUTION_TIME=%s", (limits.query_seconds * 1000,))
            cur.execute("SET SESSION lock_wait_timeout=%s", (limits.query_seconds,))
            cur.execute("SET SESSION time_zone='+00:00'")
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        return conn
    except Exception:
        conn.close()
        raise


def execute(profile, database, limits, sql, params, max_rows):
    conn = None
    cursor = None
    deadline = time.monotonic() + limits.query_seconds
    try:
        conn = connect(profile, database, limits)
        # Closing the dedicated connection, not SSCursor.close(), avoids draining an
        # unbounded unread result when truncating. The connection is never reused.
        cursor = conn.cursor(pymysql.cursors.SSCursor)
        cursor.execute(sql, params)
        return collect_rows(cursor, limits, max_rows, deadline)
    except Exception as exc:
        raise safe_db_error(exc) from exc
    finally:
        if conn is not None:
            # PyMySQL's SSCursor/MySQLResult destructors drain unfinished results.
            # On this disposable connection, explicitly abandon them before closing
            # the socket. This small driver adapter is covered by real-MySQL tests.
            for result in (getattr(cursor, "_result", None), getattr(conn, "_result", None)):
                if result is not None:
                    result.unbuffered_active = False
                    result.has_next = False
            if cursor is not None:
                cursor.connection = None
            conn.close()


def probe(profile, database, limits, *, password=None):
    conn = None
    try:
        conn = connect(profile, database, limits, password=password)
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), @@session.time_zone, @@session.sql_mode")
            version, timezone, mode = cur.fetchone()
            cur.execute("SHOW GRANTS FOR CURRENT_USER")
            grants = [row[0] for row in cur.fetchall()]
            cur.execute("SHOW STATUS LIKE 'Ssl_cipher'")
            tls = bool(cur.fetchone()[1])
        # A diagnostic, deliberately not a complete proof across role/view inheritance.
        write_terms = (
            "ALL PRIVILEGES",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "ALTER",
            "EXECUTE",
            "FILE",
            "SUPER",
            "GRANT OPTION",
        )
        broad = any(any(term in grant.upper() for term in write_terms) for grant in grants)
        warnings = ["权限诊断不覆盖完整角色继承及视图依赖；请使用专用只读账号。"]
        if broad:
            warnings.append("检测到可能的写入或管理权限，建议更换只读账号。")
        if not tls:
            warnings.append("此连接未启用 TLS。")
        return {
            "ok": True,
            "mysql_version": version,
            "timezone": timezone,
            "sql_mode": mode,
            "tls_active": tls,
            "possibly_excessive_grants": broad,
            "warnings": warnings,
        }
    except Exception as exc:
        raise safe_db_error(exc) from exc
    finally:
        if conn is not None:
            conn.close()

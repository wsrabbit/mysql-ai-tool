import asyncio
import os
import sys
import time

import pytest

from mysql_ai.models import ConnectionProfile, Settings
from mysql_ai.service import DatabaseService

pytestmark = pytest.mark.integration


@pytest.fixture
def live_service(tmp_path, monkeypatch):
    if os.environ.get("MYSQL_AI_RUN_INTEGRATION") != "1":
        pytest.skip("Run scripts/test-docker.ps1 to enable disposable MySQL tests")
    monkeypatch.setenv("MYSQL_AI_HOME", str(tmp_path))
    settings = Settings(
        connections={
            "fixture": ConnectionProfile(
                host="127.0.0.1",
                port=int(os.environ["MYSQL_AI_TEST_PORT"]),
                user="ai_reader",
                databases=["shop"],
                tls="disabled",
                password_env="MYSQL_AI_TEST_PASSWORD",
                credential_id="integration",
            )
        }
    )
    service = DatabaseService(settings)
    yield service
    service.close()


def call(service, operation, sql=None, params=None, **kwargs):
    result = asyncio.run(service.dispatch(operation, "fixture", "shop", sql, params, **kwargs))
    assert result["ok"], result
    return result


def test_auth_and_readonly_diagnostic(live_service):
    result = call(live_service, "test_connection")
    assert not result["possibly_excessive_grants"]
    assert not result["tls_active"]


def test_metadata(live_service):
    assert call(live_service, "list_tables")["returned_rows"] >= 2
    result = call(live_service, "describe_table", table="orders")
    assert any(row[0] == "index" for row in result["rows"])


def test_aggregate_precision_parameters_and_join(live_service):
    result = call(
        live_service,
        "query",
        "SELECT c.name,SUM(o.amount) AS total FROM orders o "
        "JOIN customers c ON c.id=o.customer_id WHERE o.status=:status GROUP BY c.name",
        {"status": "paid"},
    )
    assert result["rows"] == [["测试客户", "30.30"]]
    values = call(live_service, "query", "SELECT :value AS value", {"value": "a' OR 1=1 -- % \\"})
    assert values["rows"][0][0] == "a' OR 1=1 -- % \\"


def test_limits_and_explain(live_service):
    result = call(live_service, "query", "SELECT id FROM orders ORDER BY id", max_rows=1)
    assert result["returned_rows"] == 1 and result["truncated"]
    assert call(live_service, "explain_query", "SELECT id FROM orders WHERE id=:id", {"id": 1})[
        "rows"
    ]


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [("EXISTS", [[1], [2]]), ("NOT EXISTS", [[3]])],
)
def test_correlated_exists_and_explain(live_service, predicate, expected):
    sql = (
        f"SELECT o.id FROM orders o WHERE {predicate} "
        "(SELECT 1 FROM customers c WHERE c.id=o.customer_id AND o.status=:status) "
        "ORDER BY o.id"
    )
    params = {"status": "paid"}
    assert call(live_service, "query", sql, params)["rows"] == expected
    assert call(live_service, "explain_query", sql, params)["rows"]


def test_exists_projection_and_nested_subquery(live_service):
    result = call(
        live_service,
        "query",
        "SELECT EXISTS(SELECT 1 FROM orders WHERE status=:paid) AS has_paid, "
        "EXISTS(SELECT 1 FROM orders WHERE status=:missing) AS has_missing, "
        "NOT EXISTS(SELECT 1 FROM orders WHERE status=:missing) AS no_missing",
        {"paid": "paid", "missing": "missing"},
    )
    assert result["rows"] == [[1, 0, 1]]
    nested = call(
        live_service,
        "query",
        "SELECT c.id FROM customers c WHERE EXISTS (SELECT 1 FROM orders o "
        "WHERE o.customer_id=c.id AND EXISTS "
        "(SELECT 1 FROM orders i WHERE i.id=o.id AND i.status=:status))",
        {"status": "paid"},
    )
    assert nested["rows"] == [[1]]


def test_mysql_rejects_write_even_bypassing_tool(live_service):
    from mysql_ai import db
    from mysql_ai.errors import ToolError

    with pytest.raises(ToolError):
        db.execute(
            live_service.settings.connections["fixture"],
            "shop",
            live_service.settings.limits,
            "DELETE FROM orders",
            (),
            1,
        )
    assert call(live_service, "query", "SELECT COUNT(*) FROM orders")["rows"] == [[3]]


def test_numeric_types_and_duplicate_names(live_service):
    result = call(
        live_service,
        "query",
        "SELECT 9223372036854775808 AS value, "
        "CAST(12.3400 AS DECIMAL(20,4)) AS value, NULL AS empty",
    )
    assert result["rows"] == [["9223372036854775808", "12.3400", None]]
    assert [c["name"] for c in result["columns"]] == ["value", "value", "empty"]


def test_stdio_queries_real_database(live_service):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from mysql_ai.config import save_settings

    save_settings(live_service.settings)

    async def scenario():
        executable = os.environ.get("MYSQL_AI_TEST_EXECUTABLE")
        parameters = StdioServerParameters(
            command=executable or sys.executable,
            args=["serve"] if executable else ["-m", "mysql_ai", "serve"],
            env=dict(os.environ),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "query",
                    {
                        "connection": "fixture",
                        "database": "shop",
                        "sql": "SELECT SUM(amount) AS total FROM orders WHERE status=:status",
                        "params": {"status": "paid"},
                    },
                )
                assert not result.isError
                assert result.structuredContent["rows"] == [["30.30"]]
                exists = await session.call_tool(
                    "query",
                    {
                        "connection": "fixture",
                        "database": "shop",
                        "sql": "SELECT c.id FROM customers c WHERE EXISTS "
                        "(SELECT 1 FROM orders o "
                        "WHERE o.customer_id=c.id AND o.status=:status)",
                        "params": {"status": "paid"},
                    },
                )
                assert not exists.isError
                assert exists.structuredContent["rows"] == [[1]]

    asyncio.run(asyncio.wait_for(scenario(), 25))


def test_tls_verification_rejects_untrusted_certificate(live_service):
    live_service.settings.connections["fixture"].tls = "verify"
    result = asyncio.run(live_service.dispatch("test_connection", "fixture", "shop"))
    assert result["error"]["code"] == "TLS_FAILED"


def test_server_timeout_and_connection_cleanup(live_service):
    from mysql_ai import db
    from mysql_ai.errors import ToolError

    profile = live_service.settings.connections["fixture"]
    limits = live_service.settings.limits.model_copy(update={"query_seconds": 1})
    started = time.monotonic()
    # Internal driver test: SLEEP is deliberately unavailable through the MCP SQL policy.
    statement = "SELECT SLEEP(5) FROM orders"
    with pytest.raises(ToolError) as error:
        db.execute(profile, "shop", limits, statement, {}, 1)
    assert error.value.code in {"QUERY_TIMEOUT", "CONNECTION_FAILED"}
    assert time.monotonic() - started < 4
    observer = db.connect(profile, "shop", live_service.settings.limits)
    try:
        for _ in range(20):
            with observer.cursor() as cursor:
                cursor.execute("SHOW PROCESSLIST")
                running = [row for row in cursor.fetchall() if row[7] == statement]
            if not running:
                break
            time.sleep(0.1)
        assert not running, "Timed-out query remained active on server"
    finally:
        observer.close()


def test_ephemeral_password_checks_all_databases(live_service, monkeypatch):
    from mysql_ai.connections import check_connection

    profile = live_service.settings.connections["fixture"].model_copy(
        update={"databases": ["shop", "shop_reports"]}
    )
    password = os.environ["MYSQL_AI_TEST_PASSWORD"]
    monkeypatch.delenv("MYSQL_AI_TEST_PASSWORD")
    result = check_connection(profile, live_service.settings.limits, password)
    assert result["ok"]
    assert [r["database"] for r in result["databases"]] == ["shop", "shop_reports"]


def test_ephemeral_password_rejects_bad_auth(live_service):
    from mysql_ai.connections import check_connection

    result = check_connection(
        live_service.settings.connections["fixture"],
        live_service.settings.limits,
        "deliberately-wrong-fixture-password",
    )
    assert not result["ok"]
    assert result["databases"][0]["error"]["code"] == "AUTH_FAILED"


def test_wizard_detects_partial_database_permission(live_service):
    from mysql_ai.connections import check_connection

    profile = live_service.settings.connections["fixture"].model_copy(
        update={"databases": ["shop", "shop_private"]}
    )
    result = check_connection(
        profile, live_service.settings.limits, os.environ["MYSQL_AI_TEST_PASSWORD"]
    )
    assert not result["ok"] and result["databases"][0]["ok"]
    assert result["databases"][1]["error"]["code"] == "PERMISSION_DENIED"


def test_wizard_checks_tls_without_downgrading(live_service):
    from mysql_ai.connections import check_connection

    profile = live_service.settings.connections["fixture"].model_copy(update={"tls": "verify"})
    result = check_connection(
        profile, live_service.settings.limits, os.environ["MYSQL_AI_TEST_PASSWORD"]
    )
    assert result["databases"][0]["error"]["code"] == "TLS_FAILED"
    assert profile.tls == "verify"


def test_wizard_real_connection_and_save(live_service, tmp_path, monkeypatch):
    from mysql_ai.config import load_settings
    from mysql_ai.wizard import run_wizard

    stored = {}
    password = os.environ["MYSQL_AI_TEST_PASSWORD"]
    answers = iter(
        [
            "wizard_live",
            "127.0.0.1",
            os.environ["MYSQL_AI_TEST_PORT"],
            "ai_reader",
            "test",
            "shop,shop_reports",
            "3",
            "y",
            "6",
            "y",
        ]
    )

    class FixtureTerminal:
        def ask(self, prompt):
            return next(answers)

        def secret(self, prompt):
            return password

        def show(self, message):
            assert password not in message

    monkeypatch.setattr(
        "mysql_ai.credentials.set_password", lambda key, value: stored.update({key: value})
    )
    path = tmp_path / "wizard-config.json"
    result = run_wizard(FixtureTerminal(), path)
    assert result["verified"]
    profile = load_settings(path).connections["wizard_live"]
    assert stored[profile.credential_id] == password
    assert profile.databases == ["shop", "shop_reports"]
    assert password not in path.read_text()

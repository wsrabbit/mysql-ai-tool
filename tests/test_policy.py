import pytest
from hypothesis import given
from hypothesis import strategies as st
from pymysql import Connection

from mysql_ai.errors import ToolError
from mysql_ai.policy import prepare_query


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM orders WHERE status=:status ORDER BY id LIMIT 10",
        "SELECT o.id, SUM(i.amount) AS total FROM shop.orders o JOIN shop.items i "
        "ON o.id=i.order_id GROUP BY o.id HAVING SUM(i.amount)>:status",
        "SELECT (SELECT COUNT(*) FROM orders) AS n WHERE :status IS NOT NULL",
        "SELECT DATE(created_at), COUNT(*) FROM orders WHERE status=:status "
        "GROUP BY DATE(created_at)",
        "SELECT COALESCE(amount,0), ROUND(amount,2) FROM orders WHERE status=:status",
    ],
)
def test_supported(sql):
    plan = prepare_query(sql, {"status": "paid"}, ["shop"])
    assert "%(status)s" in plan.sql
    assert plan.params == {"status": "paid"}


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DELETE FROM orders",
        "SELECT 1; SELECT 2",
        "SELECT * FROM mysql.user",
        "SELECT * FROM other.orders",
        "SELECT * FROM orders o JOIN other.items i ON 1=1",
        "SELECT (SELECT COUNT(*) FROM mysql.user)",
        "SELECT 1 INTO OUTFILE '/tmp/x'",
        "SELECT 1 INTO DUMPFILE '/tmp/x'",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders LOCK IN SHARE MODE",
        "SELECT /*+ MAX_EXECUTION_TIME(0) */ 1",
        "SELECT /*!50000 SLEEP(1) */ 1",
        "SELECT /* harmless */ 1",
        "SELECT SLEEP(10)",
        "SELECT BENCHMARK(100,1)",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT GET_LOCK('x',1)",
        "SELECT RELEASE_LOCK('x')",
        "SELECT shop.custom_function()",
        "SELECT custom_function()",
        "SELECT @x:=1",
        "SELECT @@version",
        "CALL p()",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT 1 UNION SELECT 2",
        "SELECT * FROM orders PROCEDURE ANALYSE()",
        "SELECT 1 -- comment",
        "SELECT 1 # comment",
        "SELECT SQL_CALC_FOUND_ROWS * FROM orders",
        "SELECT * FROM information_schema.tables",
        "SELECT ?",
        "SELECT :missing",
        "SELECT '__mysql_ai_param_x__'",
        "SELECT * FROM a.b.orders",
        "SET NAMES utf8mb4",
        "SELECT * FROM orders;",  # overwritten below: trailing semicolon may be supported
    ],
)
def test_rejected(sql):
    if sql == "SELECT * FROM orders;":
        assert prepare_query(sql, {}, ["shop"]).sql == "SELECT * FROM orders"
    else:
        with pytest.raises(ToolError):
            prepare_query(sql, {}, ["shop"])


def test_parameters_are_driver_bound():
    value = "x' OR 1=1; DROP TABLE orders; -- % \\"
    plan = prepare_query("SELECT :x, :x, '100%'", {"x": value}, ["shop"])
    assert value not in plan.sql
    assert plan.sql.count("%(x)s") == 2
    conn = Connection(defer_connect=True)
    conn.server_status = 0
    rendered = conn.cursor().mogrify(plan.sql, plan.params)
    assert "100%" in rendered
    assert "\\'" in rendered


@pytest.mark.parametrize("params", [{"extra": 1}, {"x": []}, {"x": float("nan")}, {"x": 2**100}])
def test_invalid_params(params):
    with pytest.raises(ToolError):
        prepare_query("SELECT :x", params, ["shop"])


def test_fingerprint_omits_values():
    assert (
        prepare_query("SELECT 1", {}, ["shop"]).fingerprint
        == prepare_query("SELECT 2", {}, ["shop"]).fingerprint
    )


@given(st.text(max_size=200))
def test_arbitrary_input_fails_cleanly(sql):
    try:
        plan = prepare_query(sql, {}, ["shop"])
        assert plan.sql.upper().startswith("SELECT")
    except ToolError:
        pass

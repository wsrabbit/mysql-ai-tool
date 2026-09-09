import asyncio
import threading

from mysql_ai.service import DatabaseService


def test_policy_rejection_never_calls_database(settings, monkeypatch):
    service = DatabaseService(settings)

    def fail(*args):
        raise AssertionError("must not reach database")

    monkeypatch.setattr(service, "_perform", fail)
    result = asyncio.run(service.dispatch("query", "dev", "shop", "DELETE FROM orders"))
    assert result["error"]["code"] == "SQL_REJECTED"
    result = asyncio.run(service.dispatch("query", "dev", "mysql", "SELECT 1"))
    assert result["error"]["code"] == "DATABASE_DENIED"
    service.close()


def test_cancelled_work_keeps_concurrency_slot(settings, monkeypatch):
    settings.limits.concurrency = 1
    settings.limits.queue_size = 0
    started, finish = threading.Event(), threading.Event()
    service = DatabaseService(settings)

    def slow(*args):
        started.set()
        finish.wait(3)
        return {"ok": True}

    monkeypatch.setattr(service, "_perform", slow)

    async def scenario():
        task = asyncio.create_task(service.dispatch("test_connection", "dev"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        busy = await service.dispatch("test_connection", "dev")
        assert busy["error"]["code"] == "BUSY"
        finish.set()

    try:
        asyncio.run(scenario())
    finally:
        finish.set()
        service.close()

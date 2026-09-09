import json
import logging
from logging.handlers import RotatingFileHandler

from mysql_ai.config import data_home


def audit_logger() -> logging.Logger:
    logger = logging.getLogger("mysql_ai.audit")
    if not logger.handlers:
        logdir = data_home() / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            logdir / "operations.jsonl", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def record(**fields) -> None:
    # Do not expand this allowlist with SQL text, params, result data or raw exceptions.
    allowed = {
        "request_id",
        "operation",
        "connection",
        "elapsed_ms",
        "returned_rows",
        "code",
        "fingerprint",
    }
    audit_logger().info(
        json.dumps({k: v for k, v in fields.items() if k in allowed}, ensure_ascii=True)
    )

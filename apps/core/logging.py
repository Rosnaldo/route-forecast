"""Structured logging: every log line carries the current request id."""

import json
import logging
from contextvars import ContextVar

# A ContextVar (not a thread-local) so the value is correct for both threads
# and asyncio tasks under ASGI.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    """One JSON object per line: easy to ship to CloudWatch / Loki / ELK."""

    RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "request_id", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # Anything passed via `extra={...}` becomes a top-level key.
        payload |= {k: v for k, v in vars(record).items() if k not in self.RESERVED}
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

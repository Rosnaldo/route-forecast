import json
import logging

from apps.core.logging import JSONFormatter, RequestIDFilter, request_id_var


def test_json_formatter_includes_request_id_and_extra():
    token = request_id_var.set("req-1")
    try:
        record = logging.makeLogRecord(
            {"name": "x", "levelname": "INFO", "msg": "hi %s", "args": ("there",), "duration_ms": 3}
        )
        RequestIDFilter().filter(record)
        payload = json.loads(JSONFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["message"] == "hi there"
    assert payload["request_id"] == "req-1"
    assert payload["duration_ms"] == 3

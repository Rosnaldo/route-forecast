"""
Two middleware styles:

- RequestIDMiddleware supports both sync and async requests natively
  (no thread hop under ASGI), the "hybrid" style.
- RequestTimingMiddleware is a classic sync class; Django adapts it for ASGI.
"""

import logging
import time
import uuid

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.db import connection

from .logging import request_id_var

logger = logging.getLogger("apps.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def _start(self, request) -> object:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.request_id = request_id
        return request_id_var.set(request_id)

    def _finish(self, request, response, token):
        response[REQUEST_ID_HEADER] = request.request_id
        request_id_var.reset(token)
        return response

    def __call__(self, request):
        if self.is_async:
            return self.__acall__(request)
        token = self._start(request)
        return self._finish(request, self.get_response(request), token)

    async def __acall__(self, request):
        token = self._start(request)
        return self._finish(request, await self.get_response(request), token)


class RequestTimingMiddleware:
    """Logs method, path, status, duration and number of SQL queries."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        queries_before = len(connection.queries)  # only populated when DEBUG=True
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        logger.info(
            "%s %s -> %s",
            request.method,
            request.path,
            response.status_code,
            extra={
                "duration_ms": round(duration_ms, 1),
                "status": response.status_code,
                "queries": len(connection.queries) - queries_before,
            },
        )
        return response

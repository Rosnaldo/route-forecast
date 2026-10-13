"""
Two middleware styles:

- RequestIDMiddleware supports both sync and async requests natively
  (no thread hop under ASGI), the "hybrid" style.
- RequestTimingMiddleware is a classic sync class; Django adapts it for ASGI.
"""

import logging
import time
import uuid
import zlib

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.middleware.gzip import GZipMiddleware as DjangoGZipMiddleware
from django.middleware.gzip import re_accepts_gzip
from django.utils.cache import patch_vary_headers

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
    """Logs method, path, status and duration."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
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
            },
        )
        return response


class GZipMiddleware(DjangoGZipMiddleware):
    """Django's GZip, plus event streams. Django's buffers its output, which would hold
    server-sent events back; for those, each event is compressed and flushed on its
    own, so it reaches the browser compressed and at once."""

    def process_response(self, request, response):
        if not response.get("Content-Type", "").startswith("text/event-stream"):
            return super().process_response(request, response)
        if response.has_header("Content-Encoding") or not re_accepts_gzip.search(
            request.META.get("HTTP_ACCEPT_ENCODING", "")
        ):
            return response
        patch_vary_headers(response, ("Accept-Encoding",))
        response["Content-Encoding"] = "gzip"
        compressor = zlib.compressobj(wbits=31)  # 31: gzip format

        def flushed(chunk) -> bytes:
            data = chunk.encode() if isinstance(chunk, str) else chunk
            return compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)

        content = response.streaming_content
        if response.is_async:

            async def compressed():
                async for chunk in content:
                    yield flushed(chunk)
                yield compressor.flush()

        else:

            def compressed():
                for chunk in content:
                    yield flushed(chunk)
                yield compressor.flush()

        response.streaming_content = compressed()
        return response

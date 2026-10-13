"""The weather stream: server-sent events for a computed trip."""

import json
from types import SimpleNamespace

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.core.handlers.asgi import ASGIRequest
from django.http import JsonResponse, StreamingHttpResponse
from django.views import View

from apps.core.exceptions import NotFoundError

from ..business.weather import point_series
from ..domain.trip import TripGrid
from ..domain.weather import FailedBatch
from ..services import trips
from .requests import validate_trip_id
from .responses import GridEventSerializer, StreamedPointSerializer


class WeatherStreamView(View):
    """Server-sent events for a computed trip: its grid, then its forecasts batch by
    batch as they arrive (start of the trip first):

        event: grid         data: {now, start, hours, weight_lb, points, cells, counties,
                                   routes: [{counties, cells}]}
        event: batch        data: {"points": [{index, lat, lon, wind_mph, ..., levels}]}
        event: batch-error  data: {"indices": [...], "detail": "..."}
        event: done         data: {"loaded": n, "failed": m}

    A plain Django view: browsers' EventSource asks for text/event-stream, which DRF's
    content negotiation would refuse."""

    def get(self, request, trip_id: str):
        try:
            validate_trip_id(trip_id)
        except ValidationError as exc:
            return JsonResponse({"code": "invalid", "detail": exc.messages[0]}, status=400)
        try:
            stream = trips.weather_stream(trip_id)
        except NotFoundError as exc:
            return JsonResponse({"code": exc.code, "detail": exc.message}, status=404)
        events = _events(stream)
        if isinstance(request, ASGIRequest):
            # Under ASGI, Django would collect a plain generator whole before sending it.
            events = _event_by_event(events)
        response = StreamingHttpResponse(events, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # nginx: pass each event through at once
        return response


def _events(stream):
    loaded = failed = 0
    for event in stream:
        if isinstance(event, TripGrid):
            yield _sse("grid", GridEventSerializer(_grid_event(event)).data)
        elif isinstance(event, FailedBatch):
            failed += len(event.indices)
            yield _sse("batch-error", {"indices": event.indices, "detail": event.detail})
        else:
            loaded += len(event.points)
            points = [{"index": i, **_point_fields(point)} for i, point in event.points]
            yield _sse("batch", {"points": StreamedPointSerializer(points, many=True).data})
    yield _sse("done", {"loaded": loaded, "failed": failed})


def _grid_event(grid: TripGrid) -> SimpleNamespace:
    """GridEventSerializer's input: the weather grid plus the counties, per route too."""
    weather, counties = grid.weather, grid.counties
    return SimpleNamespace(
        **vars(weather),
        counties=list({c.fips: c for cs in counties for c in cs}.values()),
        routes=[
            {"counties": [c.fips for c in route_counties], "cells": cells}
            for route_counties, cells in zip(counties, weather.route_cells, strict=True)
        ],
    )


async def _event_by_event(events):
    """An async iterator over a blocking generator: each event is produced in a worker
    thread and sent as soon as it is ready."""
    done = object()
    while (event := await sync_to_async(next, thread_sensitive=False)(events, done)) is not done:
        yield event


def _point_fields(point) -> dict:
    """A GridPoint's position and series, for StreamedPointSerializer."""
    return {"lat": point.lat, "lon": point.lon, **point_series(point)}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"

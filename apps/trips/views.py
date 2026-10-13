import csv
import json
import time
from types import SimpleNamespace

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.asgi import ASGIRequest
from django.http import JsonResponse, StreamingHttpResponse
from django.views import View
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError

from .checkpoints import Trip, cached_route_risks, load_trip, save_trip, trip_checkpoints
from .grid import build_grid, ensure_grid
from .recommendation import recommend
from .routing import compute_routes
from .weather import FORECAST_HOURS, FailedBatch, forecast_events

EXAMPLE_ROUTES_FILE = settings.BASE_DIR / "example_routes.csv"
WEIGHT_MIN_LB = 1_000  # cargo weight accepted by the route endpoint
WEIGHT_MAX_LB = 100_000


class PointSerializer(serializers.Serializer):
    """Either coordinates ({lat, lon}) or a place name Google can geocode ({address})."""

    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)
    address = serializers.CharField(max_length=200, required=False)

    def to_internal_value(self, data):
        """Return (lat, lon) or the address string, as compute_route expects."""
        attrs = super().to_internal_value(data)
        if "address" in attrs and not ({"lat", "lon"} & attrs.keys()):
            return attrs["address"]
        if {"lat", "lon"} <= attrs.keys() and "address" not in attrs:
            return attrs["lat"], attrs["lon"]
        raise serializers.ValidationError("Give either lat and lon, or address.")


class RouteRequestSerializer(serializers.Serializer):
    departure = PointSerializer()
    arrival = PointSerializer()
    weight_lb = serializers.FloatField(min_value=WEIGHT_MIN_LB, max_value=WEIGHT_MAX_LB)


class CountySerializer(serializers.Serializer):
    fips = serializers.CharField()
    name = serializers.CharField()
    state = serializers.CharField()
    geometry = serializers.JSONField(source="outline", allow_null=True)


class GridPointSerializer(serializers.Serializer):
    """A grid cell center: hourly series from WeatherGrid.start, null where no forecast."""

    lat = serializers.FloatField()
    lon = serializers.FloatField()
    wind_mph = serializers.ListField(child=serializers.FloatField(allow_null=True))
    rain_in_hr = serializers.ListField(child=serializers.FloatField(allow_null=True))
    snow_in_hr = serializers.ListField(child=serializers.FloatField(allow_null=True))
    levels = serializers.ListField(child=serializers.IntegerField(allow_null=True))


class WeatherCellSerializer(serializers.Serializer):
    """One grid cell clipped to one county; `point` indexes WeatherGridSerializer.points."""

    point = serializers.IntegerField()
    fips = serializers.CharField(source="county.fips")
    geometry = serializers.JSONField(source="outline")


class WeatherGridSerializer(serializers.Serializer):
    """The grid's layout; the forecasts for its points arrive from the weather stream."""

    now = serializers.IntegerField()
    start = serializers.IntegerField()
    hours = serializers.SerializerMethodField()
    weight_lb = serializers.FloatField()
    points = serializers.SerializerMethodField()  # [{lat, lon}], in streaming order
    cells = WeatherCellSerializer(many=True)

    def get_hours(self, grid) -> int:
        return FORECAST_HOURS

    def get_points(self, grid) -> list[dict]:
        return [{"lat": lat, "lon": lon} for lat, lon in grid.points]


class RouteCellSerializer(serializers.Serializer):
    """A cell the route covers: `cell` indexes WeatherGridSerializer.cells."""

    cell = serializers.IntegerField()
    offset_s = serializers.IntegerField()  # when the truck passes nearest, after departure


class RouteSerializer(serializers.Serializer):
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()  # Google's car drive time; ETAs: timing.py
    description = serializers.CharField()
    source = serializers.CharField()  # "google", or a fallback: "avoid_highways" / "detour"
    points = serializers.ListField(  # [lat, lon], simplified for drawing
        source="display_points", child=serializers.ListField(child=serializers.FloatField())
    )


class RouteResponseSerializer(serializers.Serializer):
    """Google's routes, returned as soon as they are known: counties, grid and forecasts
    follow on the weather stream (WeatherStreamView)."""

    trip_id = serializers.CharField()  # for the stream, checkpoints and recommendation
    weight_lb = serializers.FloatField()
    routes = RouteSerializer(many=True)  # fastest first


class RouteGridSerializer(serializers.Serializer):
    counties = serializers.ListField(child=serializers.CharField())  # fips, in travel order
    cells = RouteCellSerializer(many=True)


class GridEventSerializer(WeatherGridSerializer):
    """The stream's first event: the grid's layout, the counties crossed (each once) and,
    per route (same order as the route response), its counties and cells."""

    counties = CountySerializer(many=True)
    routes = RouteGridSerializer(many=True)


class RouteView(APIView):
    """Up to three driving routes between departure and arrival (Google's, plus fallbacks
    when it has fewer), returned as soon as Google answers. The counties they cross and
    the weather risk on a grid over them, for a truck carrying `weight_lb` of cargo,
    come from the weather stream for the returned `trip_id`."""

    serializer_class = RouteRequestSerializer

    def post(self, request: Request, version: str) -> Response:
        params = RouteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        departure, arrival, weight_lb = (
            params.validated_data[key] for key in ("departure", "arrival", "weight_lb")
        )
        routes = compute_routes(departure, arrival)
        trip_id = save_trip(Trip(routes, weight_lb))
        data = {"trip_id": trip_id, "weight_lb": weight_lb, "routes": routes}
        return Response(RouteResponseSerializer(data).data)


class TripDepartureSerializer(serializers.Serializer):
    trip_id = serializers.CharField(max_length=64)  # from the route endpoint
    departure = serializers.DateTimeField()  # within the forecast window

    def validate_departure(self, value):
        now = time.time()
        # An hour of slack: the form computes the time from when the routes loaded.
        if not now - 3600 <= value.timestamp() <= now + FORECAST_HOURS * 3600:
            raise serializers.ValidationError(
                f"Departure must be within the next {FORECAST_HOURS} hours."
            )
        return value


class StreamedPointSerializer(GridPointSerializer):
    index = serializers.IntegerField()  # into the route response's weather.points


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

    def get(self, request, version: str, trip_id: str):
        try:
            trip = load_trip(trip_id)
        except NotFoundError as exc:
            return JsonResponse({"code": exc.code, "detail": exc.message}, status=404)
        events = self._events(trip_id, trip)
        if isinstance(request, ASGIRequest):
            # Under ASGI, Django would collect a plain generator whole before sending it.
            events = _event_by_event(events)
        response = StreamingHttpResponse(events, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # nginx: pass each event through at once
        return response

    def _events(self, trip_id: str, trip: Trip):
        grid = build_grid(trip_id, trip)
        yield _sse("grid", GridEventSerializer(_grid_event(grid)).data)
        loaded = failed = 0
        for event in forecast_events(list(grid.trip.points), grid.trip.start, trip.weight_lb):
            if isinstance(event, FailedBatch):
                failed += len(event.indices)
                yield _sse("batch-error", {"indices": event.indices, "detail": event.detail})
            else:
                loaded += len(event.points)
                points = [{"index": i, **_point_fields(point)} for i, point in event.points]
                yield _sse("batch", {"points": StreamedPointSerializer(points, many=True).data})
        yield _sse("done", {"loaded": loaded, "failed": failed})


def _grid_event(grid) -> SimpleNamespace:
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
    """A GridPoint's fields and series, for StreamedPointSerializer."""
    return {
        "lat": point.lat,
        "lon": point.lon,
        "wind_mph": point.wind_mph,
        "rain_in_hr": point.rain_in_hr,
        "snow_in_hr": point.snow_in_hr,
        "levels": point.levels,
    }


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


class CheckpointsRequestSerializer(TripDepartureSerializer):
    distance_mi = serializers.ChoiceField(choices=[10, 25, 50])  # gap between checkpoints


class CheckpointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    distance_m = serializers.IntegerField()  # along the route, from departure
    elapsed_s = serializers.IntegerField()  # expected travel time from departure
    breaks = serializers.IntegerField()  # 30-min driver breaks included in elapsed_s
    eta = serializers.IntegerField()  # unix time
    wind_mph = serializers.FloatField(source="forecast.wind_mph", allow_null=True, default=None)
    rain_in_hr = serializers.FloatField(source="forecast.rain_in_hr", allow_null=True, default=None)
    snow_in_hr = serializers.FloatField(source="forecast.snow_in_hr", allow_null=True, default=None)
    level = serializers.IntegerField(allow_null=True)  # risk level; null beyond the window
    is_arrival = serializers.BooleanField()


class RouteCheckpointsSerializer(serializers.Serializer):
    checkpoints = CheckpointSerializer(many=True)
    # Miles at each risk level when the truck gets there, segment by segment along the
    # route: low, moderate, high, severe, no_travel, and no_forecast (beyond the window).
    miles_by_level = serializers.DictField(child=serializers.FloatField())


class CheckpointsResponseSerializer(serializers.Serializer):
    distance_mi = serializers.IntegerField()
    departure = serializers.DateTimeField()
    routes = RouteCheckpointsSerializer(many=True)  # route order


class CheckpointsView(APIView):
    """Checkpoints every `distance_mi` miles along each route of a computed trip, with
    the expected travel time to each and the weather risk when the truck gets there,
    leaving at `departure`; plus each route's miles at each risk level."""

    serializer_class = CheckpointsRequestSerializer

    def post(self, request: Request, version: str) -> Response:
        params = CheckpointsRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        trip_id, distance_mi, departure = (
            params.validated_data[key] for key in ("trip_id", "distance_mi", "departure")
        )
        trip = ensure_grid(trip_id, load_trip(trip_id))
        risks = cached_route_risks(trip_id, trip, departure.timestamp())
        checkpoints = trip_checkpoints(trip, distance_mi, departure.timestamp(), risks=risks)
        data = {"distance_mi": distance_mi, "departure": departure, "routes": checkpoints}
        return Response(CheckpointsResponseSerializer(data).data)


class RouteScoreSerializer(serializers.Serializer):
    route = serializers.IntegerField()  # index in the route endpoint's routes
    severe_miles = serializers.FloatField()  # Severe + No Travel
    high_miles = serializers.FloatField()
    average_level = serializers.FloatField(allow_null=True)  # 0-4; null: no forecast
    travel_s = serializers.IntegerField()  # breaks included


class RecommendationResponseSerializer(serializers.Serializer):
    departure = serializers.DateTimeField()
    recommended = serializers.IntegerField()  # index in the route endpoint's routes
    # The criterion that put the recommendation ahead of the runner-up (one of
    # recommendation.CRITERIA), "tie", or null with a single route.
    decided_by = serializers.CharField(allow_null=True)
    ranking = RouteScoreSerializer(many=True)  # best first


class RecommendationView(APIView):
    """The route to take for a computed trip leaving at `departure`: routes ranked by
    Severe miles, High miles, average risk, then travel time (see recommendation.py)."""

    serializer_class = TripDepartureSerializer

    def post(self, request: Request, version: str) -> Response:
        params = TripDepartureSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        trip_id = params.validated_data["trip_id"]
        departure = params.validated_data["departure"]
        # Usually already computed by the checkpoints request for the same departure.
        trip = ensure_grid(trip_id, load_trip(trip_id))
        risks = cached_route_risks(trip_id, trip, departure.timestamp())
        recommendation = recommend(risks)
        data = {
            "departure": departure,
            "recommended": recommendation.ranking[0].route,
            **recommendation._asdict(),
        }
        return Response(RecommendationResponseSerializer(data).data)


class ExampleRoutesView(APIView):
    """Sample trips from example_routes.csv, for trying the route endpoint."""

    def get(self, request: Request, version: str) -> Response:
        with EXAMPLE_ROUTES_FILE.open(newline="") as file:
            rows = [
                {**row, "id": int(row["id"]), "distance_km": int(row["distance_km"])}
                for row in csv.DictReader(file)
            ]
        return Response(rows)

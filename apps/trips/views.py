import csv
import time

from django.conf import settings
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .checkpoints import Trip, load_trip, route_risks, save_trip, trip_checkpoints
from .counties import counties_along
from .recommendation import recommend
from .routing import compute_routes
from .weather import FORECAST_HOURS, weather_grid

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
    """Hourly forecasts and grid cells, each sent once and shared by the routes."""

    now = serializers.IntegerField()
    start = serializers.IntegerField()
    hours = serializers.SerializerMethodField()
    weight_lb = serializers.FloatField()
    points = GridPointSerializer(many=True)
    cells = WeatherCellSerializer(many=True)

    def get_hours(self, grid) -> int:
        return FORECAST_HOURS


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
        source="route.display_points", child=serializers.ListField(child=serializers.FloatField())
    )
    counties = serializers.ListField(child=serializers.CharField())  # fips, in travel order
    cells = RouteCellSerializer(many=True)


class RouteResponseSerializer(serializers.Serializer):
    trip_id = serializers.CharField()  # for the checkpoints endpoint, valid for an hour
    routes = RouteSerializer(many=True)  # fastest first
    counties = CountySerializer(many=True)  # every county any route crosses, once
    weather = WeatherGridSerializer()


class RouteView(APIView):
    """Up to three driving routes between departure and arrival (Google's, plus fallbacks
    when it has fewer): [lat, lon] points and counties crossed for each, and the hourly
    weather risk for the next FORECAST_HOURS on a grid over those counties, for a
    truck carrying `weight_lb` of cargo."""

    serializer_class = RouteRequestSerializer

    def post(self, request: Request, version: str) -> Response:
        params = RouteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        departure, arrival, weight_lb = (
            params.validated_data[key] for key in ("departure", "arrival", "weight_lb")
        )
        routes = compute_routes(departure, arrival)
        counties = [counties_along(route.points) for route in routes]
        weather = weather_grid(list(zip(routes, counties, strict=True)), weight_lb)
        trip_id = save_trip(Trip(routes, weight_lb, weather.step))
        data = {
            "trip_id": trip_id,
            "routes": [
                {
                    **vars(route),
                    "route": route,
                    "counties": [county.fips for county in route_counties],
                    "cells": cells,
                }
                for route, route_counties, cells in zip(
                    routes, counties, weather.route_cells, strict=True
                )
            ],
            "counties": list({c.fips: c for cs in counties for c in cs}.values()),
            "weather": weather,
        }
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
        trip = load_trip(trip_id)
        checkpoints = trip_checkpoints(trip, distance_mi, departure.timestamp())
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
        trip = load_trip(params.validated_data["trip_id"])
        departure = params.validated_data["departure"]
        recommendation = recommend(route_risks(trip, departure.timestamp()))
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

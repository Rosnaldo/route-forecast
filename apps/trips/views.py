import csv

from django.conf import settings
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .counties import counties_along
from .routing import compute_route
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
    offset_s = serializers.IntegerField()
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
    now = serializers.IntegerField()
    start = serializers.IntegerField()
    hours = serializers.SerializerMethodField()
    weight_lb = serializers.FloatField()
    points = GridPointSerializer(many=True)
    cells = WeatherCellSerializer(many=True)

    def get_hours(self, grid) -> int:
        return FORECAST_HOURS


class RouteResponseSerializer(serializers.Serializer):
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()
    points = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))
    counties = CountySerializer(many=True)
    weather = WeatherGridSerializer()


class RouteView(APIView):
    """Driving route between departure and arrival: [lat, lon] points, counties crossed,
    and the hourly weather risk for the next FORECAST_HOURS on a grid over those counties,
    for a truck carrying `weight_lb` of cargo."""

    serializer_class = RouteRequestSerializer

    def post(self, request: Request, version: str) -> Response:
        params = RouteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        departure, arrival, weight_lb = (
            params.validated_data[key] for key in ("departure", "arrival", "weight_lb")
        )
        route = compute_route(departure, arrival)
        counties = counties_along(route.points)
        weather = weather_grid(route, counties, weight_lb)
        data = {**vars(route), "counties": counties, "weather": weather}
        return Response(RouteResponseSerializer(data).data)


class ExampleRoutesView(APIView):
    """Sample trips from example_routes.csv, for trying the route endpoint."""

    def get(self, request: Request, version: str) -> Response:
        with EXAMPLE_ROUTES_FILE.open(newline="") as file:
            rows = [
                {**row, "id": int(row["id"]), "distance_km": int(row["distance_km"])}
                for row in csv.DictReader(file)
            ]
        return Response(rows)

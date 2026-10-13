"""Response serializers for the trip endpoints: domain structures to JSON."""

from rest_framework import serializers

from ..business.geometry import outline
from ..business.route import display_points
from ..business.weather import FORECAST_HOURS


class CountySerializer(serializers.Serializer):
    fips = serializers.CharField()
    name = serializers.CharField()
    state = serializers.CharField()
    geometry = serializers.SerializerMethodField()

    def get_geometry(self, county) -> dict | None:
        return outline(county.geometry)


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
    geometry = serializers.SerializerMethodField()

    def get_geometry(self, cell) -> dict:
        return outline(cell.piece)


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
        return [{"lat": center.lat, "lon": center.lon} for center in grid.points]


class RouteCellSerializer(serializers.Serializer):
    """A cell the route covers: `cell` indexes WeatherGridSerializer.cells."""

    cell = serializers.IntegerField()
    offset_s = serializers.IntegerField()  # when the truck passes nearest, after departure


class DisplayPointsField(serializers.ListField):
    """A route's points, simplified for drawing (business.route.display_points)."""

    def get_attribute(self, route):
        return display_points(route)


class RouteSerializer(serializers.Serializer):
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()  # Google's car drive time; ETAs: timing.py
    description = serializers.CharField()
    source = serializers.CharField()  # "google", or a fallback: "avoid_highways" / "detour"
    points = DisplayPointsField(  # [lat, lon], simplified for drawing
        child=serializers.ListField(child=serializers.FloatField())
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


class StreamedPointSerializer(GridPointSerializer):
    index = serializers.IntegerField()  # into the grid event's points


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

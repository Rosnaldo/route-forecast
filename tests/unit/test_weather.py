import io
import json
import urllib.error
import urllib.parse
from unittest import mock

import pytest
from shapely import box

from apps.core.exceptions import UpstreamError
from apps.trips.counties import County
from apps.trips.risk import RiskLevel
from apps.trips.routing import Route
from apps.trips.weather import FORECAST_HOURS, Forecast, _grid_pieces, _series, weather_grid

START = 1_800_000_000 - 1_800_000_000 % 3600  # on the hour
NOW = START + 600  # ten past
HOURS = [START + h * 3600 for h in range(FORECAST_HOURS + 2)]

# A square 0.4 x 0.4 degree "county": a 2 x 2 block of 0.2-degree grid cells.
SQUARE = County("99001", "Square", "ZZ", box(-105.0, 39.0, -104.6, 39.4))
# West to east across the middle of the square, 4 hours end to end.
ROUTE = Route(distance_m=35_000, duration_s=4 * 3600, points=[(39.2, -105.0), (39.2, -104.6)])


def hourly(wind=0.0, rain=0.0, snow=0.0):
    n = len(HOURS)
    return {
        "time": HOURS,
        "wind_speed_10m": [wind] * n,
        "rain": [rain] * n,
        "snowfall": [snow] * n,
    }


def fake_open_meteo(**values):
    """Answer every location in the request with the same hourly values."""

    def urlopen(url, timeout):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        count = len(query["latitude"][0].split(","))
        locations = [{"hourly": hourly(**values)} for _ in range(count)]
        return io.BytesIO(json.dumps(locations if count > 1 else locations[0]).encode())

    return mock.patch("apps.trips.weather.urllib.request.urlopen", side_effect=urlopen)


def test_forecast_level_is_worst_condition():
    forecast = Forecast(wind_mph=40, rain_in_hr=0, snow_in_hr=0.6)
    assert forecast.level() == RiskLevel.HIGH
    assert forecast.level(45_000) == RiskLevel.SEVERE  # 35-44 mph over 40,000 lb
    assert Forecast(wind_mph=0, rain_in_hr=0, snow_in_hr=0).level() == RiskLevel.LOW


def test_grid_pieces_split_on_county_borders():
    pieces = _grid_pieces([SQUARE], 0.2)
    assert sorted(center for center, _, _ in pieces) == [
        (39.1, -104.9),
        (39.1, -104.7),
        (39.3, -104.9),
        (39.3, -104.7),
    ]
    assert sum(piece.area for _, _, piece in pieces) == pytest.approx(SQUARE.geometry.area)

    # Shifted half a cell, the county touches 3 x 3 cells and edge cells are clipped.
    shifted = County("99002", "Shifted", "ZZ", box(-104.9, 39.1, -104.5, 39.5))
    assert len(_grid_pieces([shifted], 0.2)) == 9


def test_series_shifts_precipitation_to_the_hour_it_fell():
    data = hourly()
    data["wind_speed_10m"] = list(range(len(HOURS)))
    data["rain"] = [h / 100 for h in range(len(HOURS))]
    series = _series(data, START)
    assert len(series) == FORECAST_HOURS + 1
    assert series[2].wind_mph == 2  # value at the start of the hour
    assert series[2].rain_in_hr == 0.03  # total over the hour, stamped at its end
    assert series[-1] is not None


def test_series_from_older_cached_data():
    data = hourly(wind=10)
    # Fetched an hour earlier: hour 0 is the second entry and the last hour is missing.
    series = _series(data | {"time": [t - 3600 for t in HOURS]}, START)
    assert series[0].wind_mph == 10
    assert series[-2] is not None
    assert series[-1] is None
    assert _series({"time": []}, START) == [None] * (FORECAST_HOURS + 1)


def test_weather_grid_classifies_each_hour_for_the_weight():
    with fake_open_meteo(wind=40) as urlopen:
        grid = weather_grid(ROUTE, [SQUARE], 45_000, now=NOW)
    assert urlopen.call_count == 1
    assert (grid.now, grid.start, grid.weight_lb) == (NOW, START, 45_000)
    assert len(grid.points) == len(grid.cells) == 4
    assert {cell.county for cell in grid.cells} == {SQUARE}
    point = grid.points[0]
    # 40 mph wind is High, Severe over 40,000 lb.
    assert point.levels == [RiskLevel.SEVERE] * (FORECAST_HOURS + 1)
    assert point.wind_mph[0] == 40
    # West cells are passed after a quarter of the trip, east ones after three quarters.
    assert sorted({p.offset_s for p in grid.points}) == [3600, 3 * 3600]
    assert grid.cells[0].outline()["type"] == "Polygon"


def test_weather_grid_light_load():
    with fake_open_meteo(wind=40):
        grid = weather_grid(ROUTE, [SQUARE], 20_000, now=NOW)
    assert set(grid.points[0].levels) == {RiskLevel.HIGH}


def test_weather_grid_caches_forecasts():
    with fake_open_meteo() as urlopen:
        weather_grid(ROUTE, [SQUARE], now=NOW)
        weather_grid(ROUTE, [SQUARE], now=NOW)
    assert urlopen.call_count == 1


def test_weather_grid_coarsens_long_routes():
    with mock.patch("apps.trips.weather.MAX_CELLS", 1), fake_open_meteo():
        grid = weather_grid(ROUTE, [SQUARE], now=NOW)
    assert len(grid.points) == 1
    assert {cell.point for cell in grid.cells} == {0}


def test_weather_grid_without_counties():
    assert weather_grid(ROUTE, [], now=NOW).points == []
    assert weather_grid(ROUTE, [County("99003", "No outline", "ZZ")], now=NOW).cells == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("", 429, "Too Many", {}, None), "rate limit"),
        (urllib.error.HTTPError("", 500, "Oops", {}, None), "request failed"),
        (urllib.error.URLError("down"), "unreachable"),
    ],
)
def test_weather_api_errors(error, message):
    with (
        mock.patch("apps.trips.weather.urllib.request.urlopen", side_effect=error),
        pytest.raises(UpstreamError, match=message),
    ):
        weather_grid(ROUTE, [SQUARE], now=NOW)

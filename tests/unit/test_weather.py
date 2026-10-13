import io
import json
import urllib.error
import urllib.parse
from unittest import mock

import pytest
from shapely import box

from apps.trips import weather as weather_module
from apps.trips.counties import County
from apps.trips.risk import RiskLevel
from apps.trips.routing import Point, Route
from apps.trips.timing import TravelTimes
from apps.trips.weather import (
    FORECAST_HOURS,
    FailedBatch,
    Forecast,
    _grid_pieces,
    _series,
    forecast_events,
    weather_grid,
)

START = 1_800_000_000 - 1_800_000_000 % 3600  # on the hour
NOW = START + 600  # ten past
HOURS = [START + h * 3600 for h in range(FORECAST_HOURS + 2)]

# A square 0.4 x 0.4 degree "county": a 2 x 2 block of 0.2-degree grid cells.
SQUARE = County("99001", "Square", "ZZ", box(-105.0, 39.0, -104.6, 39.4))
# West to east across the middle of the square, 4 hours end to end.
ROUTE = Route(
    distance_m=35_000, duration_s=4 * 3600, points=[Point(39.2, -105.0), Point(39.2, -104.6)]
)


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


def test_weather_grid_is_the_layout_without_forecasts():
    with fake_open_meteo() as urlopen:
        grid = weather_grid([(ROUTE, [SQUARE])], 45_000, now=NOW)
    assert urlopen.call_count == 0  # forecasts come from forecast_events
    assert (grid.now, grid.start, grid.weight_lb) == (NOW, START, 45_000)
    assert len(grid.points) == len(grid.cells) == 4
    assert {cell.county for cell in grid.cells} == {SQUARE}
    # West cells are passed a quarter of the way along, east ones three quarters, at the
    # fallback speed (no steps; Google's 4 h duration is not used): 34.5 km at 100 km/h.
    (route_cells,) = grid.route_cells
    assert sorted(rc.cell for rc in route_cells) == [0, 1, 2, 3]
    length, times = ROUTE.length_m(), TravelTimes(ROUTE)
    quarter, three_quarters = times.elapsed_s(length / 4), times.elapsed_s(length * 3 / 4)
    assert sorted({rc.offset_s for rc in route_cells}) == [quarter, three_quarters]
    # Points come in the order the truck reaches them: the west (departure) side first.
    assert [lon for _, lon in grid.points] == [-104.9, -104.9, -104.7, -104.7]
    assert grid.cells[0].outline()["type"] == "Polygon"


def events(centers=None, weight_lb=20_000, **values):
    centers = centers or [(39.1, -104.9), (39.3, -104.9), (39.1, -104.7), (39.3, -104.7)]
    with fake_open_meteo(**values) as urlopen:
        result = list(forecast_events(centers, START, weight_lb))
    return result, urlopen


def test_forecast_events_classify_each_hour_for_the_weight():
    (batch,), _ = events(weight_lb=45_000, wind=40)
    assert [i for i, _ in batch.points] == [0, 1, 2, 3]
    _, point = batch.points[0]
    # 40 mph wind is High, Severe over 40,000 lb.
    assert point.levels == [RiskLevel.SEVERE] * (FORECAST_HOURS + 1)
    assert point.wind_mph[0] == 40
    (light,), _ = events(weight_lb=20_000, wind=40)
    assert set(light.points[0][1].levels) == {RiskLevel.HIGH}


def test_forecast_events_come_in_batches_of_80_cached_first():
    centers = [(30 + i * 0.2, -100.0) for i in range(200)]
    with fake_open_meteo():
        list(forecast_events(centers[:50], START, 0))  # caches the first 50
    batches, urlopen = events(centers)
    # Cached points first, in order (50 = one batch); then the other 150 in 80 + 70,
    # one request each.
    assert [len(b.points) for b in batches] == [50, 80, 70]
    assert [i for i, _ in batches[0].points] == list(range(50))
    assert urlopen.call_count == 2
    fetched = sorted(i for b in batches[1:] for i, _ in b.points)
    assert fetched == list(range(50, 200))


def test_forecast_events_cache_what_they_fetch():
    _, first = events()
    _, second = events()
    assert first.call_count == 1
    assert second.call_count == 0


def test_weather_grid_coarsens_long_routes():
    with mock.patch("apps.trips.weather.MAX_CELLS", 1), fake_open_meteo():
        grid = weather_grid([(ROUTE, [SQUARE])], now=NOW)
    assert len(grid.points) == 1
    assert {cell.point for cell in grid.cells} == {0}


def test_weather_grid_without_counties():
    assert weather_grid([], now=NOW).points == []
    grid = weather_grid([(ROUTE, [County("99003", "No outline", "ZZ")])], now=NOW)
    assert grid.cells == []
    assert grid.route_cells == [[]]


def test_routes_share_cells():
    # East to west over the same square: same cells, each once, reversed timing.
    back = Route(distance_m=35_000, duration_s=4 * 3600, points=ROUTE.points[::-1])
    grid = weather_grid([(ROUTE, [SQUARE]), (back, [SQUARE])], now=NOW)
    assert len(grid.cells) == len(grid.points) == 4
    there, back_again = (
        {grid.cells[rc.cell].point: rc.offset_s for rc in cells} for cells in grid.route_cells
    )
    assert there.keys() == back_again.keys()
    total = TravelTimes(ROUTE).elapsed_s(ROUTE.length_m())
    assert all(abs(there[p] + back_again[p] - total) <= 1 for p in there)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("", 429, "Too Many", {}, None), "rate limit"),
        (urllib.error.HTTPError("", 500, "Oops", {}, None), "request failed"),
        (urllib.error.URLError("down"), "unreachable"),
    ],
)
def test_weather_api_errors_fail_only_their_batch(error, message):
    centers = [(30 + i * 0.2, -100.0) for i in range(100)]  # two batches: 80 + 20
    calls = []

    def urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise error  # the first request fails, the second works
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        count = len(query["latitude"][0].split(","))
        return io.BytesIO(json.dumps([{"hourly": hourly()}] * count).encode())

    with mock.patch("apps.trips.weather.urllib.request.urlopen", side_effect=urlopen):
        result = list(forecast_events(centers, START, 0))
    failed = [e for e in result if isinstance(e, FailedBatch)]
    loaded = [e for e in result if not isinstance(e, FailedBatch)]
    assert len(failed) == len(loaded) == 1
    assert message in failed[0].detail
    assert sorted(failed[0].indices + [i for i, _ in loaded[0].points]) == list(range(100))


def test_grid_step_jumps_to_a_size_that_fits():
    # A 4 x 4 degree county: 400 cells at 0.2 degrees, more than MAX_CELLS (300).
    big = County("99004", "Big", "ZZ", box(-110.0, 38.0, -106.0, 42.0))
    with mock.patch("apps.trips.weather._cell_count", wraps=weather_module._cell_count) as count:
        step = weather_module._grid_step([[big]])
    assert weather_module._cell_count([[big]], step) <= weather_module.MAX_CELLS
    assert step > weather_module.GRID_STEP
    assert count.call_count <= 3  # one jump instead of growing x1.5 pass after pass


def test_grid_pieces_cover_each_county_exactly():
    odd = County("99005", "Odd", "ZZ", box(-104.93, 39.07, -104.31, 39.88))
    pieces = _grid_pieces([odd], 0.2)
    assert sum(piece.area for _, _, piece in pieces) == pytest.approx(odd.geometry.area)
    assert len({center for center, _, _ in pieces}) == len(pieces)  # one piece per cell

from unittest import mock

import pytest

from apps.core.exceptions import NotFoundError
from apps.trips.checkpoints import (
    METERS_PER_MILE,
    Trip,
    _along,
    load_trip,
    save_trip,
    trip_checkpoints,
)
from apps.trips.risk import RiskLevel
from apps.trips.routing import Point, Route, haversine_m
from apps.trips.weather import FORECAST_HOURS, Forecast

START = 1_800_000_000 - 1_800_000_000 % 3600  # on the hour
NOW = START + 600
# One degree of longitude along the equator (~69.1 mi, 111.2 km). Google's duration is
# ignored and there are no steps: the fallback 100 km/h applies (67 min to the end).
EAST = Route(111_195, 7200, [Point(0.0, 0.0), Point(0.0, 0.5), Point(0.0, 1.0)])
LENGTH_M = haversine_m(0, 0, 0, 1)


def test_along_places_a_mark_every_gap_then_the_arrival():
    marks = _along(EAST, 25 * METERS_PER_MILE)
    assert [round(d / METERS_PER_MILE, 1) for _, _, d, _ in marks] == [25.0, 50.0, 69.1]
    assert [arrival for *_, arrival in marks] == [False, False, True]
    lat, lon, _, _ = marks[0]
    assert lat == 0
    assert lon == pytest.approx(25 * METERS_PER_MILE / LENGTH_M)
    assert marks[-1][:2] == (0.0, 1.0)


def test_along_mark_on_the_arrival_is_not_doubled():
    marks = _along(EAST, LENGTH_M / 2)
    assert [arrival for *_, arrival in marks] == [False, True]
    assert marks[-1][2] == pytest.approx(LENGTH_M)


def test_along_shorter_than_the_gap_is_just_the_arrival():
    assert [arrival for *_, arrival in _along(EAST, 100 * METERS_PER_MILE)] == [True]
    assert _along(Route(0, 0, []), 1000) == []


def fake_forecasts(wind_by_hour):
    """Every grid center gets the same hourly series: wind from `wind_by_hour`."""
    hours = [Forecast(wind, 0, 0) for wind in wind_by_hour] + [None] * (
        FORECAST_HOURS + 1 - len(wind_by_hour)
    )
    return mock.patch(
        "apps.trips.checkpoints.hourly_forecasts",
        side_effect=lambda centers, start: dict.fromkeys(centers, hours),
    )


def test_checkpoints_have_travel_time_and_the_forecast_on_arrival():
    trip = Trip([EAST], weight_lb=20_000, step=0.2)
    departure = NOW + 3 * 3600  # three hours from now
    with fake_forecasts(list(range(FORECAST_HOURS + 1))) as forecasts:
        (route,) = trip_checkpoints(trip, 25, departure, now=NOW)
    assert forecasts.call_args.args[1] == START
    # At 100 km/h: 25 mi (40.2 km) after 24 min, 50 mi after 48 min, arrival after 67 min.
    assert [round(c.elapsed_s / 60) for c in route] == [24, 48, 67]
    assert [c.eta - departure for c in route] == [c.elapsed_s for c in route]
    # Wind equals the hour index: the forecast is for the hour each checkpoint is reached.
    assert [c.forecast.wind_mph for c in route] == [(c.eta - START) // 3600 for c in route]
    assert route[-1].is_arrival


def test_checkpoint_level_uses_the_load_weight():
    with fake_forecasts([40] * (FORECAST_HOURS + 1)):
        light = trip_checkpoints(Trip([EAST], 20_000, 0.2), 50, NOW, now=NOW)[0]
        heavy = trip_checkpoints(Trip([EAST], 45_000, 0.2), 50, NOW, now=NOW)[0]
    assert {c.level for c in light} == {RiskLevel.HIGH}
    assert {c.level for c in heavy} == {RiskLevel.SEVERE}  # 35-44 mph over 40,000 lb


def test_checkpoints_beyond_the_window_have_no_forecast():
    departure = NOW + FORECAST_HOURS * 3600 - 3600  # the last hour of the window
    with fake_forecasts([10] * (FORECAST_HOURS + 1)):
        (route,) = trip_checkpoints(Trip([EAST], 20_000, 0.2), 25, departure, now=NOW)
    assert route[0].forecast is not None  # 24 min in: still inside
    assert route[-1].forecast is None and route[-1].level is None  # 67 min in: past it


def test_trips_are_saved_and_loaded():
    trip = Trip([EAST], 20_000, 0.2)
    assert load_trip(save_trip(trip)) == trip
    with pytest.raises(NotFoundError):
        load_trip("missing")


def test_checkpoints_count_the_breaks_before_them():
    # ~1,000 km north at 100 km/h: 10 h of driving, a break after 8 h.
    long_route = Route(0, 0, [Point(0.0, 0.0), Point(8.993, 0.0)])
    with fake_forecasts([0] * (FORECAST_HOURS + 1)):
        (route,) = trip_checkpoints(Trip([long_route], 20_000, 0.2), 100, NOW, now=NOW)
    # Checkpoints every 100 mi (161 km): 1.6 h of driving apart; the 5th (805 km) is
    # 8.05 h in, so after the break.
    assert [c.breaks for c in route] == [0, 0, 0, 0, 1, 1, 1]
    assert route[3].elapsed_s == pytest.approx(4 * 160.934 / 100 * 3600, abs=5)
    assert route[4].elapsed_s == pytest.approx(5 * 160.934 / 100 * 3600 + 1800, abs=5)

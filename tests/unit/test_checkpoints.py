from contextlib import contextmanager
from unittest import mock

import pytest

from apps.core.exceptions import NotFoundError
from apps.trips.business.route import haversine_m
from apps.trips.business.trip import (
    MAX_SEGMENT_M,
    METERS_PER_MILE,
    _along,
    route_risks,
    trip_checkpoints,
)
from apps.trips.business.weather import FORECAST_HOURS
from apps.trips.domain.risk import RiskLevel
from apps.trips.domain.route import Point, Route
from apps.trips.domain.trip import MILES_KEYS, Trip
from apps.trips.domain.weather import Forecast
from apps.trips.services.trip_store import load_trip, save_trip

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


@contextmanager
def fake_forecasts(wind_by_hour):
    """A ForecastSource giving every grid center the same hourly series: wind from
    `wind_by_hour`."""
    hours = [Forecast(wind, 0, 0) for wind in wind_by_hour] + [None] * (
        FORECAST_HOURS + 1 - len(wind_by_hour)
    )
    yield mock.Mock(side_effect=lambda centers, start: dict.fromkeys(centers, hours))


def test_checkpoints_have_travel_time_and_the_forecast_on_arrival():
    trip = Trip([EAST], weight_lb=20_000, step=0.2)
    departure = NOW + 3 * 3600  # three hours from now
    with fake_forecasts(list(range(FORECAST_HOURS + 1))) as forecasts:
        ((route, _),) = trip_checkpoints(trip, 25, departure, forecasts, now=NOW)
    assert forecasts.call_args.args[1] == START
    # At 100 km/h: 25 mi (40.2 km) after 24 min, 50 mi after 48 min, arrival after 67 min.
    assert [round(c.elapsed_s / 60) for c in route] == [24, 48, 67]
    assert [c.eta - departure for c in route] == [c.elapsed_s for c in route]
    # Wind equals the hour index: the forecast is for the hour each checkpoint is reached.
    assert [c.forecast.wind_mph for c in route] == [(c.eta - START) // 3600 for c in route]
    assert route[-1].is_arrival


def test_checkpoint_level_uses_the_load_weight():
    with fake_forecasts([40] * (FORECAST_HOURS + 1)) as forecasts:
        light = trip_checkpoints(Trip([EAST], 20_000, 0.2), 50, NOW, forecasts, now=NOW)[
            0
        ].checkpoints
        heavy = trip_checkpoints(Trip([EAST], 45_000, 0.2), 50, NOW, forecasts, now=NOW)[
            0
        ].checkpoints
    assert {c.level for c in light} == {RiskLevel.HIGH}
    assert {c.level for c in heavy} == {RiskLevel.SEVERE}  # 35-44 mph over 40,000 lb


def test_checkpoints_beyond_the_window_have_no_forecast():
    departure = NOW + FORECAST_HOURS * 3600 - 3600  # the last hour of the window
    with fake_forecasts([10] * (FORECAST_HOURS + 1)) as forecasts:
        ((route, _),) = trip_checkpoints(
            Trip([EAST], 20_000, 0.2), 25, departure, forecasts, now=NOW
        )
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
    with fake_forecasts([0] * (FORECAST_HOURS + 1)) as forecasts:
        ((route, _),) = trip_checkpoints(
            Trip([long_route], 20_000, 0.2), 100, NOW, forecasts, now=NOW
        )
    # Checkpoints every 100 mi (161 km): 1.6 h of driving apart; the 5th (805 km) is
    # 8.05 h in, so after the break.
    assert [c.breaks for c in route] == [0, 0, 0, 0, 1, 1, 1]
    assert route[3].elapsed_s == pytest.approx(4 * 160.934 / 100 * 3600, abs=5)
    assert route[4].elapsed_s == pytest.approx(5 * 160.934 / 100 * 3600 + 1800, abs=5)


LENGTH_MI = LENGTH_M / METERS_PER_MILE  # 69.1
PIECE_MI = MAX_SEGMENT_M / METERS_PER_MILE  # where a level changes, one piece can go either way


def test_miles_by_level_split_where_the_forecast_changes():
    # Leave half an hour before hour 1: at the fallback 100 km/h, the first 50 km are
    # driven in hour 0 (calm), the rest in hour 1 (40 mph wind: High).
    departure = START + 3600 - 1800
    with fake_forecasts([0] + [40] * FORECAST_HOURS) as forecasts:
        ((_, miles),) = trip_checkpoints(
            Trip([EAST], 20_000, 0.2), 25, departure, forecasts, now=NOW
        )
    assert miles.keys() == set(MILES_KEYS)
    assert miles["low"] == pytest.approx(50 / 1.609344, abs=PIECE_MI)  # 31.1 mi
    assert miles["high"] == pytest.approx(LENGTH_MI - 50 / 1.609344, abs=PIECE_MI)  # 38.0 mi
    assert miles["moderate"] == miles["severe"] == miles["no_travel"] == 0
    assert sum(miles.values()) == pytest.approx(LENGTH_MI, abs=0.1)


def test_miles_by_level_use_the_load_weight_and_the_window():
    with fake_forecasts([40] * (FORECAST_HOURS + 1)) as forecasts:
        ((_, heavy),) = trip_checkpoints(Trip([EAST], 45_000, 0.2), 25, NOW, forecasts, now=NOW)
    assert heavy["severe"] == pytest.approx(LENGTH_MI, abs=0.1)  # 35-44 mph over 40,000 lb

    # Leaving 20 min before the window ends: the rest of the route has no forecast.
    departure = NOW + FORECAST_HOURS * 3600 - 1200
    with fake_forecasts([0] * (FORECAST_HOURS + 1)) as forecasts:
        ((_, late),) = trip_checkpoints(
            Trip([EAST], 20_000, 0.2), 25, departure, forecasts, now=NOW
        )
    assert late["low"] == pytest.approx(100 / 3 / 1.609344, abs=PIECE_MI)  # 33.3 km in 20 min
    assert late["no_forecast"] == pytest.approx(LENGTH_MI - late["low"], abs=0.1)


def test_route_risks_average_level_and_travel_time():
    # First half calm (Low = 0), second half 40 mph (High = 2): the average is 1.
    departure = START + 3600 - 2000  # the hour changes 33.3 min (55.6 km, half-way) in
    with fake_forecasts([0] + [40] * FORECAST_HOURS) as forecasts:
        (risk,) = route_risks(Trip([EAST], 20_000, 0.2), departure, forecasts, now=NOW)
    assert risk.average_level == pytest.approx(1, abs=0.02)
    assert risk.travel_s == round(LENGTH_M / (100_000 / 3600))  # fallback 100 km/h
    assert risk.miles_by_level["low"] + risk.miles_by_level["high"] == pytest.approx(
        LENGTH_MI, abs=0.1
    )

    # Nothing within the window: no average.
    with fake_forecasts([]) as forecasts:
        (risk,) = route_risks(Trip([EAST], 20_000, 0.2), NOW, forecasts, now=NOW)
    assert risk.average_level is None
    assert risk.miles_by_level["no_forecast"] == pytest.approx(LENGTH_MI, abs=0.1)

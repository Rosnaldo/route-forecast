import pytest

from apps.trips.routing import Point, Route, Step
from apps.trips.timing import BREAK_AFTER_S, BREAK_S, TravelTimes, elapsed_with_breaks

# Straight north along a meridian: ~111.2 km per degree.
POINTS = [Point(0.0, 0.0), Point(1.0, 0.0)]
LENGTH = Route(0, 0, POINTS).length_m()


def test_without_steps_the_whole_route_runs_at_the_fallback_speed():
    times = TravelTimes(Route(0, 0, POINTS))
    assert times.driving_s(100_000) == pytest.approx(3600)  # 100 km at 100 km/h
    assert times.driving_s(0) == 0
    assert times.elapsed_s(LENGTH) == round(LENGTH / (100_000 / 3600))


def test_each_step_runs_at_googles_speed():
    # First 20% of the route at Google's 30 km/h, the rest at Google's 130 km/h.
    steps = (Step(20_000, 2400), Step(80_000, 2215))  # Google's step distances sum to 100 km
    times = TravelTimes(Route(0, 0, POINTS, steps=steps))
    city_end = LENGTH * 0.2  # steps are scaled onto the measured length
    assert times.driving_s(city_end) == pytest.approx(city_end / (30_000 / 3600))
    # The highway runs at Google's 130 km/h: no cap (100 km/h is only a fallback).
    highway = LENGTH * 0.8
    assert times.driving_s(LENGTH) == pytest.approx(
        city_end / (30_000 / 3600) + highway / (80_000 / 2215), rel=1e-6
    )
    # Halfway through the city: half its time.
    assert times.driving_s(city_end / 2) == pytest.approx(times.driving_s(city_end) / 2)


def test_step_without_duration_runs_at_the_fallback_speed():
    times = TravelTimes(Route(0, 0, POINTS, steps=(Step(100_000, 0),)))
    assert times.driving_s(LENGTH) == pytest.approx(LENGTH / (100_000 / 3600))


@pytest.mark.parametrize(
    ("driving_h", "breaks"),
    [(0, 0), (7.5, 0), (8, 0), (8.01, 1), (16, 1), (16.5, 2), (25, 3)],
)
def test_a_break_after_every_eight_hours_of_driving(driving_h, breaks):
    driving = driving_h * 3600
    assert BREAK_AFTER_S == 8 * 3600 and BREAK_S == 30 * 60
    assert elapsed_with_breaks(driving) == round(driving) + breaks * BREAK_S


def test_breaks_add_to_travel_times_along_a_long_route():
    # 1,000 km at 100 km/h: 10 h driving, one break -> 10 h 30 min.
    route = Route(0, 0, [Point(0.0, 0.0), Point(8.993, 0.0)])  # ~1,000 km north
    times = TravelTimes(route)
    assert times.elapsed_s(route.length_m()) == pytest.approx(10.5 * 3600, abs=60)
    assert times.elapsed_s(route.length_m() * 0.7) == pytest.approx(7 * 3600, abs=60)

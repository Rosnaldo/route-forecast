import pytest

from apps.trips.risk import Condition, RiskLevel, classify, overall

LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = RiskLevel


@pytest.mark.parametrize(
    ("value", "level"),
    [
        (0, LOW),
        (24.9, LOW),
        (25, MODERATE),
        (34.9, MODERATE),
        (35, HIGH),
        (44.9, HIGH),
        (45, SEVERE),
        (54.9, SEVERE),
        (55, NO_TRAVEL),  # >= 55 mph
        (80, NO_TRAVEL),
    ],
)
def test_wind_mph(value, level):
    assert classify(Condition.WIND, value) is level


@pytest.mark.parametrize(
    ("value", "level"),
    [
        (0, LOW),
        (0.09, LOW),
        (0.10, MODERATE),
        (0.25, HIGH),  # shared edge goes to the higher range
        (0.49, HIGH),
        (0.50, SEVERE),
        (1.00, SEVERE),  # > 1.00 for No Travel
        (1.01, NO_TRAVEL),
    ],
)
def test_rain_in_per_hour(value, level):
    assert classify(Condition.RAIN, value) is level


@pytest.mark.parametrize(
    ("value", "level"),
    [
        (0, LOW),
        (0.4, LOW),
        (0.5, MODERATE),
        (1.0, HIGH),
        (2.0, SEVERE),
        (3.0, SEVERE),  # > 3.0 for No Travel
        (3.1, NO_TRAVEL),
    ],
)
def test_snow_in_per_hour(value, level):
    assert classify(Condition.SNOW, value) is level


def test_overall_is_the_worst_condition():
    assert overall({Condition.WIND: 30, Condition.SNOW: 1.5, Condition.RAIN: 0}) is HIGH
    assert overall({Condition.WIND: 10, Condition.RAIN: 0.05}) is LOW
    assert overall({}) is LOW


def test_levels_are_ordered_and_labelled():
    assert LOW < MODERATE < HIGH < SEVERE < NO_TRAVEL
    assert NO_TRAVEL.label == "No Travel"

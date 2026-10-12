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


@pytest.mark.parametrize(
    ("mph", "weight_lb", "level"),
    [
        # >= 55 mph: No Travel for any load
        (55, 1_000, NO_TRAVEL),
        (70, 100_000, NO_TRAVEL),
        # 45-54 mph: No Travel over 30,000 lb, else the table's Severe
        (45, 30_000, SEVERE),  # needs more than 30,000
        (45, 30_001, NO_TRAVEL),
        (54.9, 35_000, NO_TRAVEL),
        (54.9, 10_000, SEVERE),
        # 35-44 mph: Severe over 40,000 lb, else the table's High
        (35, 40_000, HIGH),  # needs more than 40,000
        (35, 40_001, SEVERE),
        (44.9, 100_000, SEVERE),
        (40, 35_000, HIGH),
        # below 35 mph weight does not matter
        (34.9, 100_000, MODERATE),
        (10, 100_000, LOW),
    ],
)
def test_wind_with_load_weight(mph, weight_lb, level):
    assert classify(Condition.WIND, mph, weight_lb) is level


def test_load_weight_does_not_change_rain_or_snow():
    assert classify(Condition.RAIN, 0.30, 100_000) is HIGH
    assert classify(Condition.SNOW, 0.6, 100_000) is MODERATE


def test_overall_with_load_weight():
    values = {Condition.WIND: 40, Condition.SNOW: 0.6}
    assert overall(values) is HIGH
    assert overall(values, 45_000) is SEVERE

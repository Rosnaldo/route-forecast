import pytest

from apps.trips.business.risk import classify, overall, risk_label
from apps.trips.domain.risk import Condition, RiskLevel

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
    assert risk_label(NO_TRAVEL) == "No Travel"


@pytest.mark.parametrize("weight_lb", [0, 1_000, 30_000, 40_001, 100_000])
@pytest.mark.parametrize("mph", [55, 70])
def test_wind_55_mph_or_more_is_no_travel_for_any_load(mph, weight_lb):
    assert classify(Condition.WIND, mph, weight_lb) is NO_TRAVEL


@pytest.mark.parametrize(
    ("mph", "weight_lb", "level"),
    [
        (45, 30_001, NO_TRAVEL),
        (50, 45_000, NO_TRAVEL),
        (54.9, 35_000, NO_TRAVEL),
        (45, 30_000, SEVERE),  # needs more than 30,000 lb: the table's Severe
        (54.9, 10_000, SEVERE),
        (44.9, 30_001, HIGH),  # below 45 mph this rule does not apply
    ],
)
def test_wind_45_to_54_mph_over_30000_lb_is_no_travel(mph, weight_lb, level):
    assert classify(Condition.WIND, mph, weight_lb) is level


@pytest.mark.parametrize(
    ("mph", "weight_lb", "level"),
    [
        (35, 40_001, SEVERE),
        (40, 45_000, SEVERE),
        (44.9, 100_000, SEVERE),
        (35, 40_000, HIGH),  # needs more than 40,000 lb: the table's High
        (40, 35_000, HIGH),
        (34.9, 100_000, MODERATE),  # below 35 mph weight does not matter
        (10, 100_000, LOW),
    ],
)
def test_wind_35_to_44_mph_over_40000_lb_is_severe(mph, weight_lb, level):
    assert classify(Condition.WIND, mph, weight_lb) is level


def test_load_weight_does_not_change_rain_or_snow():
    assert classify(Condition.RAIN, 0.30, 100_000) is HIGH
    assert classify(Condition.SNOW, 0.6, 100_000) is MODERATE


def test_overall_with_load_weight():
    values = {Condition.WIND: 40, Condition.SNOW: 0.6}
    assert overall(values) is HIGH
    assert overall(values, 45_000) is SEVERE


@pytest.mark.parametrize(
    ("rain", "level"),
    [(0, LOW), (0.10, MODERATE), (0.30, HIGH), (0.75, SEVERE), (1.5, NO_TRAVEL)],
)
def test_overall_rain(rain, level):
    assert overall({Condition.WIND: 0, Condition.RAIN: rain, Condition.SNOW: 0}) is level


@pytest.mark.parametrize(
    ("snow", "level"),
    [(0.2, LOW), (0.5, MODERATE), (1.5, HIGH), (2.5, SEVERE), (4.0, NO_TRAVEL)],
)
def test_overall_snow(snow, level):
    assert overall({Condition.WIND: 0, Condition.RAIN: 0, Condition.SNOW: snow}) is level


def test_overall_rain_and_snow_take_the_worse():
    assert overall({Condition.RAIN: 0.30, Condition.SNOW: 2.5}) is SEVERE  # snow decides
    assert overall({Condition.RAIN: 1.5, Condition.SNOW: 0.5}) is NO_TRAVEL  # rain decides


def test_overall_rain_and_snow_ignore_the_load():
    values = {Condition.WIND: 10, Condition.RAIN: 0.30, Condition.SNOW: 0.6}
    assert overall(values) is HIGH
    assert overall(values, 100_000) is HIGH

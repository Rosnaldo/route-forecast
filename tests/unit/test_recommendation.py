import pytest

from apps.trips.business.recommendation import recommend
from apps.trips.domain.trip import RouteRisk


def risk(severe=0.0, high=0.0, average=0.5, travel_min=300, no_travel=0.0, low=100.0):
    miles = {
        "low": low,
        "moderate": 0.0,
        "high": high,
        "severe": severe,
        "no_travel": no_travel,
        "no_forecast": 0.0,
    }
    return RouteRisk(miles, average, travel_min * 60)


def ranking(risks):
    result = recommend(risks)
    return [score.route for score in result.ranking], result.decided_by


@pytest.mark.parametrize(
    ("risks", "expected"),
    [
        # 1. fewest Severe miles beats everything after it
        (
            [risk(severe=5, travel_min=100), risk(severe=1, high=50, average=3)],
            ([1, 0], "severe_miles"),
        ),
        # 2. Severe tied: fewest High miles
        ([risk(severe=2, high=9), risk(severe=2, high=3, travel_min=900)], ([1, 0], "high_miles")),
        # 3. then the lowest average risk
        ([risk(average=1.2), risk(average=0.8, travel_min=900)], ([1, 0], "average_level")),
        # 4. then the shortest travel time
        ([risk(travel_min=320), risk(travel_min=310)], ([1, 0], "travel_s")),
    ],
)
def test_each_criterion_breaks_the_ties_of_the_ones_before(risks, expected):
    assert ranking(risks) == expected


def test_three_routes_are_fully_ranked():
    risks = [risk(severe=3), risk(severe=0, high=4), risk(severe=0, high=1)]
    assert ranking(risks) == ([2, 1, 0], "high_miles")


def test_no_travel_miles_count_as_severe():
    risks = [risk(severe=4), risk(severe=0, no_travel=10)]
    result = recommend(risks)
    assert [s.route for s in result.ranking] == [0, 1]
    assert result.ranking[1].severe_miles == 10


def test_rounding_noise_does_not_decide():
    # 0.04 mi and 0.004 levels apart: equal at the shown precision, so travel time decides.
    risks = [risk(severe=1.02, average=1.001, travel_min=400), risk(severe=1.0, average=1.0)]
    assert ranking(risks) == ([1, 0], "travel_s")


def test_no_forecast_average_ranks_last_and_full_ties_keep_googles_order():
    assert ranking([risk(average=None), risk(average=3.9)]) == ([1, 0], "average_level")
    assert ranking([risk(), risk()]) == ([0, 1], "tie")
    assert ranking([risk()]) == ([0], None)


# Each case below is three routes, built so the recommended one loses on every criterion
# after the one that should decide: only that criterion can have picked it.


def test_rule_1_fewest_severe_miles():
    risks = [
        risk(severe=8, high=0, average=0.5, travel_min=200),
        risk(severe=6, high=0, average=0.5, travel_min=200),
        risk(severe=2, high=40, average=3.0, travel_min=600),
    ]
    assert ranking(risks) == ([2, 1, 0], "severe_miles")


def test_rule_2_severe_tied_fewest_high_miles():
    risks = [
        risk(severe=3, high=12, average=0.5, travel_min=200),
        risk(severe=3, high=4, average=2.5, travel_min=600),
        risk(severe=3, high=7, average=0.5, travel_min=200),
    ]
    assert ranking(risks) == ([1, 2, 0], "high_miles")


def test_rule_3_no_severe_or_high_lowest_average():
    risks = [
        risk(average=1.4, travel_min=200),
        risk(average=0.9, travel_min=200),
        risk(average=0.3, travel_min=600),
    ]
    assert ranking(risks) == ([2, 1, 0], "average_level")


def test_rule_3_severe_and_high_tied_lowest_average():
    risks = [
        risk(severe=5, high=10, average=1.1, travel_min=600),
        risk(severe=5, high=10, average=2.2, travel_min=200),
        risk(severe=5, high=10, average=1.6, travel_min=200),
    ]
    assert ranking(risks) == ([0, 2, 1], "average_level")


def test_rule_4_everything_else_tied_shortest_travel_time():
    risks = [
        risk(average=0.7, travel_min=340),
        risk(average=0.7, travel_min=360),
        risk(average=0.7, travel_min=315),
    ]
    assert ranking(risks) == ([2, 0, 1], "travel_s")

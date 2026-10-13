"""
Which route to take: the routes ranked by these criteria, each one only breaking
ties left by the ones before it:

    1. Fewest Severe miles (No Travel miles count as Severe: they are worse)
    2. Fewest High miles
    3. Lowest average risk (mile-weighted level, 0-4; no forecast ranks last)
    4. Shortest travel time (breaks included)

Values are compared at the precision they are shown with (0.1 mi, 0.01 level,
1 min), so rounding noise does not decide.
"""

import math

from ..domain.recommendation import Recommendation, RouteScore
from ..domain.trip import RouteRisk

CRITERIA = ("severe_miles", "high_miles", "average_level", "travel_s")


def score_key(score: RouteScore) -> tuple:
    """The score's criteria in order, at the precision they are shown with."""
    average = math.inf if score.average_level is None else round(score.average_level, 2)
    return (
        round(score.severe_miles, 1),
        round(score.high_miles, 1),
        average,
        round(score.travel_s / 60),
    )


def recommend(risks: list[RouteRisk]) -> Recommendation:
    scores = [
        RouteScore(
            route=index,
            severe_miles=risk.miles_by_level["severe"] + risk.miles_by_level["no_travel"],
            high_miles=risk.miles_by_level["high"],
            average_level=risk.average_level,
            travel_s=risk.travel_s,
        )
        for index, risk in enumerate(risks)
    ]
    ranking = sorted(scores, key=lambda score: (score_key(score), score.route))
    if len(ranking) < 2:
        return Recommendation(ranking, None)
    best, runner_up = score_key(ranking[0]), score_key(ranking[1])
    decided_by = next(
        (name for name, a, b in zip(CRITERIA, best, runner_up, strict=True) if a != b), "tie"
    )
    return Recommendation(ranking, decided_by)

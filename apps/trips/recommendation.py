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
from typing import NamedTuple

from .checkpoints import RouteRisk

CRITERIA = ("severe_miles", "high_miles", "average_level", "travel_s")


class RouteScore(NamedTuple):
    route: int  # index in the trip's routes
    severe_miles: float  # Severe + No Travel
    high_miles: float
    average_level: float | None
    travel_s: int

    def key(self) -> tuple:
        average = math.inf if self.average_level is None else round(self.average_level, 2)
        return (
            round(self.severe_miles, 1),
            round(self.high_miles, 1),
            average,
            round(self.travel_s / 60),
        )


class Recommendation(NamedTuple):
    ranking: list[RouteScore]  # best first; ranking[0] is the recommended route
    # The criterion that put the recommended route ahead of the runner-up; None with a
    # single route, "tie" when all four are equal (the first route Google gave wins).
    decided_by: str | None


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
    ranking = sorted(scores, key=lambda score: (score.key(), score.route))
    if len(ranking) < 2:
        return Recommendation(ranking, None)
    best, runner_up = ranking[0].key(), ranking[1].key()
    decided_by = next(
        (name for name, a, b in zip(CRITERIA, best, runner_up, strict=True) if a != b), "tie"
    )
    return Recommendation(ranking, decided_by)

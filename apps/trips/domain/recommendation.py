"""Which route to take: each route's score, and the ranking (see business/recommendation.py)."""

from typing import NamedTuple


class RouteScore(NamedTuple):
    route: int  # index in the trip's routes
    severe_miles: float  # Severe + No Travel
    high_miles: float
    average_level: float | None
    travel_s: int


class Recommendation(NamedTuple):
    ranking: list[RouteScore]  # best first; ranking[0] is the recommended route
    # The criterion that put the recommended route ahead of the runner-up; None with a
    # single route, "tie" when all four are equal (the first route Google gave wins).
    decided_by: str | None

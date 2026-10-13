"""
Expected travel time along a route for a truck: how long after departure it
reaches a given distance along the route.

Speed varies along the route with Google's steps (each street or highway
section): a step's speed is Google's estimate for it (its distance over its
time), so city streets are slow and highways fast. FALLBACK_SPEED_KMH is used
only where Google gives no speed: a route without step data, or a step without
a time.

Breaks: the driver stops BREAK_S after every BREAK_AFTER_S of driving (the US
hours-of-service 30-minute break after 8 hours). A point reached after a break
includes it.
"""

import bisect
import itertools

from ..domain.route import Route, Step
from .route import length_m

FALLBACK_SPEED_KMH = 100
FALLBACK_SPEED_MPS = FALLBACK_SPEED_KMH * 1000 / 3600
BREAK_AFTER_S = 8 * 3600
BREAK_S = 30 * 60


class TravelTimes:
    """Travel times along one route, by distance from departure (meters along the
    route's points, as measured by route.length_m)."""

    def __init__(self, route: Route):
        route_m = length_m(route)
        step_m = sum(step.distance_m for step in route.steps)
        # Google's step distances are scaled onto our measured length, so the profile
        # covers exactly the route's points.
        scale = route_m / step_m if step_m and route_m else 0
        self._ends = []  # cumulative distance at the end of each section
        self._starts_s = [0.0]  # driving seconds at the start of each section
        self._speeds = []  # meters per second within each section
        if scale:
            sections = [
                (step.distance_m * scale, speed_mps(step) or FALLBACK_SPEED_MPS)
                for step in route.steps
                if step.distance_m
            ]
        else:
            sections = [(route_m, FALLBACK_SPEED_MPS)]
        for end, (distance, speed) in zip(
            itertools.accumulate(d for d, _ in sections), sections, strict=True
        ):
            self._ends.append(end)
            self._speeds.append(speed)
            self._starts_s.append(self._starts_s[-1] + distance / speed)

    def driving_s(self, distance_m: float) -> float:
        """Seconds of driving to cover `distance_m` from departure (no breaks)."""
        if not self._ends or distance_m <= 0:
            return 0.0
        i = min(bisect.bisect_left(self._ends, distance_m), len(self._ends) - 1)
        section_start = self._ends[i - 1] if i else 0.0
        return self._starts_s[i] + (distance_m - section_start) / self._speeds[i]

    def elapsed_s(self, distance_m: float) -> int:
        """Seconds from departure to reach `distance_m`, breaks included."""
        return elapsed_with_breaks(self.driving_s(distance_m))


def speed_mps(step: Step) -> float | None:
    """Google's speed for the step; None when it gives no time."""
    return step.distance_m / step.duration_s if step.duration_s else None


def elapsed_with_breaks(driving_s: float) -> int:
    """Clock time for `driving_s` of driving: a BREAK_S stop after every BREAK_AFTER_S
    (a point reached exactly as a break starts is reached before it)."""
    breaks = max(0, -(-int(driving_s) // BREAK_AFTER_S) - 1)  # ceil(driving / 8 h) - 1
    return round(driving_s) + breaks * BREAK_S

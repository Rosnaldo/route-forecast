"""Driving routes: a route, its points and Google's steps along it."""

from dataclasses import dataclass
from typing import NamedTuple


class Point(NamedTuple):
    """A position on a route. Still a (lat, lon) tuple: `lat, lon = point` works."""

    lat: float
    lon: float


class Step(NamedTuple):
    """One of Google's route steps (a street or highway section, maneuver to maneuver)."""

    distance_m: int
    duration_s: int  # Google's estimate, without traffic


# A route end: (lat, lon) coordinates, or an address/place name Google geocodes.
Waypoint = tuple[float, float] | str


@dataclass(frozen=True)
class Route:
    distance_m: int
    duration_s: int
    points: list[Point]  # departure first
    description: str = ""  # main roads, e.g. "I-80 E"
    source: str = "google"  # "google", or the fallback: "avoid_highways" / "detour"
    # Google's steps in order: street by street, highway by highway; their speeds
    # shape the travel times (see business/timing.py).
    steps: tuple[Step, ...] = ()

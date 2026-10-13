"""
Checkpoints along each route: a point every N miles (and the arrival), with the
expected travel time to reach it and the weather risk when the truck gets there.

Travel time follows the route's speed profile and the driver's breaks (timing.py).
The forecast comes from the
weather grid cell the checkpoint lies in (the same cells, and cached forecasts,
as the route's heat map), for the hour of the checkpoint's arrival time.
"""

import itertools
import time
import uuid
from dataclasses import dataclass

from django.core.cache import cache

from apps.core.exceptions import NotFoundError

from .risk import RiskLevel
from .routing import Route, haversine_m
from .timing import BREAK_S, TravelTimes, elapsed_with_breaks
from .weather import FORECAST_HOURS, Forecast, grid_center, hourly_forecasts

METERS_PER_MILE = 1609.344
TRIP_CACHE_SECONDS = 60 * 60  # how long a computed trip can get checkpoints


@dataclass(frozen=True)
class Trip:
    """What the route endpoint computed, kept so checkpoints need no new routing."""

    routes: list[Route]
    weight_lb: float
    step: float  # weather grid cell size


@dataclass(frozen=True)
class Checkpoint:
    lat: float
    lon: float
    distance_m: float  # along the route, from departure
    elapsed_s: int  # expected travel time from departure, breaks included
    breaks: int  # driver breaks (BREAK_S each) taken before reaching it
    eta: int  # unix time: departure + elapsed_s
    forecast: Forecast | None  # None beyond the forecast window
    level: RiskLevel | None
    is_arrival: bool


def save_trip(trip: Trip) -> str:
    """Keep a trip for TRIP_CACHE_SECONDS; returns its id."""
    trip_id = uuid.uuid4().hex
    cache.set(_trip_key(trip_id), trip, TRIP_CACHE_SECONDS)
    return trip_id


def load_trip(trip_id: str) -> Trip:
    trip = cache.get(_trip_key(trip_id))
    if trip is None:
        raise NotFoundError("Trip not found or expired; submit the route again")
    return trip


def _trip_key(trip_id: str) -> str:
    # v2: routes hold Point/Step objects; trips saved before that are not found.
    return f"trip:v2:{trip_id}"


def trip_checkpoints(
    trip: Trip, gap_mi: float, departure: float, now: float | None = None
) -> list[list[Checkpoint]]:
    """Checkpoints every `gap_mi` miles along each of the trip's routes, for a departure
    at unix time `departure`."""
    now = time.time() if now is None else now
    start = int(now - now % 3600)  # hour 0 of the forecast series
    window_end = now + FORECAST_HOURS * 3600

    placed = [_along(route, gap_mi * METERS_PER_MILE) for route in trip.routes]
    centers = [grid_center(lat, lon, trip.step) for route in placed for lat, lon, *_ in route]
    series = hourly_forecasts(centers, start)

    result = []
    for route, points in zip(trip.routes, placed, strict=True):
        times = TravelTimes(route)
        checkpoints = []
        for lat, lon, distance_m, is_arrival in points:
            driving = times.driving_s(distance_m)
            elapsed = elapsed_with_breaks(driving)
            eta = int(departure + elapsed)
            forecast = None
            if eta < window_end:
                hour = int((eta - start) // 3600)
                hours = series[grid_center(lat, lon, trip.step)]
                forecast = hours[hour] if 0 <= hour < len(hours) else None
            checkpoints.append(
                Checkpoint(
                    lat=round(lat, 5),
                    lon=round(lon, 5),
                    distance_m=round(distance_m),
                    elapsed_s=elapsed,
                    breaks=(elapsed - round(driving)) // BREAK_S,
                    eta=eta,
                    forecast=forecast,
                    level=forecast.level(trip.weight_lb) if forecast else None,
                    is_arrival=is_arrival,
                )
            )
        result.append(checkpoints)
    return result


def _along(route: Route, gap_m: float) -> list[tuple[float, float, float, bool]]:
    """(lat, lon, distance from departure, is_arrival) every `gap_m` along the route,
    then the arrival."""
    points = route.points
    if not points:
        return []
    marks = []
    next_mark = gap_m
    travelled = 0.0
    for a, b in itertools.pairwise(points):
        segment = haversine_m(*a, *b)
        while segment > 0 and travelled + segment >= next_mark:
            t = (next_mark - travelled) / segment
            marks.append(
                (a.lat + t * (b.lat - a.lat), a.lon + t * (b.lon - a.lon), next_mark, False)
            )
            next_mark += gap_m
        travelled += segment
    # The arrival, unless a mark already landed on it.
    if not marks or travelled - marks[-1][2] > 1:
        marks.append((*points[-1], travelled, True))
    else:
        marks[-1] = (*marks[-1][:3], True)
    return marks

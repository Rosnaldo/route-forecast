"""
Checkpoints along each route: a point every N miles (and the arrival), with the
expected travel time to reach it and the weather risk when the truck gets there.
Also the miles of each route at each risk level, segment by segment between the
route's points, for the same departure.

Travel time follows the route's speed profile and the driver's breaks (timing.py).
The forecast comes from the
weather grid cell the checkpoint lies in (the same cells, and cached forecasts,
as the route's heat map), for the hour of the checkpoint's arrival time.
"""

import itertools
import math
import time
import uuid
from dataclasses import dataclass
from typing import NamedTuple

from django.core.cache import cache

from apps.core.exceptions import NotFoundError

from .risk import RiskLevel
from .routing import Route, haversine_m
from .timing import BREAK_S, TravelTimes, elapsed_with_breaks
from .weather import FORECAST_HOURS, Forecast, grid_center, hourly_forecasts

METERS_PER_MILE = 1609.344
TRIP_CACHE_SECONDS = 60 * 60  # how long a computed trip can get checkpoints
# Miles per risk level: stretches between points longer than this (straight highways
# can have points kilometers apart) are split, each piece with its own forecast.
MAX_SEGMENT_M = 1000


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


# Keys of RouteCheckpoints.miles_by_level: the risk levels, then stretches without one.
MILES_KEYS = (*(level.name.lower() for level in RiskLevel), "no_forecast")


class RouteCheckpoints(NamedTuple):
    checkpoints: list[Checkpoint]
    # Miles at each risk level (MILES_KEYS) when the truck gets there; they sum to the
    # route's length.
    miles_by_level: dict[str, float]


class RouteRisk(NamedTuple):
    """A route's weather risk and travel time for one departure."""

    miles_by_level: dict[str, float]  # MILES_KEYS -> miles, summing to the route length
    average_level: float | None  # mile-weighted mean level (0-4); None if no forecast
    travel_s: int  # to the arrival, breaks included


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
) -> list[RouteCheckpoints]:
    """Checkpoints every `gap_mi` miles along each of the trip's routes, and each route's
    miles per risk level, for a departure at unix time `departure`."""
    placed = [_along(route, gap_mi * METERS_PER_MILE) for route in trip.routes]
    forecast_at = _forecast_lookup(trip, [p[:2] for route in placed for p in route], now)

    result = []
    for route, points, risk in zip(
        trip.routes, placed, route_risks(trip, departure, now), strict=True
    ):
        times = TravelTimes(route)
        checkpoints = []
        for lat, lon, distance_m, is_arrival in points:
            driving = times.driving_s(distance_m)
            elapsed = elapsed_with_breaks(driving)
            eta = int(departure + elapsed)
            forecast = forecast_at(lat, lon, eta)
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
        result.append(RouteCheckpoints(checkpoints, risk.miles_by_level))
    return result


def route_risks(trip: Trip, departure: float, now: float | None = None) -> list[RouteRisk]:
    """Each route's miles per risk level, average risk and travel time, segment by
    segment between its points, for a departure at unix time `departure`."""
    segments = [_segments(route) for route in trip.routes]
    forecast_at = _forecast_lookup(trip, [s[:2] for route in segments for s in route], now)

    risks = []
    for route, route_segments in zip(trip.routes, segments, strict=True):
        times = TravelTimes(route)
        meters = dict.fromkeys(MILES_KEYS, 0.0)
        level_meters = 0.0  # sum of level x length, for the average
        for lat, lon, middle_m, length_m in route_segments:
            forecast = forecast_at(lat, lon, departure + times.elapsed_s(middle_m))
            if forecast:
                level = forecast.level(trip.weight_lb)
                meters[level.name.lower()] += length_m
                level_meters += level * length_m
            else:
                meters["no_forecast"] += length_m
        with_forecast = sum(meters.values()) - meters["no_forecast"]
        risks.append(
            RouteRisk(
                miles_by_level={k: round(m / METERS_PER_MILE, 1) for k, m in meters.items()},
                average_level=level_meters / with_forecast if with_forecast else None,
                travel_s=times.elapsed_s(route.length_m()),
            )
        )
    return risks


def _forecast_lookup(trip: Trip, positions: list[tuple[float, float]], now: float | None):
    """forecast_at(lat, lon, eta): the forecast of the grid cell around (lat, lon) for the
    hour of `eta`, None outside the window. Forecasts for `positions` are loaded once."""
    now = time.time() if now is None else now
    start = int(now - now % 3600)  # hour 0 of the forecast series
    window_end = now + FORECAST_HOURS * 3600
    series = hourly_forecasts([grid_center(lat, lon, trip.step) for lat, lon in positions], start)

    def forecast_at(lat: float, lon: float, eta: float) -> Forecast | None:
        if eta >= window_end:
            return None
        hour = int((eta - start) // 3600)
        hours = series.get(grid_center(lat, lon, trip.step), [])
        return hours[hour] if 0 <= hour < len(hours) else None

    return forecast_at


def _segments(route: Route) -> list[tuple[float, float, float, float]]:
    """(mid lat, mid lon, distance from departure to the middle, length) for each
    stretch between consecutive points of the route, split to at most MAX_SEGMENT_M."""
    segments = []
    travelled = 0.0
    for a, b in itertools.pairwise(route.points):
        length = haversine_m(*a, *b)
        pieces = math.ceil(length / MAX_SEGMENT_M)
        for k in range(pieces):
            t = (k + 0.5) / pieces  # middle of the piece, as a share of the stretch
            mid = (a.lat + t * (b.lat - a.lat), a.lon + t * (b.lon - a.lon))
            segments.append((*mid, travelled + t * length, length / pieces))
        travelled += length
    return segments


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

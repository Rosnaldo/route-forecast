"""
The trip use cases, one function each, called by the controllers:

    plan_trip           routes between two places, saved as a trip
    weather_stream      a trip's weather grid, then its forecasts batch by batch
    plan_checkpoints    checkpoints along each route for a departure
    recommend_route     the route to take for a departure
    example_routes      sample trips for trying the route endpoint

A trip's weather grid is built after its routes are returned: the counties each
route crosses (in parallel: shapely's geometry work runs outside the GIL) and the
grid over them (business.weather.weather_grid). The trip is updated with the grid's
cell size, points and start, which the checkpoints and recommendation read.
"""

import csv
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from django.conf import settings
from django.core.cache import cache

from ..business.recommendation import recommend
from ..business.trip import route_risks, trip_checkpoints
from ..business.weather import weather_grid
from ..domain.recommendation import Recommendation
from ..domain.route import Route, Waypoint
from ..domain.trip import RouteCheckpoints, RouteRisk, Trip, TripGrid
from ..domain.weather import FailedBatch, ForecastBatch
from .counties import counties_along
from .routing import compute_routes
from .trip_store import load_trip, save_trip, update_trip
from .weather import forecast_events, hourly_forecasts

EXAMPLE_ROUTES_FILE = settings.BASE_DIR / "example_routes.csv"
# Route risks for a trip and departure are kept this long: the checkpoints and the
# recommendation requests for the same departure share one calculation.
RISKS_CACHE_SECONDS = 5 * 60


def plan_trip(departure: Waypoint, arrival: Waypoint, weight_lb: float) -> tuple[str, list[Route]]:
    """Up to three driving routes, kept as a trip for `weight_lb` of cargo; returns the
    trip's id and its routes (fastest first)."""
    routes = compute_routes(departure, arrival)
    return save_trip(Trip(routes, weight_lb)), routes


def weather_stream(trip_id: str) -> Iterator[TripGrid | ForecastBatch | FailedBatch]:
    """The trip's grid, then its forecasts as they arrive (start of the trip first).
    An unknown trip raises NotFoundError here, before anything is computed."""
    trip = load_trip(trip_id)

    def events():
        grid = build_grid(trip_id, trip)
        yield grid
        yield from forecast_events(list(grid.trip.points), grid.trip.start, trip.weight_lb)

    return events()


def plan_checkpoints(trip_id: str, gap_mi: float, departure: float) -> list[RouteCheckpoints]:
    """Checkpoints every `gap_mi` miles along each route of the trip, and each route's
    miles per risk level, leaving at unix time `departure`."""
    trip = ensure_grid(trip_id, load_trip(trip_id))
    risks = cached_route_risks(trip_id, trip, departure)
    return trip_checkpoints(trip, gap_mi, departure, hourly_forecasts, risks=risks)


def recommend_route(trip_id: str, departure: float) -> Recommendation:
    """The trip's routes ranked for a departure at unix time `departure`."""
    # Usually already computed by the checkpoints request for the same departure.
    trip = ensure_grid(trip_id, load_trip(trip_id))
    return recommend(cached_route_risks(trip_id, trip, departure))


def example_routes() -> list[dict]:
    """Sample trips from example_routes.csv."""
    with EXAMPLE_ROUTES_FILE.open(newline="") as file:
        return [
            {**row, "id": int(row["id"]), "distance_km": int(row["distance_km"])}
            for row in csv.DictReader(file)
        ]


def build_grid(trip_id: str, trip: Trip) -> TripGrid:
    with ThreadPoolExecutor(max(len(trip.routes), 1)) as pool:
        counties = list(pool.map(lambda route: counties_along(route.points), trip.routes))
    weather = weather_grid(list(zip(trip.routes, counties, strict=True)), trip.weight_lb)
    trip = replace(trip, step=weather.step, points=tuple(weather.points), start=weather.start)
    update_trip(trip_id, trip)
    return TripGrid(trip, weather, counties)


def ensure_grid(trip_id: str, trip: Trip) -> Trip:
    """The trip with its grid: normally built by the weather stream already."""
    return trip if trip.step else build_grid(trip_id, trip).trip


def cached_route_risks(trip_id: str, trip: Trip, departure: float) -> list[RouteRisk]:
    """route_risks, kept RISKS_CACHE_SECONDS per trip and departure (to the second)."""
    key = f"risks:{trip_id}:{int(departure)}"
    risks = cache.get(key)
    if risks is None:
        risks = route_risks(trip, departure, hourly_forecasts)
        cache.set(key, risks, RISKS_CACHE_SECONDS)
    return risks

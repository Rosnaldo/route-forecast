"""
A trip's weather grid, built after its routes are returned: the counties each route
crosses (in parallel: shapely's geometry work runs outside the GIL) and the grid
over them (weather.weather_grid). The trip is updated with the grid's cell size,
points and start, which the checkpoints and recommendation read.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import NamedTuple

from .checkpoints import Trip, update_trip
from .counties import County, counties_along
from .weather import WeatherGrid, weather_grid


class TripGrid(NamedTuple):
    trip: Trip  # with the grid's step, points and start
    weather: WeatherGrid
    counties: list[list[County]]  # per route, in travel order


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

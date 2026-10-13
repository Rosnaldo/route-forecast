"""
A trip (its routes, cargo and weather grid), the checkpoints along its routes and
each route's weather risk for a departure. How they are computed: business/trip.py.
"""

from dataclasses import dataclass
from typing import NamedTuple, Protocol

from .county import County
from .risk import RiskLevel
from .route import Route
from .weather import Forecast, GridCenter, WeatherGrid


@dataclass(frozen=True)
class Trip:
    """What the route endpoint computed, kept so checkpoints need no new routing."""

    routes: list[Route]
    weight_lb: float
    # The weather grid, added once built (services/trips.py): cell size (0 until then),
    # forecast points (cell centers, in streaming order) and unix time of hour 0 of
    # their series.
    step: float = 0.0
    points: tuple[GridCenter, ...] = ()
    start: int = 0


class TripGrid(NamedTuple):
    trip: Trip  # with the grid's step, points and start
    weather: WeatherGrid
    counties: list[list[County]]  # per route, in travel order


@dataclass(frozen=True)
class Checkpoint:
    lat: float
    lon: float
    distance_m: float  # along the route, from departure
    elapsed_s: int  # expected travel time from departure, breaks included
    breaks: int  # 30-minute driver breaks taken before reaching it
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


class ForecastSource(Protocol):
    """Hourly forecasts from unix time `start` (hour 0) for grid cell centers: index k
    is the hour starting k hours after `start`; None where there is no forecast.
    Implemented by services/weather.py."""

    def __call__(
        self, centers: list[GridCenter], start: int
    ) -> dict[GridCenter, list[Forecast | None]]: ...

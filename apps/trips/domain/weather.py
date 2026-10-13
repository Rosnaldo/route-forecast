"""
The weather grid over the counties a route crosses, and its forecasts.

A fixed lat/lon grid covers the counties; each cell's center gets an hourly
forecast. Cells are clipped to each county outline, so a cell on a border is split
into one piece per county; the pieces share the center's forecast. How the grid
is built: business/weather.py.
"""

from dataclasses import dataclass
from typing import NamedTuple

import shapely

from .county import County


class GridCenter(NamedTuple):
    """The middle of one square of the weather grid: the location whose forecast stands
    for the whole square (and the cache key for it). A (lat, lon) tuple too."""

    lat: float
    lon: float


@dataclass(frozen=True)
class Forecast:
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass(frozen=True)
class GridPoint:
    """A cell center. Hourly series: index k is the hour starting k hours after
    WeatherGrid.start, for k = 0..FORECAST_HOURS; None where there is no forecast."""

    lat: float
    lon: float
    hours: list[Forecast | None]
    weight_lb: float  # cargo weight the levels are for


@dataclass(frozen=True)
class Cell:
    point: int  # index into WeatherGrid.points
    county: County
    piece: shapely.Polygon | shapely.MultiPolygon  # the grid cell clipped to the county


@dataclass(frozen=True)
class RouteCell:
    cell: int  # index into WeatherGrid.cells
    offset_s: int  # seconds after departure the truck passes nearest to the cell's center


@dataclass(frozen=True)
class WeatherGrid:
    """The grid's layout: where each forecast point and cell is, without forecasts
    (those are streamed afterwards, see services/weather.py)."""

    now: int  # unix time the grid was made; departure offsets count from here
    start: int  # unix time of hour 0 in the series (the start of the current hour)
    weight_lb: float
    step: float  # cell size in degrees (coarser than GRID_STEP on long trips)
    # The cells' centers, ordered by when the truck first reaches them on any route:
    # forecasts for the start of the trip are fetched first.
    points: list[GridCenter]
    cells: list[Cell]  # each once, however many routes cross it
    route_cells: list[list[RouteCell]]  # per route, in the order given


class ForecastBatch(NamedTuple):
    """Forecasts for some of a grid's points, as (index into the points, GridPoint)."""

    points: list[tuple[int, GridPoint]]


class FailedBatch(NamedTuple):
    indices: list[int]  # points left without a forecast
    detail: str

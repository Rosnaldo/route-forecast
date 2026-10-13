"""
Building the weather grid over the counties a route crosses.

The counties each route crosses are covered by a fixed lat/lon grid. Each cell's
center gets the hourly forecast for the whole window, classified hour by hour
with the rules in risk.py. Each route's cells also carry how long after
departure the truck passes nearest to their center (route speeds and breaks, see
timing.py); the client picks a departure time and reads each center's risk for the
hour the truck gets there. Cells are clipped to each county outline, so a cell
on a border is split into one piece per county; the pieces share the center's
forecast. Routes share the grid, so a center on several routes is fetched once.

The forecasts themselves come from services/weather.py. Open-Meteo's free tier
counts every location as a call, so the grid is capped at MAX_CELLS (long routes
get bigger cells).
"""

import math
import time

import numpy as np
import shapely
from shapely import LineString, Point

from ..domain.county import County
from ..domain.route import Route
from ..domain.weather import Cell, GridCenter, GridPoint, RouteCell, WeatherGrid
from .risk import forecast_level
from .route import length_m
from .timing import TravelTimes

FORECAST_HOURS = 48  # the app's forecast window
GRID_STEP = 0.2  # degrees, ~20 km; about the resolution of the US forecast models
MAX_CELLS = 300  # long routes get a coarser grid instead of more requests


def weather_grid(
    routes: list[tuple[Route, list[County]]], weight_lb: float = 0, now: float | None = None
) -> WeatherGrid:
    """Grid over the counties of each (route, counties crossed): its cells, their
    forecast points, and when each route reaches them. No forecasts are fetched."""
    now = int(time.time() if now is None else now)
    start = now - now % 3600
    routes = [
        (route, [county for county in counties if county.geometry is not None])
        for route, counties in routes
    ]

    # One step for all routes, coarse enough that their cells together fit MAX_CELLS.
    step = _grid_step([counties for _, counties in routes])
    pieces = [_grid_pieces(counties, step) for _, counties in routes]

    # When each route passes nearest to each of its cell centers.
    offsets = []
    for (route, _), route_pieces in zip(routes, pieces, strict=True):
        line = (
            LineString([(lon, lat) for lat, lon in route.points]) if len(route.points) > 1 else None
        )
        route_m, times = length_m(route), TravelTimes(route)
        offsets.append(
            {
                center: _offset_s(line, center, route_m, times)
                for center in {center for center, _, _ in route_pieces}
            }
        )
    earliest: dict[GridCenter, int] = {}
    for route_offsets in offsets:
        for center, offset in route_offsets.items():
            earliest[center] = min(offset, earliest.get(center, offset))
    centers = sorted(earliest, key=lambda center: (earliest[center], center))

    point_index = {center: i for i, center in enumerate(centers)}
    cells: list[Cell] = []
    cell_index: dict[tuple, int] = {}  # (center, fips) -> index into cells
    route_cells = []
    for route_pieces, route_offsets in zip(pieces, offsets, strict=True):
        this_route = []
        for center, county, piece in route_pieces:
            key = (center, county.fips)
            if key not in cell_index:
                cell_index[key] = len(cells)
                cells.append(Cell(point_index[center], county, piece))
            this_route.append(RouteCell(cell_index[key], route_offsets[center]))
        route_cells.append(this_route)
    return WeatherGrid(now, start, weight_lb, step, centers, cells, route_cells)


def point_series(point: GridPoint) -> dict[str, list]:
    """A grid point's hourly series, one list per field: None where there is no
    forecast; levels for the point's cargo weight."""
    hours = point.hours
    return {
        "wind_mph": [f and f.wind_mph for f in hours],
        "rain_in_hr": [f and f.rain_in_hr for f in hours],
        "snow_in_hr": [f and f.snow_in_hr for f in hours],
        "levels": [f and forecast_level(f, point.weight_lb) for f in hours],
    }


def grid_center(lat: float, lon: float, step: float) -> GridCenter:
    """Center (lat, lon) of the grid cell of size `step` that contains (lat, lon)."""
    return _center(math.floor(lat / step), math.floor(lon / step), step)


def _center(i: int, j: int, step: float) -> GridCenter:
    return GridCenter(round((i + 0.5) * step, 4), round((j + 0.5) * step, 4))


def _grid_step(counties_per_route: list[list[County]]) -> float:
    """Cell size: GRID_STEP, or coarser until all routes' cells fit MAX_CELLS.

    The number of cells shrinks roughly with the square of the size, so each try
    jumps straight to the size that should fit; counting is cheap (no clipping), and
    one or two counts are usually enough."""
    step = GRID_STEP
    while (count := _cell_count(counties_per_route, step)) > MAX_CELLS:
        step *= max(1.05, math.sqrt(count / MAX_CELLS) * 1.02)
    return step


def _cell_count(counties_per_route: list[list[County]], step: float) -> int:
    """Grid cells of size `step` touching any of the counties (all routes, each once)."""
    centers = set()
    for counties in counties_per_route:
        for county in counties:
            cells, indices = _candidate_cells(county, step)
            touching = shapely.intersects(cells, county.geometry)
            centers.update(_center(i, j, step) for i, j in indices[touching])
    return len(centers)


def _grid_pieces(counties: list[County], step: float):
    """(cell center (lat, lon), county, cell clipped to county) for every non-empty piece."""
    pieces = []
    for county in counties:
        cells, indices = _candidate_cells(county, step)
        touching = shapely.intersects(cells, county.geometry)
        clipped = shapely.intersection(cells[touching], county.geometry)
        # Skip empty pieces and float-rounding slivers.
        keep = shapely.area(clipped) >= step * step * 1e-6
        for (i, j), piece in zip(indices[touching][keep], clipped[keep], strict=True):
            pieces.append((_center(int(i), int(j), step), county, piece))
    return pieces


def _candidate_cells(county: County, step: float) -> tuple[np.ndarray, np.ndarray]:
    """The grid cells covering the county's bounding box, and their (i, j) indices
    (row i: latitude, column j: longitude). The county is prepared for fast tests."""
    shapely.prepare(county.geometry)
    min_lon, min_lat, max_lon, max_lat = county.geometry.bounds
    i, j = np.meshgrid(
        np.arange(math.floor(min_lat / step), math.ceil(max_lat / step)),
        np.arange(math.floor(min_lon / step), math.ceil(max_lon / step)),
        indexing="ij",
    )
    i, j = i.ravel(), j.ravel()
    cells = shapely.box(j * step, i * step, (j + 1) * step, (i + 1) * step)
    return cells, np.column_stack([i, j])


def _offset_s(
    line: LineString | None, center: GridCenter, route_m: float, times: TravelTimes
) -> int:
    """Seconds after departure the truck is nearest to `center` (see timing.py)."""
    if line is None or line.length == 0:
        return 0
    lat, lon = center
    return times.elapsed_s(line.project(Point(lon, lat), normalized=True) * route_m)

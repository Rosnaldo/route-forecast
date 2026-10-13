"""
Weather risk on a grid over the counties a route crosses, via Open-Meteo.

The counties each route crosses are covered by a fixed lat/lon grid. Each cell's
center gets the hourly forecast for the whole window, classified hour by hour
with the rules in risk.py. Each route's cells also carry how long after
departure the truck passes nearest to their center (route speeds and breaks, see
timing.py); the client picks a departure time and reads each center's risk for the
hour the truck gets there. Cells are clipped to each county outline, so a cell
on a border is split into one piece per county; the pieces share the center's
forecast. Routes share the grid, so a center on several routes is fetched once.

Open-Meteo's free tier counts every location as a call (600 a minute), so the
grid is capped at MAX_CELLS (long routes get bigger cells) and each center's
hourly forecast is cached for a while.
"""

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import shapely
from django.core.cache import cache
from shapely import LineString, Point
from shapely.geometry import mapping

from apps.core.exceptions import UpstreamError

from .counties import DISPLAY_GRID, DISPLAY_TOLERANCE, County
from .risk import Condition, RiskLevel, overall
from .routing import Route
from .timing import TravelTimes

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 15
FORECAST_HOURS = 48  # the app's forecast window
GRID_STEP = 0.2  # degrees, ~20 km; about the resolution of the US forecast models
MAX_CELLS = 300  # long routes get a coarser grid instead of more requests
CACHE_SECONDS = 30 * 60
LOCATIONS_PER_REQUEST = 80  # also the size of each streamed batch
PARALLEL_REQUESTS = 4


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

    def level(self, weight_lb: float = 0) -> RiskLevel:
        return overall(
            {
                Condition.WIND: self.wind_mph,
                Condition.RAIN: self.rain_in_hr,
                Condition.SNOW: self.snow_in_hr,
            },
            weight_lb,
        )


@dataclass(frozen=True)
class GridPoint:
    """A cell center. Hourly series: index k is the hour starting k hours after
    WeatherGrid.start, for k = 0..FORECAST_HOURS; None where there is no forecast."""

    lat: float
    lon: float
    hours: list[Forecast | None]
    weight_lb: float  # cargo weight the levels are for

    @property
    def wind_mph(self) -> list[float | None]:
        return [f and f.wind_mph for f in self.hours]

    @property
    def rain_in_hr(self) -> list[float | None]:
        return [f and f.rain_in_hr for f in self.hours]

    @property
    def snow_in_hr(self) -> list[float | None]:
        return [f and f.snow_in_hr for f in self.hours]

    @property
    def levels(self) -> list[RiskLevel | None]:
        """Hourly risk level for the cargo weight."""
        return [f and f.level(self.weight_lb) for f in self.hours]


@dataclass(frozen=True)
class Cell:
    point: int  # index into WeatherGrid.points
    county: County
    piece: shapely.Polygon | shapely.MultiPolygon  # the grid cell clipped to the county

    def outline(self) -> dict:
        simplified = self.piece.simplify(DISPLAY_TOLERANCE)
        return mapping(shapely.set_precision(simplified, DISPLAY_GRID))


@dataclass(frozen=True)
class RouteCell:
    cell: int  # index into WeatherGrid.cells
    offset_s: int  # seconds after departure the truck passes nearest to the cell's center


@dataclass(frozen=True)
class WeatherGrid:
    """The grid's layout: where each forecast point and cell is, without forecasts
    (those are streamed afterwards, see forecast_events)."""

    now: int  # unix time the grid was made; departure offsets count from here
    start: int  # unix time of hour 0 in the series (the start of the current hour)
    weight_lb: float
    step: float  # cell size in degrees (coarser than GRID_STEP on long trips)
    # The cells' centers, ordered by when the truck first reaches them on any route:
    # forecasts for the start of the trip are fetched first.
    points: list[GridCenter]
    cells: list[Cell]  # each once, however many routes cross it
    route_cells: list[list[RouteCell]]  # per route, in the order given


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
        length_m, times = route.length_m(), TravelTimes(route)
        offsets.append(
            {
                center: _offset_s(line, center, length_m, times)
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


class ForecastBatch(NamedTuple):
    """Forecasts for some of a grid's points, as (index into the points, GridPoint)."""

    points: list[tuple[int, GridPoint]]


class FailedBatch(NamedTuple):
    indices: list[int]  # points left without a forecast
    detail: str


def forecast_events(
    centers: list[GridCenter], start: int, weight_lb: float
) -> Iterator[ForecastBatch | FailedBatch]:
    """Forecasts for `centers`, in batches of LOCATIONS_PER_REQUEST as they become
    available: cached ones first (in order), then one Open-Meteo request per batch of
    the rest, PARALLEL_REQUESTS at a time, each yielded as soon as it completes. A
    failed request yields a FailedBatch; the others still come."""

    def batch(indices: list[int], hourly: dict) -> ForecastBatch:
        return ForecastBatch(
            [
                (i, GridPoint(*centers[i], _series(hourly[centers[i]], start), weight_lb))
                for i in indices
            ]
        )

    keys = {center: _cache_key(center) for center in centers}
    cached = cache.get_many(keys.values())
    hourly = {center: cached[key] for center, key in keys.items() if key in cached}

    ready = [i for i, center in enumerate(centers) if center in hourly]
    for chunk in _chunks(ready):
        yield batch(chunk, hourly)

    missing = [i for i, center in enumerate(centers) if center not in hourly]
    pool = ThreadPoolExecutor(PARALLEL_REQUESTS)
    try:
        futures = {
            pool.submit(_fetch_batch, [centers[i] for i in chunk]): chunk
            for chunk in _chunks(missing)
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                fetched = future.result()
            except UpstreamError as exc:
                yield FailedBatch(chunk, exc.message)
                continue
            yield batch(chunk, fetched)
    finally:
        # The client may leave mid-stream: drop requests that have not started.
        pool.shutdown(wait=False, cancel_futures=True)


def _chunks(items: list) -> list[list]:
    return [
        items[i : i + LOCATIONS_PER_REQUEST] for i in range(0, len(items), LOCATIONS_PER_REQUEST)
    ]


def grid_center(lat: float, lon: float, step: float) -> GridCenter:
    """Center (lat, lon) of the grid cell of size `step` that contains (lat, lon)."""
    return _center(math.floor(lat / step), math.floor(lon / step), step)


def _center(i: int, j: int, step: float) -> GridCenter:
    return GridCenter(round((i + 0.5) * step, 4), round((j + 0.5) * step, 4))


def hourly_forecasts(
    centers: list[GridCenter], start: int
) -> dict[GridCenter, list[Forecast | None]]:
    """Hourly forecasts from `start` for grid cell centers (cached like the grid's)."""
    centers = sorted(set(centers))
    hourly = _fetch(centers)
    return {center: _series(hourly[center], start) for center in centers}


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
    line: LineString | None, center: GridCenter, length_m: float, times: TravelTimes
) -> int:
    """Seconds after departure the truck is nearest to `center` (see timing.py)."""
    if line is None or line.length == 0:
        return 0
    lat, lon = center
    return times.elapsed_s(line.project(Point(lon, lat), normalized=True) * length_m)


def _fetch(centers: list[GridCenter]) -> dict[GridCenter, dict]:
    """Open-Meteo's hourly data for each center; cached centers skip the request."""
    keys = {center: _cache_key(center) for center in centers}
    cached = cache.get_many(keys.values())
    hourly = {center: cached[key] for center, key in keys.items() if key in cached}

    missing = [center for center in centers if center not in hourly]
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        for fetched in pool.map(_fetch_batch, _chunks(missing)):
            hourly.update(fetched)
    return hourly


def _fetch_batch(batch: list[GridCenter]) -> dict[GridCenter, dict]:
    """One Open-Meteo request for `batch`; the results are cached."""
    locations = _request(batch)
    if len(locations) != len(batch):
        raise UpstreamError("Weather API returned the wrong number of locations")
    hourly = {center: location["hourly"] for center, location in zip(batch, locations, strict=True)}
    cache.set_many({_cache_key(center): data for center, data in hourly.items()}, CACHE_SECONDS)
    return hourly


def _cache_key(center: GridCenter) -> str:
    return "weather:{}:{}".format(*center)


def _request(batch: list[GridCenter]) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "latitude": ",".join(str(lat) for lat, _ in batch),
            "longitude": ",".join(str(lon) for _, lon in batch),
            "hourly": "wind_speed_10m,rain,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",  # rain and snowfall per hour, in inches
            # Hours 0..FORECAST_HOURS, plus one: precipitation is stamped at the hour's end.
            "forecast_hours": FORECAST_HOURS + 2,
            "timeformat": "unixtime",
            "timezone": "GMT",
        }
    )
    try:
        with urllib.request.urlopen(
            f"{FORECAST_URL}?{params}", timeout=TIMEOUT_SECONDS
        ) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise UpstreamError("Weather API rate limit reached, try again in a minute") from exc
        raise UpstreamError("Weather API request failed", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpstreamError("Weather API is unreachable") from exc
    # A single location comes back as an object, several as a list.
    return data if isinstance(data, list) else [data]


def _series(hourly: dict, start: int) -> list[Forecast | None]:
    """Forecasts for the hours starting at `start`, `start` + 1 h, ... (FORECAST_HOURS + 1).

    Wind is the value at the start of each hour; rain and snowfall are totals
    over the hour *before* each timestamp, so they come from the next one.
    Cached data may begin an hour or so before `start`, hence the shift.
    """
    times = hourly["time"]
    if not times:
        return [None] * (FORECAST_HOURS + 1)
    shift = round((start - times[0]) / 3600)
    series = []
    for k in range(FORECAST_HOURS + 1):
        i = k + shift
        if 0 <= i < len(times) - 1:
            series.append(
                Forecast(
                    wind_mph=hourly["wind_speed_10m"][i] or 0,
                    rain_in_hr=hourly["rain"][i + 1] or 0,
                    snow_in_hr=hourly["snowfall"][i + 1] or 0,
                )
            )
        else:
            series.append(None)
    return series

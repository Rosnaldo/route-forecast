"""
Weather risk on a grid over the counties a route crosses, via Open-Meteo.

The counties are covered by a fixed lat/lon grid. Each cell's center gets the
hourly forecast for the whole window, classified hour by hour with the rules in
risk.py, plus how long after departure the truck passes nearest to it (at the
route's average speed). The client picks a departure time and reads each
center's risk for the hour the truck gets there. Cells are clipped to each
county outline, so a cell on a border is split into one piece per county; the
pieces share the center's forecast.

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import shapely
from django.core.cache import cache
from shapely import LineString, Point, box
from shapely.geometry import mapping

from apps.core.exceptions import UpstreamError

from .counties import DISPLAY_GRID, DISPLAY_TOLERANCE, County
from .risk import Condition, RiskLevel, overall
from .routing import Route

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 15
FORECAST_HOURS = 48  # the app's forecast window
GRID_STEP = 0.2  # degrees, ~20 km; about the resolution of the US forecast models
MAX_CELLS = 300  # long routes get a coarser grid instead of more requests
CACHE_SECONDS = 30 * 60
LOCATIONS_PER_REQUEST = 100
PARALLEL_REQUESTS = 4


@dataclass(frozen=True)
class Forecast:
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float

    @property
    def level(self) -> RiskLevel:
        return overall(
            {
                Condition.WIND: self.wind_mph,
                Condition.RAIN: self.rain_in_hr,
                Condition.SNOW: self.snow_in_hr,
            }
        )


@dataclass(frozen=True)
class GridPoint:
    """A cell center. Hourly series: index k is the hour starting k hours after
    WeatherGrid.start, for k = 0..FORECAST_HOURS; None where there is no forecast."""

    lat: float
    lon: float
    offset_s: int  # seconds after departure the truck passes nearest to here
    hours: list[Forecast | None]

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
        return [f and f.level for f in self.hours]


@dataclass(frozen=True)
class Cell:
    point: int  # index into WeatherGrid.points
    county: County
    piece: shapely.Polygon | shapely.MultiPolygon  # the grid cell clipped to the county

    def outline(self) -> dict:
        simplified = self.piece.simplify(DISPLAY_TOLERANCE)
        return mapping(shapely.set_precision(simplified, DISPLAY_GRID))


@dataclass(frozen=True)
class WeatherGrid:
    now: int  # unix time the grid was made; departure offsets count from here
    start: int  # unix time of hour 0 in the series (the start of the current hour)
    points: list[GridPoint]
    cells: list[Cell]


def weather_grid(route: Route, counties: list[County], now: float | None = None) -> WeatherGrid:
    """Grid over `counties` with each center's hourly forecast and risk level."""
    now = int(time.time() if now is None else now)
    start = now - now % 3600
    counties = [county for county in counties if county.geometry is not None]
    if not counties or not route.points:
        return WeatherGrid(now, start, [], [])

    step = GRID_STEP
    pieces = _grid_pieces(counties, step)
    while _cell_count(pieces) > MAX_CELLS:
        step *= 1.5
        pieces = _grid_pieces(counties, step)

    line = LineString([(lon, lat) for lat, lon in route.points]) if len(route.points) > 1 else None
    centers = sorted({center for center, _, _ in pieces})
    hourly = _fetch(centers)
    points = [
        GridPoint(
            lat,
            lon,
            round(_offset_s(line, (lat, lon), route.duration_s)),
            _series(hourly[(lat, lon)], start),
        )
        for lat, lon in centers
    ]
    index = {center: i for i, center in enumerate(centers)}
    cells = [Cell(index[center], county, piece) for center, county, piece in pieces]
    return WeatherGrid(now, start, points, cells)


def _grid_pieces(counties: list[County], step: float):
    """(cell center (lat, lon), county, cell clipped to county) for every non-empty piece."""
    pieces = []
    for county in counties:
        min_lon, min_lat, max_lon, max_lat = county.geometry.bounds
        for i in range(math.floor(min_lat / step), math.ceil(max_lat / step)):
            for j in range(math.floor(min_lon / step), math.ceil(max_lon / step)):
                cell = box(j * step, i * step, (j + 1) * step, (i + 1) * step)
                piece = cell.intersection(county.geometry)
                if piece.area < cell.area * 1e-6:  # nothing, or a float-rounding sliver
                    continue
                center = (round((i + 0.5) * step, 4), round((j + 0.5) * step, 4))
                pieces.append((center, county, piece))
    return pieces


def _cell_count(pieces) -> int:
    return len({center for center, _, _ in pieces})


def _offset_s(line: LineString | None, center: tuple[float, float], duration_s: int) -> float:
    """Seconds after departure the truck is nearest to `center`, at constant speed."""
    if line is None or line.length == 0:
        return 0
    lat, lon = center
    return line.project(Point(lon, lat), normalized=True) * duration_s


def _fetch(centers) -> dict[tuple[float, float], dict]:
    """Open-Meteo's hourly data for each center; cached centers skip the request."""
    keys = {center: "weather:{}:{}".format(*center) for center in centers}
    cached = cache.get_many(keys.values())
    hourly = {center: cached[key] for center, key in keys.items() if key in cached}

    missing = [center for center in centers if center not in hourly]
    batches = [
        missing[i : i + LOCATIONS_PER_REQUEST]
        for i in range(0, len(missing), LOCATIONS_PER_REQUEST)
    ]
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        responses = list(pool.map(_request, batches))
    for batch, locations in zip(batches, responses, strict=True):
        if len(locations) != len(batch):
            raise UpstreamError("Weather API returned the wrong number of locations")
        for center, location in zip(batch, locations, strict=True):
            hourly[center] = location["hourly"]
    cache.set_many({keys[center]: hourly[center] for center in missing}, CACHE_SECONDS)
    return hourly


def _request(batch: list[tuple[float, float]]) -> list[dict]:
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

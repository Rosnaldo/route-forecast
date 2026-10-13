"""
Hourly forecasts for weather grid centers, via Open-Meteo.

Open-Meteo's free tier counts every location as a call (600 a minute), so each
center's hourly forecast is cached for a while, and requests carry
LOCATIONS_PER_REQUEST locations each.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache

from apps.core.exceptions import UpstreamError

from ..business.weather import FORECAST_HOURS
from ..domain.weather import (
    FailedBatch,
    Forecast,
    ForecastBatch,
    GridCenter,
    GridPoint,
)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 15
CACHE_SECONDS = 30 * 60
LOCATIONS_PER_REQUEST = 80  # also the size of each streamed batch
PARALLEL_REQUESTS = 4


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


def hourly_forecasts(
    centers: list[GridCenter], start: int
) -> dict[GridCenter, list[Forecast | None]]:
    """Hourly forecasts from `start` for grid cell centers (cached like the grid's)."""
    centers = sorted(set(centers))
    hourly = _fetch(centers)
    return {center: _series(hourly[center], start) for center in centers}


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

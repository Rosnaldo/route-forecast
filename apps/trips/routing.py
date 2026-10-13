"""
Driving routes between two points, via the Google Routes API (computeRoutes).

Google returns the fastest route plus up to two alternatives when there are
reasonable ones; a trip with a single sensible road gets one route. To still offer
MAX_ROUTES options, we then ask for fallback routes (avoiding highways, or passing
through a point off to one side of the direct line) and keep the ones that are
really different and not absurdly long. Each route's geometry comes back as an
encoded polyline; we decode it to a list of (lat, lon) points, which later steps
(counties, weather) walk along.
"""

import json
import math
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.conf import settings
from shapely import LineString

from apps.core.exceptions import DomainError, UpstreamError

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join(
    f"routes.{field}"
    for field in ("distanceMeters", "duration", "polyline.encodedPolyline", "description")
)
TIMEOUT_SECONDS = 10
# Line detail sent to the map: ~50 m simplification, 5 decimals (~1 m).
DISPLAY_TOLERANCE = 0.0005
DISPLAY_DECIMALS = 5

MAX_ROUTES = 3
# Fallback routes must differ from every route kept: at most this share of their
# length within OVERLAP_BUFFER_DEG (~1 km) of another route...
MAX_OVERLAP = 0.7
OVERLAP_BUFFER_DEG = 0.01
# ...and take at most this many times as long as the fastest route.
MAX_SLOWDOWN = 3
# Detours pass through a point this far (as a share of the trip's straight-line
# length) to the side of the line's midpoint, nearest first.
DETOUR_OFFSETS = (0.15, -0.15, 0.3, -0.3)


# A route end: (lat, lon) coordinates, or an address/place name Google geocodes.
Waypoint = tuple[float, float] | str


@dataclass(frozen=True)
class Route:
    distance_m: int
    duration_s: int
    points: list[tuple[float, float]]  # (lat, lon), departure first
    description: str = ""  # main roads, e.g. "I-80 E"
    source: str = "google"  # "google", or the fallback: "avoid_highways" / "detour"

    def display_points(self) -> list[tuple[float, float]]:
        """The route simplified for drawing: a cross-country route has ~17,000 points."""
        if len(self.points) < 3:
            return self.points
        simplified = LineString(self.points).simplify(DISPLAY_TOLERANCE)
        return [
            (round(lat, DISPLAY_DECIMALS), round(lon, DISPLAY_DECIMALS))
            for lat, lon in simplified.coords
        ]


def compute_routes(origin: Waypoint, destination: Waypoint) -> list[Route]:
    """Driving routes from origin to destination: Google's (fastest first), then
    fallbacks to make MAX_ROUTES when Google has fewer and different ones exist."""
    if not settings.GOOGLE_ROUTES_API_KEY:
        raise UpstreamError("GOOGLE_ROUTES_API_KEY is not configured")

    routes = _request(origin, destination, computeAlternativeRoutes=True)[:MAX_ROUTES]
    # An empty response (no "routes" key) means there is no drivable route.
    if not routes:
        raise DomainError("No driving route between these places")
    if len(routes) < MAX_ROUTES:
        routes += _fallbacks(origin, destination, routes)
    return routes


def _request(origin: Waypoint, destination: Waypoint, source="google", **options) -> list[Route]:
    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        **options,
    }
    request = urllib.request.Request(
        ROUTES_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.GOOGLE_ROUTES_API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise UpstreamError("Routes API request failed", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpstreamError("Routes API is unreachable") from exc

    return [
        Route(
            distance_m=route.get("distanceMeters", 0),
            duration_s=int(route.get("duration", "0s").rstrip("s")),
            points=decode_polyline(route["polyline"]["encodedPolyline"]),
            description=route.get("description", ""),
            source=source,
        )
        for route in data.get("routes", [])
    ]


def _fallbacks(origin: Waypoint, destination: Waypoint, routes: list[Route]) -> list[Route]:
    """Extra routes, up to MAX_ROUTES in all, that differ from `routes` and each other.
    Candidates are requested in parallel; a failed one is skipped."""
    start, end = routes[0].points[0], routes[0].points[-1]
    candidates = [{"source": "avoid_highways", "routeModifiers": {"avoidHighways": True}}]
    candidates += [
        {
            "source": "detour",
            "intermediates": [
                {"location": _waypoint(_side_point(start, end, k))["location"], "via": True}
            ],
        }
        for k in DETOUR_OFFSETS
    ]

    def fetch(options):
        try:
            return _request(origin, destination, **options)[:1]
        except DomainError:  # UpstreamError included: a fallback is optional
            return []

    with ThreadPoolExecutor(len(candidates)) as pool:
        results = list(pool.map(fetch, candidates))

    kept = list(routes)
    fastest = min(route.duration_s for route in routes)
    for route in (route for result in results for route in result):
        if len(kept) == MAX_ROUTES:
            break
        if route.duration_s <= MAX_SLOWDOWN * fastest and all(
            _overlap(route, other) <= MAX_OVERLAP for other in kept
        ):
            kept.append(route)
    return kept[len(routes) :]


def _side_point(
    start: tuple[float, float], end: tuple[float, float], k: float
) -> tuple[float, float]:
    """The point `k` trip-lengths to the left of the start-end line's midpoint
    (right for negative k), measured in locally scaled degrees."""
    scale = math.cos(math.radians((start[0] + end[0]) / 2))  # lon degrees are shorter
    dx, dy = (end[1] - start[1]) * scale, end[0] - start[0]
    mid_lat, mid_lon = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    return mid_lat + k * dx, mid_lon - k * dy / scale


def _overlap(route: Route, other: Route) -> float:
    """Share of `route`'s length that runs along `other` (within OVERLAP_BUFFER_DEG)."""
    line = LineString([(lon, lat) for lat, lon in route.points])
    along = LineString([(lon, lat) for lat, lon in other.points]).buffer(OVERLAP_BUFFER_DEG)
    return line.intersection(along).length / line.length if line.length else 1.0


def _waypoint(point: Waypoint) -> dict:
    if isinstance(point, str):
        return {"address": point}
    lat, lon = point
    return {"location": {"latLng": {"latitude": lat, "longitude": lon}}}


def decode_polyline(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    """Decode Google's encoded polyline format into (lat, lon) pairs.

    Each coordinate is a delta from the previous one, zigzag-encoded and split
    into 5-bit chunks offset by 63 (see Google's "Encoded Polyline Algorithm").
    """
    factor = 10**precision
    points: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / factor, lon / factor))
    return points

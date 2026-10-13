"""
Driving routes between two points, via the Google Routes API (computeRoutes).

Google's routes come first (fastest first); when it has fewer than MAX_ROUTES,
fallback candidates are requested in parallel and the distinct ones kept (see
business/route.py). Each route's geometry comes back as an encoded polyline; we
decode it to a list of (lat, lon) points, which later steps (counties, weather)
walk along.
"""

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

from apps.core.exceptions import DomainError, UpstreamError

from ..business.route import DETOUR_OFFSETS, MAX_ROUTES, keep_distinct, side_point
from ..domain.route import Point, Route, Step, Waypoint

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join(
    f"routes.{field}"
    for field in (
        "distanceMeters",
        "duration",
        "polyline.encodedPolyline",
        "description",
        # Per-step distance and time: the speed profile for travel times (timing.py).
        "legs.steps.distanceMeters",
        "legs.steps.staticDuration",
    )
)
TIMEOUT_SECONDS = 10


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
            steps=tuple(
                Step(
                    step.get("distanceMeters", 0), int(step.get("staticDuration", "0s").rstrip("s"))
                )
                for leg in route.get("legs", [])
                for step in leg.get("steps", [])
            ),
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
                {"location": _waypoint(side_point(start, end, k))["location"], "via": True}
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
    return keep_distinct(routes, [route for result in results for route in result])


def _waypoint(point: Waypoint) -> dict:
    if isinstance(point, str):
        return {"address": point}
    lat, lon = point
    return {"location": {"latLng": {"latitude": lat, "longitude": lon}}}


def decode_polyline(encoded: str, precision: int = 5) -> list[Point]:
    """Decode Google's encoded polyline format into (lat, lon) pairs.

    Each coordinate is a delta from the previous one, zigzag-encoded and split
    into 5-bit chunks offset by 63 (see Google's "Encoded Polyline Algorithm").
    """
    factor = 10**precision
    points: list[Point] = []
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
        points.append(Point(lat / factor, lon / factor))
    return points

"""
Driving route between two points, via the Google Routes API (computeRoutes).

The route geometry comes back as an encoded polyline; we decode it to a list of
(lat, lon) points, which later steps (counties, weather) walk along.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

from apps.core.exceptions import DomainError, UpstreamError

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Route:
    distance_m: int
    duration_s: int
    points: list[tuple[float, float]]  # (lat, lon), departure first


def compute_route(origin: tuple[float, float], destination: tuple[float, float]) -> Route:
    """Fastest driving route from origin to destination, both (lat, lon)."""
    if not settings.GOOGLE_ROUTES_API_KEY:
        raise UpstreamError("GOOGLE_ROUTES_API_KEY is not configured")

    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
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

    # An empty response (no "routes" key) means there is no drivable route.
    if not data.get("routes"):
        raise DomainError("No driving route between these places")
    route = data["routes"][0]
    return Route(
        distance_m=route.get("distanceMeters", 0),
        duration_s=int(route.get("duration", "0s").rstrip("s")),
        points=decode_polyline(route["polyline"]["encodedPolyline"]),
    )


def _waypoint(point: tuple[float, float]) -> dict:
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

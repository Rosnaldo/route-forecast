"""
Route geometry, and the rules for which fallback routes are worth offering next
to Google's.

Google returns the fastest route plus up to two alternatives when there are
reasonable ones; a trip with a single sensible road gets one route. To still offer
MAX_ROUTES options, the routing service asks for fallback routes (avoiding highways,
or passing through a point off to one side of the direct line, see side_point) and
keeps the ones that are really different and not absurdly long (keep_distinct).
"""

import itertools
import math

from shapely import LineString

from ..domain.route import Point, Route

EARTH_RADIUS_M = 6_371_008.8

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


def length_m(route: Route) -> float:
    """Length along the route's points (great-circle), which travel times are based on."""
    return sum(haversine_m(*a, *b) for a, b in itertools.pairwise(route.points))


def display_points(route: Route) -> list[Point]:
    """The route simplified for drawing: a cross-country route has ~17,000 points."""
    if len(route.points) < 3:
        return route.points
    simplified = LineString(route.points).simplify(DISPLAY_TOLERANCE)
    return [
        Point(round(lat, DISPLAY_DECIMALS), round(lon, DISPLAY_DECIMALS))
        for lat, lon in simplified.coords
    ]


def keep_distinct(routes: list[Route], candidates: list[Route]) -> list[Route]:
    """The candidates worth adding to `routes`, in order, up to MAX_ROUTES in all: each
    at most MAX_SLOWDOWN times as slow as the fastest route and different enough
    (MAX_OVERLAP) from every route kept."""
    kept = list(routes)
    fastest = min(route.duration_s for route in routes)
    for route in candidates:
        if len(kept) == MAX_ROUTES:
            break
        if route.duration_s <= MAX_SLOWDOWN * fastest and all(
            overlap(route, other) <= MAX_OVERLAP for other in kept
        ):
            kept.append(route)
    return kept[len(routes) :]


def side_point(start: Point, end: Point, k: float) -> Point:
    """The point `k` trip-lengths to the left of the start-end line's midpoint
    (right for negative k), measured in locally scaled degrees."""
    scale = math.cos(math.radians((start[0] + end[0]) / 2))  # lon degrees are shorter
    dx, dy = (end[1] - start[1]) * scale, end[0] - start[0]
    mid_lat, mid_lon = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    return Point(mid_lat + k * dx, mid_lon - k * dy / scale)


def overlap(route: Route, other: Route) -> float:
    """Share of `route`'s length that runs along `other` (within OVERLAP_BUFFER_DEG)."""
    line = LineString([(lon, lat) for lat, lon in route.points])
    along = LineString([(lon, lat) for lat, lon in other.points]).buffer(OVERLAP_BUFFER_DEG)
    return line.intersection(along).length / line.length if line.length else 1.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

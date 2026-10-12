"""
Which US counties a route passes through, in travel order.

County outlines come from the Census cartographic boundary file committed in
data/ (refresh it about once a year; boundaries rarely change). They are loaded
into memory once per process, with an STRtree spatial index so a lookup only
runs exact geometry checks on counties whose bounding box touches the route.
"""

from dataclasses import dataclass
from functools import cache

import shapefile
import shapely
from django.conf import settings
from shapely import LineString, Point, STRtree
from shapely.geometry import shape

COUNTIES_FILE = settings.BASE_DIR / "data" / "cb_2024_us_county_500k.zip"


@dataclass(frozen=True)
class County:
    fips: str  # 5-digit state+county code, e.g. "08031"
    name: str
    state: str  # USPS abbreviation, e.g. "CO"


@cache
def _index() -> tuple[STRtree, list, list[County]]:
    """Load every county outline and build the spatial index (first call only)."""
    geometries, counties = [], []
    with shapefile.Reader(str(COUNTIES_FILE)) as reader:
        for record in reader.iterShapeRecords():
            geometries.append(shape(record.shape.__geo_interface__))
            counties.append(County(record.record.GEOID, record.record.NAME, record.record.STUSPS))
    return STRtree(geometries), geometries, counties


def counties_along(points: list[tuple[float, float]]) -> list[County]:
    """Counties crossed by the route through `points` ((lat, lon) pairs), in order."""
    if not points:
        return []
    tree, geometries, counties = _index()

    # Shapely works in (x, y) = (lon, lat).
    coords = [(lon, lat) for lat, lon in points]
    if len(coords) == 1:
        return [counties[i] for i in tree.query(Point(coords[0]), predicate="intersects")]
    route = LineString(coords)

    entries = []
    for i in tree.query(route, predicate="intersects"):
        inside = route.intersection(geometries[i])
        if inside.length == 0:  # only touches the border, never enters
            continue
        # Distance from departure to where the route first enters this county.
        entered_at = min(
            route.project(Point(part.coords[end]))
            for part in shapely.get_parts(inside)
            if part.length > 0
            for end in (0, -1)
        )
        entries.append((entered_at, counties[i]))
    return [county for _, county in sorted(entries, key=lambda entry: entry[0])]

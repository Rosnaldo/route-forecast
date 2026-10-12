"""
Which US counties a route passes through, in travel order.

County outlines come from the Census cartographic boundary file committed in
data/ (refresh it about once a year; boundaries rarely change). They are loaded
into memory once per process, with an STRtree spatial index so a lookup only
runs exact geometry checks on counties whose bounding box touches the route.
"""

from dataclasses import dataclass, field
from functools import cache

import shapefile
import shapely
from django.conf import settings
from shapely import LineString, Point, STRtree
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

COUNTIES_FILE = settings.BASE_DIR / "data" / "cb_2024_us_county_500k.zip"
# Outline detail sent to the map: ~500 m simplification, ~10 m coordinate grid.
DISPLAY_TOLERANCE = 0.005
DISPLAY_GRID = 0.0001


@dataclass(frozen=True)
class County:
    fips: str  # 5-digit state+county code, e.g. "08031"
    name: str
    state: str  # USPS abbreviation, e.g. "CO"
    geometry: BaseGeometry | None = field(default=None, compare=False, repr=False)

    def outline(self) -> dict | None:
        """Simplified GeoJSON geometry, small enough to draw on a map."""
        if self.geometry is None:
            return None
        simplified = self.geometry.simplify(DISPLAY_TOLERANCE)
        return mapping(shapely.set_precision(simplified, DISPLAY_GRID))


@cache
def _index() -> tuple[STRtree, list[County]]:
    """Load every county outline and build the spatial index (first call only)."""
    counties = []
    with shapefile.Reader(str(COUNTIES_FILE)) as reader:
        for record in reader.iterShapeRecords():
            geometry = shape(record.shape.__geo_interface__)
            r = record.record
            counties.append(County(r.GEOID, r.NAME, r.STUSPS, geometry))
    return STRtree([county.geometry for county in counties]), counties


def counties_along(points: list[tuple[float, float]]) -> list[County]:
    """Counties crossed by the route through `points` ((lat, lon) pairs), in order."""
    if not points:
        return []
    tree, counties = _index()

    # Shapely works in (x, y) = (lon, lat).
    coords = [(lon, lat) for lat, lon in points]
    if len(coords) == 1:
        return [counties[i] for i in tree.query(Point(coords[0]), predicate="intersects")]
    route = LineString(coords)

    entries = []
    for i in tree.query(route, predicate="intersects"):
        inside = route.intersection(counties[i].geometry)
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

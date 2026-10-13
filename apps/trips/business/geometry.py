"""Outlines sent to the map: county and grid cell shapes, simplified."""

import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

# Outline detail sent to the map: ~500 m simplification, ~10 m coordinate grid.
DISPLAY_TOLERANCE = 0.005
DISPLAY_GRID = 0.0001


def outline(geometry: BaseGeometry | None) -> dict | None:
    """Simplified GeoJSON geometry, small enough to draw on a map."""
    if geometry is None:
        return None
    simplified = geometry.simplify(DISPLAY_TOLERANCE)
    return mapping(shapely.set_precision(simplified, DISPLAY_GRID))

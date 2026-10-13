"""A US county: what the map draws, and the weather grid is clipped to."""

from dataclasses import dataclass, field

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class County:
    fips: str  # 5-digit state+county code, e.g. "08031"
    name: str
    state: str  # USPS abbreviation, e.g. "CO"
    geometry: BaseGeometry | None = field(default=None, compare=False, repr=False)

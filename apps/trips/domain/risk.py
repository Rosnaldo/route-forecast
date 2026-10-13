"""Risk levels, the weather conditions they are read from, and the shape of the rules
that map one to the other (the rules themselves: business/risk.py)."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class RiskLevel(IntEnum):
    """Ordered, so levels compare and max() gives the worst one."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


class Condition(StrEnum):
    WIND = "wind"
    RAIN = "rain"
    SNOW = "snow"


@dataclass(frozen=True)
class Threshold:
    level: RiskLevel
    value: float
    exclusive: bool = False  # True: the level needs value > bound, not >=


@dataclass(frozen=True)
class Rule:
    condition: Condition
    unit: str
    thresholds: tuple[Threshold, ...]  # ascending; below the first one is Low


@dataclass(frozen=True)
class WindLoadRule:
    """Wind from `from_mph` up to (not including) `to_mph`, with cargo over `over_lb`,
    is at least `level`."""

    over_lb: int
    from_mph: float
    to_mph: float
    level: RiskLevel

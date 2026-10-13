"""
Driving-risk rules: thresholds that turn a weather value into a risk level.

Each condition lists the value at which every level above Low starts. Ranges
are read "from this value up" (rain 0.25 in/hr is High, not Moderate); a bound
marked exclusive needs the value to be strictly above it (rain > 1.00 in/hr
is No Travel, exactly 1.00 is Severe), matching the source table:

    Condition  Low          Moderate    High        Severe      No Travel
    Wind       <25 mph      25-34       35-44       45-54       >=55 mph
    Rain       <0.10 in/hr  0.10-0.25   0.25-0.50   0.50-1.00   >1.00
    Snow       <0.5 in/hr   0.5-1.0     1.0-2.0     2.0-3.0     >3.0

Cargo weight then raises the wind level (see WIND_LOAD_RULES):

    Wind        Cargo weight    Level
    >= 55 mph   any             No Travel
    45-54 mph   > 30,000 lb     No Travel
    35-44 mph   > 40,000 lb     Severe
"""

from ..domain.risk import Condition, RiskLevel, Rule, Threshold, WindLoadRule
from ..domain.weather import Forecast

RULES: dict[Condition, Rule] = {
    rule.condition: rule
    for rule in (
        Rule(
            Condition.WIND,
            "mph",
            (
                Threshold(RiskLevel.MODERATE, 25),
                Threshold(RiskLevel.HIGH, 35),
                Threshold(RiskLevel.SEVERE, 45),
                Threshold(RiskLevel.NO_TRAVEL, 55),
            ),
        ),
        Rule(
            Condition.RAIN,
            "in/hr",
            (
                Threshold(RiskLevel.MODERATE, 0.10),
                Threshold(RiskLevel.HIGH, 0.25),
                Threshold(RiskLevel.SEVERE, 0.50),
                Threshold(RiskLevel.NO_TRAVEL, 1.00, exclusive=True),
            ),
        ),
        Rule(
            Condition.SNOW,
            "in/hr",
            (
                Threshold(RiskLevel.MODERATE, 0.5),
                Threshold(RiskLevel.HIGH, 1.0),
                Threshold(RiskLevel.SEVERE, 2.0),
                Threshold(RiskLevel.NO_TRAVEL, 3.0, exclusive=True),
            ),
        ),
    )
}


# Heavier loads raise the wind level. >= 55 mph is already No Travel for any load.
WIND_LOAD_RULES = (
    WindLoadRule(over_lb=30_000, from_mph=45, to_mph=55, level=RiskLevel.NO_TRAVEL),
    WindLoadRule(over_lb=40_000, from_mph=35, to_mph=45, level=RiskLevel.SEVERE),
)


def classify(condition: Condition, value: float, weight_lb: float = 0) -> RiskLevel:
    """Risk level for one condition and cargo weight.

    classify(Condition.WIND, 40) -> HIGH; classify(Condition.WIND, 40, 45_000) -> SEVERE.
    """
    level = _rule_level(RULES[condition], value)
    if condition is Condition.WIND:
        for rule in WIND_LOAD_RULES:
            if weight_lb > rule.over_lb and rule.from_mph <= value < rule.to_mph:
                level = max(level, rule.level)
    return level


def overall(values: dict[Condition, float], weight_lb: float = 0) -> RiskLevel:
    """Worst level across conditions: 30 mph wind + 1.5 in/hr snow -> HIGH."""
    return max((classify(c, v, weight_lb) for c, v in values.items()), default=RiskLevel.LOW)


def risk_label(level: RiskLevel) -> str:
    """The level's name for people: NO_TRAVEL -> "No Travel"."""
    return level.name.replace("_", " ").title()


def forecast_level(forecast: Forecast, weight_lb: float = 0) -> RiskLevel:
    """Risk level of an hour's forecast for the cargo weight."""
    return overall(
        {
            Condition.WIND: forecast.wind_mph,
            Condition.RAIN: forecast.rain_in_hr,
            Condition.SNOW: forecast.snow_in_hr,
        },
        weight_lb,
    )


def _rule_level(rule: Rule, value: float) -> RiskLevel:
    """The highest threshold `value` reaches; Low below the first one."""
    level = RiskLevel.LOW
    for threshold in rule.thresholds:
        reached = value > threshold.value if threshold.exclusive else value >= threshold.value
        if not reached:
            break
        level = threshold.level
    return level

"""
Input validation for the trip endpoints: request bodies and path parameters.

Every request serializer is strict: a field it does not declare is an error, so a
typo (`lng`, `weight`) is reported instead of silently ignored. Numbers must be
finite JSON numbers (or numeric strings); true/false are refused, which Python
would otherwise read as 1/0.
"""

import time
from collections.abc import Mapping

from django.core.validators import RegexValidator
from rest_framework import serializers

from ..business.weather import FORECAST_HOURS

WEIGHT_MIN_LB = 1_000  # cargo weight accepted by the route endpoint
WEIGHT_MAX_LB = 100_000
ADDRESS_MIN_LENGTH = 2
ADDRESS_MAX_LENGTH = 200
CHECKPOINT_GAPS_MI = (10, 25, 50)
# An hour of slack before now: the form computes the departure from when the routes
# loaded, which may be a while ago.
DEPARTURE_SLACK_S = 3600

# Trip ids are uuid4().hex (services/trip_store.py).
validate_trip_id = RegexValidator(
    r"^[0-9a-f]{32}\Z", "Not a valid trip id: 32 lowercase hexadecimal digits.", code="invalid"
)


def validate_printable(value: str) -> str:
    if not value.isprintable():
        raise serializers.ValidationError("Must not contain control characters.")
    return value


class StrictSerializer(serializers.Serializer):
    """Refuses fields it does not declare."""

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and (unknown := data.keys() - self.fields.keys()):
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class NumberField(serializers.FloatField):
    """A finite number (FloatField already refuses NaN and infinity), not a boolean."""

    def to_internal_value(self, data):
        if isinstance(data, bool):
            self.fail("invalid")
        return super().to_internal_value(data)


class PointSerializer(StrictSerializer):
    """Either coordinates ({lat, lon}) or a place name Google can geocode ({address})."""

    lat = NumberField(min_value=-90, max_value=90, required=False)
    lon = NumberField(min_value=-180, max_value=180, required=False)
    address = serializers.CharField(
        min_length=ADDRESS_MIN_LENGTH,
        max_length=ADDRESS_MAX_LENGTH,
        validators=[validate_printable],
        required=False,
    )

    def to_internal_value(self, data):
        """Return (lat, lon) or the address string, as compute_routes expects."""
        attrs = super().to_internal_value(data)
        if "address" in attrs and not ({"lat", "lon"} & attrs.keys()):
            return attrs["address"]
        if {"lat", "lon"} <= attrs.keys() and "address" not in attrs:
            return attrs["lat"], attrs["lon"]
        raise serializers.ValidationError("Give either lat and lon, or address.")


def _same_place(a, b) -> bool:
    """The same coordinates, or the same address ignoring case and spacing."""
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.casefold().split()) == " ".join(b.casefold().split())
    return a == b


class RouteRequestSerializer(StrictSerializer):
    departure = PointSerializer()
    arrival = PointSerializer()
    weight_lb = NumberField(min_value=WEIGHT_MIN_LB, max_value=WEIGHT_MAX_LB)

    def validate(self, attrs):
        if _same_place(attrs["departure"], attrs["arrival"]):
            raise serializers.ValidationError({"arrival": "Arrival must differ from departure."})
        return attrs


class TripDepartureSerializer(StrictSerializer):
    trip_id = serializers.CharField(validators=[validate_trip_id])  # from the route endpoint
    departure = serializers.DateTimeField()  # within the forecast window

    def validate_departure(self, value):
        now = time.time()
        if not now - DEPARTURE_SLACK_S <= value.timestamp() <= now + FORECAST_HOURS * 3600:
            raise serializers.ValidationError(
                f"Departure must be within the next {FORECAST_HOURS} hours."
            )
        return value


class CheckpointsRequestSerializer(TripDepartureSerializer):
    distance_mi = serializers.ChoiceField(choices=CHECKPOINT_GAPS_MI)  # between checkpoints

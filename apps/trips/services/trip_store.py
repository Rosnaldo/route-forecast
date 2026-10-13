"""Computed trips, kept in the cache so later requests need no new routing."""

import uuid

from django.core.cache import cache

from apps.core.exceptions import NotFoundError

from ..domain.trip import Trip

TRIP_CACHE_SECONDS = 60 * 60  # how long a computed trip can get checkpoints


def save_trip(trip: Trip) -> str:
    """Keep a trip for TRIP_CACHE_SECONDS; returns its id (32 lowercase hex digits)."""
    trip_id = uuid.uuid4().hex
    cache.set(_trip_key(trip_id), trip, TRIP_CACHE_SECONDS)
    return trip_id


def update_trip(trip_id: str, trip: Trip) -> None:
    """Store a changed trip under its id (its lifetime restarts)."""
    cache.set(_trip_key(trip_id), trip, TRIP_CACHE_SECONDS)


def load_trip(trip_id: str) -> Trip:
    trip = cache.get(_trip_key(trip_id))
    if trip is None:
        raise NotFoundError("Trip not found or expired; submit the route again")
    return trip


def _trip_key(trip_id: str) -> str:
    # v4: the grid is added after the routes; trips saved before that are not found.
    return f"trip:v4:{trip_id}"

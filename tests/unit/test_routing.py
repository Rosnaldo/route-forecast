from unittest import mock

import pytest

from apps.core.exceptions import UpstreamError
from apps.trips.routing import MAX_ROUTES, Route, _overlap, _side_point, compute_routes

# Routes from (0, 0) to (0, 1), (lat, lon): straight east, and bowing north or south.
MAIN = Route(100_000, 3600, [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)], "Main")
NORTH = Route(120_000, 4000, [(0.0, 0.0), (0.3, 0.5), (0.0, 1.0)], "North")
SOUTH = Route(120_000, 4000, [(0.0, 0.0), (-0.3, 0.5), (0.0, 1.0)], "South")
FAR_NORTH = Route(150_000, 5000, [(0.0, 0.0), (0.6, 0.5), (0.0, 1.0)], "Far north")


@pytest.fixture(autouse=True)
def _routes_key(settings):
    settings.GOOGLE_ROUTES_API_KEY = "test-key"


def fake_google(main, fallbacks):
    """Main request -> `main`; fallback n (in request order) -> fallbacks[n] (a route,
    None for no route, or an exception)."""
    calls = []

    def request(origin, destination, source="google", **options):
        calls.append((source, options))
        if source == "google":
            return main
        answer = fallbacks[len(calls) - 2] if len(calls) - 2 < len(fallbacks) else None
        if isinstance(answer, Exception):
            raise answer
        return [Route(**{**vars(answer), "source": source})] if answer else []

    return mock.patch("apps.trips.routing._request", side_effect=request), calls


def test_three_google_routes_need_no_fallback():
    patch, calls = fake_google([MAIN, NORTH, SOUTH], [])
    with patch:
        routes = compute_routes("A", "B")
    assert [r.description for r in routes] == ["Main", "North", "South"]
    assert len(calls) == 1
    assert calls[0][1] == {"computeAlternativeRoutes": True}


def test_fallbacks_fill_up_to_three():
    # avoid highways -> same road (rejected), detours -> north, north again, south.
    patch, calls = fake_google([MAIN], [MAIN, NORTH, NORTH, SOUTH])
    with patch:
        routes = compute_routes("A", "B")
    assert [(r.description, r.source) for r in routes] == [
        ("Main", "google"),
        ("North", "detour"),
        ("South", "detour"),
    ]
    assert len(routes) == MAX_ROUTES
    sources = [source for source, _ in calls[1:]]
    assert sources == ["avoid_highways"] + ["detour"] * 4
    assert calls[1][1]["routeModifiers"] == {"avoidHighways": True}
    (via,) = calls[2][1]["intermediates"]
    assert via["via"] is True
    assert via["location"]["latLng"] == pytest.approx({"latitude": 0.15, "longitude": 0.5})


def test_fallbacks_skip_too_slow_and_failed_requests():
    slow = Route(**{**vars(FAR_NORTH), "duration_s": 3 * 3600 + 1})  # > 3x the fastest
    patch, _ = fake_google([MAIN], [UpstreamError("down"), slow, None, SOUTH, FAR_NORTH])
    with patch:
        routes = compute_routes("A", "B")
    assert [r.description for r in routes] == ["Main", "South", "Far north"]


def test_fewer_than_three_when_nothing_different_exists():
    patch, _ = fake_google([MAIN], [MAIN, MAIN, None, MAIN, None])
    with patch:
        assert [r.description for r in compute_routes("A", "B")] == ["Main"]


def test_no_route_found_skips_fallbacks():
    patch, calls = fake_google([], [])
    with patch, pytest.raises(Exception, match="No driving route"):
        compute_routes("A", "B")
    assert len(calls) == 1


def test_side_point_is_left_of_the_direction_of_travel():
    # Heading east along the equator: left is north.
    assert _side_point((0.0, 0.0), (0.0, 1.0), 0.15) == pytest.approx((0.15, 0.5))
    assert _side_point((0.0, 0.0), (0.0, 1.0), -0.3) == pytest.approx((-0.3, 0.5))


def test_overlap():
    assert _overlap(MAIN, MAIN) == pytest.approx(1)
    assert _overlap(NORTH, MAIN) < 0.1

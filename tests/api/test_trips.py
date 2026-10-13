import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from apps.trips import checkpoints as checkpoints_module
from apps.trips.checkpoints import Trip, load_trip, save_trip
from apps.trips.counties import County, counties_along
from apps.trips.routing import Point, Route, Step, decode_polyline
from apps.trips.weather import Forecast, WeatherGrid

URL = "/api/v1/trips/route/"
DENVER = {"lat": 39.7392, "lon": -104.9903}
VAIL = {"lat": 39.6403, "lon": -106.3742}

# Example from Google's polyline documentation.
ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
DECODED = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


@pytest.fixture(autouse=True)
def _routes_key(settings):
    settings.GOOGLE_ROUTES_API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _no_weather():
    """The weather grid has its own tests (unit/test_weather.py); keep these offline."""

    def grid(routes, weight_lb):
        return WeatherGrid(
            1_800_000_000, 1_799_998_400, weight_lb, 0.2, [], [], [[] for _ in routes]
        )

    with mock.patch("apps.trips.views.weather_grid", side_effect=grid) as weather:
        yield weather


def fake_urlopen(payload):
    """Every Routes API call (the main one and any fallbacks) gets `payload`."""
    return mock.patch(
        "apps.trips.routing.urllib.request.urlopen",
        side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()),
    )


def test_decode_polyline():
    points = decode_polyline(ENCODED)
    assert points == DECODED
    assert points[0].lat == 38.5 and points[0].lon == -120.2


def test_route(api_client, _no_weather):
    payload = {
        "routes": [
            {
                "distanceMeters": 158000,
                "duration": "6300s",
                "polyline": {"encodedPolyline": ENCODED},
                "description": "I-70 W",
                "legs": [
                    {
                        "steps": [
                            {"distanceMeters": 1000, "staticDuration": "120s"},
                            {"distanceMeters": 157000, "staticDuration": "6180s"},
                        ]
                    }
                ],
            },
            {
                "distanceMeters": 170000,
                "duration": "7200s",
                "polyline": {"encodedPolyline": ENCODED[:10]},  # just its first point
                "description": "US-6 W",
            },
        ]
    }
    denver = County("08031", "Denver", "CO")
    jefferson = County("08059", "Jefferson", "CO")
    with (
        fake_urlopen(payload) as urlopen,
        # Routes are looked up in parallel: answer by route (point count), not call order.
        mock.patch(
            "apps.trips.views.counties_along",
            side_effect=lambda points: [denver] if len(points) == 3 else [denver, jefferson],
        ) as counties,
    ):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})

    assert response.status_code == 200
    body = response.json()
    # The trip is kept for the checkpoints endpoint.
    trip = load_trip(body["trip_id"])
    assert [r.description for r in trip.routes] == ["I-70 W", "US-6 W"]
    assert (trip.weight_lb, trip.step) == (20_000, 0.2)
    assert trip.routes[0].steps == (Step(1000, 120), Step(157000, 6180))  # for travel times
    assert isinstance(trip.routes[0].points[0], Point)
    assert trip.routes[1].steps == ()
    assert [
        (r["description"], r["distance_m"], r["duration_s"], r["counties"]) for r in body["routes"]
    ] == [
        ("I-70 W", 158000, 6300, ["08031"]),
        ("US-6 W", 170000, 7200, ["08031", "08059"]),
    ]
    assert body["routes"][0]["points"] == [list(p) for p in DECODED]
    assert body["routes"][0]["cells"] == []
    # Counties crossed by any route, each once.
    assert [c["fips"] for c in body["counties"]] == ["08031", "08059"]
    assert body["weather"] == {
        "now": 1_800_000_000,
        "start": 1_799_998_400,
        "hours": 48,
        "weight_lb": 20_000,
        "points": [],
        "cells": [],
    }
    assert counties.call_count == 2
    routes, weight = _no_weather.call_args.args
    assert [route_counties for _, route_counties in routes] == [[denver], [denver, jefferson]]
    assert weight == 20_000
    sent = json.loads(urlopen.call_args_list[0].args[0].data)  # the main request
    assert sent["origin"]["location"]["latLng"] == {"latitude": 39.7392, "longitude": -104.9903}
    assert sent["travelMode"] == "DRIVE"
    assert sent["computeAlternativeRoutes"] is True


def test_display_points_are_simplified():
    straight = Route(1, 1, [Point(39.0, -105.0 + i * 0.001) for i in range(1000)])
    assert straight.display_points() == [(39.0, -105.0), (39.0, -104.001)]
    assert Route(1, 1, DECODED[:2]).display_points() == DECODED[:2]


def test_route_from_addresses(api_client):
    payload = {"routes": [{"distanceMeters": 1, "polyline": {"encodedPolyline": ENCODED}}]}
    with fake_urlopen(payload) as urlopen:
        response = api_client.post(
            URL,
            {
                "departure": {"address": "Denver, CO"},
                "arrival": {"address": "Vail, CO"},
                "weight_lb": 20_000,
            },
        )
    assert response.status_code == 200
    sent = json.loads(urlopen.call_args_list[0].args[0].data)  # the main request
    assert sent["origin"] == {"address": "Denver, CO"}
    assert sent["destination"] == {"address": "Vail, CO"}


@pytest.mark.parametrize(
    "point",
    [{}, {"lat": 39.7}, {"lat": 39.7, "lon": -105.0, "address": "Denver, CO"}, {"address": ""}],
)
def test_point_needs_coordinates_or_address(api_client, point):
    response = api_client.post(URL, {"departure": point, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 400
    assert "departure" in response.json()


def test_large_responses_are_gzipped(api_client):
    response = api_client.get("/api/v1/trips/examples/", HTTP_ACCEPT_ENCODING="gzip")
    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"


def test_checkpoints_and_recommendation_share_the_risk_calculation(api_client):
    trip_id = save_trip(
        Trip([Route(111_195, 7200, [Point(0.0, 0.0), Point(0.0, 1.0)])], 20_000, 0.2)
    )
    hours = [Forecast(12, 0, 0)] * 49
    body = checkpoints_body(trip_id)
    with (
        mock.patch(
            "apps.trips.checkpoints.hourly_forecasts",
            side_effect=lambda centers, start: dict.fromkeys(centers, hours),
        ),
        mock.patch(
            "apps.trips.checkpoints.route_risks", wraps=checkpoints_module.route_risks
        ) as risks,
    ):
        assert api_client.post(CHECKPOINTS_URL, body, format="json").status_code == 200
        del body["distance_mi"]
        assert api_client.post(RECOMMENDATION_URL, body, format="json").status_code == 200
    assert risks.call_count == 1  # computed for checkpoints, reused by the recommendation


def test_example_routes(api_client):
    response = api_client.get("/api/v1/trips/examples/")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 11
    assert rows[0] | {"purpose": None} == {
        "id": 1,
        "departure": "Denver, CO",
        "arrival": "Vail, CO",
        "distance_km": 160,
        "purpose": None,
    }


def test_no_route_found(api_client):
    with fake_urlopen({}):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 400
    assert response.json()["code"] == "domain_error"


def test_google_error_is_bad_gateway(api_client):
    error = urllib.error.HTTPError(URL, 403, "Forbidden", {}, None)
    with mock.patch("apps.trips.routing.urllib.request.urlopen", side_effect=error):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 502
    assert response.json() == {"code": "upstream_error", "detail": mock.ANY, "status": 403}


def test_missing_key_is_bad_gateway(api_client, settings):
    settings.GOOGLE_ROUTES_API_KEY = ""
    response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 502


@pytest.mark.parametrize("weight", [None, 999, 100_001, "heavy"])
def test_weight_is_required_and_in_range(api_client, weight):
    body = {"departure": DENVER, "arrival": VAIL}
    if weight is not None:
        body["weight_lb"] = weight
    response = api_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert "weight_lb" in response.json()


def test_invalid_coordinates(api_client):
    response = api_client.post(
        URL, {"departure": {"lat": 200, "lon": 0}, "arrival": VAIL, "weight_lb": 20_000}
    )
    assert response.status_code == 400


# Hand-made path along I-70 from Denver to Vail, (lat, lon).
I70 = [
    (39.7392, -104.9903),
    (39.7400, -105.2100),
    (39.7425, -105.5136),
    (39.7060, -105.6970),
    (39.6800, -105.9200),
    (39.6300, -106.0700),
    (39.5740, -106.0970),
    (39.5000, -106.1500),
    (39.5300, -106.2200),
    (39.6403, -106.3742),
]


def test_counties_along_in_travel_order():
    names = [c.name for c in counties_along(I70)]
    assert names == ["Denver", "Jefferson", "Clear Creek", "Summit", "Eagle"]
    assert [c.name for c in counties_along(I70[::-1])] == names[::-1]


def test_counties_along_single_point():
    assert counties_along([(39.7392, -104.9903)]) == [County("08031", "Denver", "CO")]


def test_counties_along_empty_and_offshore():
    assert counties_along([]) == []
    assert counties_along([(30.0, -40.0), (31.0, -41.0)]) == []  # mid-Atlantic


def test_county_outline_is_simplified_geojson():
    (denver,) = counties_along([(39.7392, -104.9903)])
    outline = denver.outline()
    assert outline["type"] in ("Polygon", "MultiPolygon")
    assert len(str(outline)) < len(str(denver.geometry.__geo_interface__))


CHECKPOINTS_URL = "/api/v1/trips/checkpoints/"


def checkpoints_body(trip_id, **overrides):
    departure = datetime.now(UTC) + timedelta(hours=2)
    return {"trip_id": trip_id, "distance_mi": 25, "departure": departure.isoformat()} | overrides


def test_checkpoints(api_client):
    trip_id = save_trip(
        Trip([Route(111_195, 7200, [Point(0.0, 0.0), Point(0.0, 1.0)])], 20_000, 0.2)
    )
    hours = [Forecast(12, 0.05, 0)] * 49
    with mock.patch(
        "apps.trips.checkpoints.hourly_forecasts",
        side_effect=lambda centers, start: dict.fromkeys(centers, hours),
    ):
        response = api_client.post(CHECKPOINTS_URL, checkpoints_body(trip_id), format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["distance_mi"] == 25
    ((route, miles),) = ((r["checkpoints"], r["miles_by_level"]) for r in body["routes"])
    # Calm forecast everywhere: the whole route (69.1 mi) is Low.
    assert miles == {
        "low": 69.1,
        "moderate": 0,
        "high": 0,
        "severe": 0,
        "no_travel": 0,
        "no_forecast": 0,
    }
    assert [round(c["elapsed_s"] / 60) for c in route] == [
        24,
        48,
        67,
    ]  # no steps: fallback 100 km/h
    assert [c["is_arrival"] for c in route] == [False, False, True]
    assert route[0] | {"lat": 0, "lon": 0, "distance_m": 0, "eta": 0} == {
        "lat": 0,
        "lon": 0,
        "distance_m": 0,
        "elapsed_s": route[0]["elapsed_s"],
        "breaks": 0,
        "eta": 0,
        "wind_mph": 12,
        "rain_in_hr": 0.05,
        "snow_in_hr": 0,
        "level": 0,
        "is_arrival": False,
    }


def test_checkpoints_for_an_unknown_trip(api_client):
    response = api_client.post(CHECKPOINTS_URL, checkpoints_body("missing"), format="json")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"distance_mi": 30},
        {"departure": "2020-01-01T00:00:00Z"},
        {"departure": (datetime.now(UTC) + timedelta(hours=49)).isoformat()},
        {"trip_id": ""},
    ],
)
def test_checkpoints_validation(api_client, overrides):
    body = checkpoints_body("x") | overrides
    response = api_client.post(CHECKPOINTS_URL, body, format="json")
    assert response.status_code == 400
    assert response.json().keys() == {next(iter(overrides))}


RECOMMENDATION_URL = "/api/v1/trips/recommendation/"


def test_recommendation(api_client):
    # Two routes over the same calm-then-windy forecast: the shorter one has fewer High
    # miles and wins on criterion 2.
    short = Route(55_000, 0, [Point(0.0, 0.0), Point(0.0, 0.5)])
    long = Route(111_000, 0, [Point(0.0, 0.0), Point(0.0, 1.0)])
    trip_id = save_trip(Trip([long, short], 20_000, 0.2))
    hours = [Forecast(40, 0, 0)] * 49  # 40 mph: High everywhere
    with mock.patch(
        "apps.trips.checkpoints.hourly_forecasts",
        side_effect=lambda centers, start: dict.fromkeys(centers, hours),
    ):
        body = checkpoints_body(trip_id)
        del body["distance_mi"]
        response = api_client.post(RECOMMENDATION_URL, body, format="json")

    assert response.status_code == 200
    data = response.json()
    assert data["recommended"] == 1
    assert data["decided_by"] == "high_miles"
    assert [score["route"] for score in data["ranking"]] == [1, 0]
    assert data["ranking"][0] == {
        "route": 1,
        "severe_miles": 0,
        "high_miles": pytest.approx(34.5, abs=0.1),
        "average_level": 2,
        "travel_s": pytest.approx(55_597 / (100_000 / 3600), abs=2),  # fallback 100 km/h
    }


def test_recommendation_for_an_unknown_trip(api_client):
    body = checkpoints_body("missing")
    del body["distance_mi"]
    assert api_client.post(RECOMMENDATION_URL, body, format="json").status_code == 404


def test_recommendation_validation(api_client):
    response = api_client.post(
        RECOMMENDATION_URL, {"trip_id": "x", "departure": "2020-01-01T00:00:00Z"}, format="json"
    )
    assert response.status_code == 400
    assert response.json().keys() == {"departure"}

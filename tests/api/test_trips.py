import io
import json
import urllib.error
import zlib
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from shapely import box

from apps.trips.business import trip as trip_module
from apps.trips.business.geometry import outline
from apps.trips.business.route import display_points
from apps.trips.domain.county import County
from apps.trips.domain.route import Point, Route, Step
from apps.trips.domain.trip import Trip
from apps.trips.domain.weather import Forecast
from apps.trips.services.counties import counties_along
from apps.trips.services.routing import decode_polyline
from apps.trips.services.trip_store import load_trip, save_trip

URL = "/backend/trips/route/"
DENVER = {"lat": 39.7392, "lon": -104.9903}
VAIL = {"lat": 39.6403, "lon": -106.3742}

# Example from Google's polyline documentation.
ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
DECODED = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


@pytest.fixture(autouse=True)
def _routes_key(settings):
    settings.GOOGLE_ROUTES_API_KEY = "test-key"


def fake_urlopen(payload):
    """Every Routes API call (the main one and any fallbacks) gets `payload`."""
    return mock.patch(
        "apps.trips.services.routing.urllib.request.urlopen",
        side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()),
    )


def test_decode_polyline():
    points = decode_polyline(ENCODED)
    assert points == DECODED
    assert points[0].lat == 38.5 and points[0].lon == -120.2


def test_route(api_client):
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
    with (
        fake_urlopen(payload) as urlopen,
        mock.patch("apps.trips.services.trips.counties_along") as counties,
    ):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})

    assert response.status_code == 200
    body = response.json()
    # Only Google's routes: counties, grid and forecasts come from the weather stream.
    assert body.keys() == {"trip_id", "weight_lb", "routes"}
    assert body["weight_lb"] == 20_000
    assert [
        (r["description"], r["distance_m"], r["duration_s"], r["source"]) for r in body["routes"]
    ] == [("I-70 W", 158000, 6300, "google"), ("US-6 W", 170000, 7200, "google")]
    assert body["routes"][0]["points"] == [list(p) for p in DECODED]
    counties.assert_not_called()
    # The trip is kept for the stream, checkpoints and recommendation; no grid yet.
    trip = load_trip(body["trip_id"])
    assert [r.description for r in trip.routes] == ["I-70 W", "US-6 W"]
    assert (trip.weight_lb, trip.step, trip.points) == (20_000, 0, ())
    assert trip.routes[0].steps == (Step(1000, 120), Step(157000, 6180))  # for travel times
    assert isinstance(trip.routes[0].points[0], Point)
    assert trip.routes[1].steps == ()
    sent = json.loads(urlopen.call_args_list[0].args[0].data)  # the main request
    assert sent["origin"]["location"]["latLng"] == {"latitude": 39.7392, "longitude": -104.9903}
    assert sent["travelMode"] == "DRIVE"
    assert sent["computeAlternativeRoutes"] is True


def test_display_points_are_simplified():
    straight = Route(1, 1, [Point(39.0, -105.0 + i * 0.001) for i in range(1000)])
    assert display_points(straight) == [(39.0, -105.0), (39.0, -104.001)]
    assert display_points(Route(1, 1, DECODED[:2])) == DECODED[:2]


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
    response = api_client.get("/backend/trips/examples/", HTTP_ACCEPT_ENCODING="gzip")
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
            "apps.trips.services.trips.hourly_forecasts",
            side_effect=lambda centers, start: dict.fromkeys(centers, hours),
        ),
        mock.patch("apps.trips.services.trips.route_risks", wraps=trip_module.route_risks) as risks,
    ):
        assert api_client.post(CHECKPOINTS_URL, body, format="json").status_code == 200
        del body["distance_mi"]
        assert api_client.post(RECOMMENDATION_URL, body, format="json").status_code == 200
    assert risks.call_count == 1  # computed for checkpoints, reused by the recommendation


def test_example_routes(api_client):
    response = api_client.get("/backend/trips/examples/")
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
    with mock.patch("apps.trips.services.routing.urllib.request.urlopen", side_effect=error):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 502
    assert response.json() == {"code": "upstream_error", "detail": mock.ANY, "status": 403}


def test_missing_key_is_bad_gateway(api_client, settings):
    settings.GOOGLE_ROUTES_API_KEY = ""
    response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 502


@pytest.mark.parametrize("weight", [None, 999, 100_001, "heavy", True, "NaN", "Infinity"])
def test_weight_is_required_and_in_range(api_client, weight):
    body = {"departure": DENVER, "arrival": VAIL}
    if weight is not None:
        body["weight_lb"] = weight
    response = api_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert "weight_lb" in response.json()


@pytest.mark.parametrize(
    "point",
    [
        {"lat": 200, "lon": 0},
        {"lat": 0, "lon": -181},
        {"lat": True, "lon": 0},
        {"lat": "NaN", "lon": 0},
        {"lat": 39.7, "lng": -105.0},  # typo: an unknown field
        {"address": "D"},
        {"address": "Denver\nCO"},
        {"address": "x" * 201},
        "Denver, CO",
    ],
)
def test_invalid_points(api_client, point):
    response = api_client.post(URL, {"departure": point, "arrival": VAIL, "weight_lb": 20_000})
    assert response.status_code == 400
    assert response.json().keys() == {"departure"}


@pytest.mark.parametrize(
    ("departure", "arrival"),
    [(DENVER, DENVER), ({"address": "Denver, CO"}, {"address": " denver,  co "})],
)
def test_departure_and_arrival_must_differ(api_client, departure, arrival):
    body = {"departure": departure, "arrival": arrival, "weight_lb": 20_000}
    response = api_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert response.json() == {"arrival": ["Arrival must differ from departure."]}


def test_route_refuses_unknown_fields(api_client):
    body = {"departure": DENVER, "arrival": VAIL, "weight_lb": 20_000, "weight": 1}
    response = api_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert response.json() == {"weight": ["Unknown field."]}


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
    simplified = outline(denver.geometry)
    assert simplified["type"] in ("Polygon", "MultiPolygon")
    assert len(str(simplified)) < len(str(denver.geometry.__geo_interface__))


CHECKPOINTS_URL = "/backend/trips/checkpoints/"
UNKNOWN_TRIP = "0" * 32  # well-formed, never saved


def checkpoints_body(trip_id, **overrides):
    departure = datetime.now(UTC) + timedelta(hours=2)
    return {"trip_id": trip_id, "distance_mi": 25, "departure": departure.isoformat()} | overrides


def test_checkpoints(api_client):
    trip_id = save_trip(
        Trip([Route(111_195, 7200, [Point(0.0, 0.0), Point(0.0, 1.0)])], 20_000, 0.2)
    )
    hours = [Forecast(12, 0.05, 0)] * 49
    with mock.patch(
        "apps.trips.services.trips.hourly_forecasts",
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
    response = api_client.post(CHECKPOINTS_URL, checkpoints_body(UNKNOWN_TRIP), format="json")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"distance_mi": 30},
        {"departure": "2020-01-01T00:00:00Z"},
        {"departure": (datetime.now(UTC) + timedelta(hours=49)).isoformat()},
        {"distance_mi": True},
        {"trip_id": ""},
        {"trip_id": "x"},
        {"trip_id": "A" * 32},  # ids are lowercase
        {"trip_id": "g" * 32},
        {"trip_id": UNKNOWN_TRIP + "0"},
    ],
)
def test_checkpoints_validation(api_client, overrides):
    body = checkpoints_body(UNKNOWN_TRIP) | overrides
    response = api_client.post(CHECKPOINTS_URL, body, format="json")
    assert response.status_code == 400
    assert response.json().keys() == {next(iter(overrides))}


RECOMMENDATION_URL = "/backend/trips/recommendation/"


def test_recommendation(api_client):
    # Two routes over the same calm-then-windy forecast: the shorter one has fewer High
    # miles and wins on criterion 2.
    short = Route(55_000, 0, [Point(0.0, 0.0), Point(0.0, 0.5)])
    long = Route(111_000, 0, [Point(0.0, 0.0), Point(0.0, 1.0)])
    trip_id = save_trip(Trip([long, short], 20_000, 0.2))
    hours = [Forecast(40, 0, 0)] * 49  # 40 mph: High everywhere
    with mock.patch(
        "apps.trips.services.trips.hourly_forecasts",
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
    body = checkpoints_body(UNKNOWN_TRIP)
    del body["distance_mi"]
    assert api_client.post(RECOMMENDATION_URL, body, format="json").status_code == 404


def test_recommendation_validation(api_client):
    response = api_client.post(
        RECOMMENDATION_URL,
        {"trip_id": UNKNOWN_TRIP, "departure": "2020-01-01T00:00:00Z"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json().keys() == {"departure"}


def test_requests_refuse_unknown_fields(api_client):
    body = checkpoints_body(UNKNOWN_TRIP, gap=10)
    response = api_client.post(CHECKPOINTS_URL, body, format="json")
    assert response.status_code == 400
    assert response.json() == {"gap": ["Unknown field."]}


def read_events(response) -> list[tuple[str, dict]]:
    """(event, data) pairs from a server-sent events response."""
    text = b"".join(response.streaming_content).decode()
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


# A 2 x 2 degree "county" and a route across it: 100 grid cells of 0.2 degrees.
SQUARE = County("99001", "Square", "ZZ", box(-105.0, 39.0, -103.0, 41.0))
ACROSS = Route(171_000, 7200, [Point(40.0, -105.0), Point(40.0, -103.0)])
HOURLY = {
    "time": [1_800_000_000 - 1_800_000_000 % 3600 + h * 3600 for h in range(50)],
    "wind_speed_10m": [40] * 50,
    "rain": [0] * 50,
    "snowfall": [0] * 50,
}


def fake_open_meteo():
    def urlopen(url, timeout):
        count = url.count("%2C", 0, url.index("longitude")) + 1  # latitudes in the request
        return io.BytesIO(json.dumps([{"hourly": HOURLY}] * count).encode())

    return mock.patch("apps.trips.services.weather.urllib.request.urlopen", side_effect=urlopen)


def stream(api_client, trip, **headers):
    """Saves the trip and streams its weather; returns (trip_id, response, events)."""
    # The time patch reaches time.time everywhere, the cache's expiry checks included,
    # so the trip is saved inside it too: saved before, it would already be expired.
    with (
        fake_open_meteo(),
        mock.patch("apps.trips.services.trips.counties_along", return_value=[SQUARE]),
        mock.patch("apps.trips.business.weather.time.time", return_value=1_800_000_000),
    ):
        trip_id = save_trip(trip)
        response = api_client.get(
            f"/backend/trips/{trip_id}/weather/", HTTP_ACCEPT="text/event-stream", **headers
        )
        return trip_id, response, read_events(response)


def test_weather_stream_sends_the_grid_then_the_forecasts(api_client):
    trip_id, response, events = stream(api_client, Trip([ACROSS], 45_000))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response["X-Accel-Buffering"] == "no"
    # The grid first, then 100 forecasts in batches of 80 + 20, then done.
    assert [name for name, _ in events] == ["grid", "batch", "batch", "done"]

    grid = events[0][1]
    assert len(grid["points"]) == len(grid["cells"]) == 100
    assert [c["fips"] for c in grid["counties"]] == ["99001"]
    (route,) = grid["routes"]
    assert route["counties"] == ["99001"]
    assert len(route["cells"]) == 100
    # Points come in the order the truck reaches them: westernmost (departure) first.
    assert grid["points"][0]["lon"] < grid["points"][-1]["lon"]

    indices = sorted(p["index"] for _, data in events[1:3] for p in data["points"])
    assert indices == list(range(100))
    first = events[1][1]["points"][0]
    assert first["levels"][0] == 3  # 40 mph over 40,000 lb: Severe
    assert len(first["wind_mph"]) == 49
    assert events[-1] == ("done", {"loaded": 100, "failed": 0})

    # The trip now has its grid, for the checkpoints and the recommendation.
    trip = load_trip(trip_id)
    assert (trip.step, len(trip.points)) == (0.2, 100)


def test_weather_stream_is_gzipped_event_by_event(api_client):
    trip_id = save_trip(Trip([ACROSS], 20_000))
    with (
        fake_open_meteo(),
        mock.patch("apps.trips.services.trips.counties_along", return_value=[SQUARE]),
    ):
        response = api_client.get(
            f"/backend/trips/{trip_id}/weather/",
            HTTP_ACCEPT="text/event-stream",
            HTTP_ACCEPT_ENCODING="gzip",
        )
        chunks = list(response.streaming_content)
    assert response["Content-Encoding"] == "gzip"
    # Each event is flushed on its own: every chunk decompresses on arrival.
    decompressor = zlib.decompressobj(31)
    text = "".join(decompressor.decompress(chunk).decode() for chunk in chunks)
    names = [line[7:] for line in text.splitlines() if line.startswith("event: ")]
    assert names == ["grid", "batch", "batch", "done"]


def test_checkpoints_build_the_grid_if_the_stream_did_not(api_client):
    trip_id = save_trip(Trip([ACROSS], 20_000))
    body = checkpoints_body(trip_id)
    with (
        fake_open_meteo(),
        mock.patch("apps.trips.services.trips.counties_along", return_value=[SQUARE]),
    ):
        response = api_client.post(CHECKPOINTS_URL, body, format="json")
    assert response.status_code == 200
    assert load_trip(trip_id).step == 0.2


def test_weather_stream_for_an_unknown_trip(api_client):
    response = api_client.get(f"/backend/trips/{UNKNOWN_TRIP}/weather/")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_weather_stream_refuses_a_malformed_trip_id(api_client):
    response = api_client.get("/backend/trips/missing/weather/")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid"

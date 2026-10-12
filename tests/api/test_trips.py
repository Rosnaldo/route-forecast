import io
import json
import urllib.error
from unittest import mock

import pytest

from apps.trips.counties import County, counties_along
from apps.trips.routing import decode_polyline

URL = "/api/v1/trips/route/"
DENVER = {"lat": 39.7392, "lon": -104.9903}
VAIL = {"lat": 39.6403, "lon": -106.3742}

# Example from Google's polyline documentation.
ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
DECODED = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


@pytest.fixture(autouse=True)
def _routes_key(settings):
    settings.GOOGLE_ROUTES_API_KEY = "test-key"


def fake_urlopen(payload):
    return mock.patch(
        "apps.trips.routing.urllib.request.urlopen",
        return_value=io.BytesIO(json.dumps(payload).encode()),
    )


def test_decode_polyline():
    assert decode_polyline(ENCODED) == DECODED


def test_route(api_client):
    payload = {
        "routes": [
            {
                "distanceMeters": 158000,
                "duration": "6300s",
                "polyline": {"encodedPolyline": ENCODED},
            }
        ]
    }
    denver = County("08031", "Denver", "CO")
    with (
        fake_urlopen(payload) as urlopen,
        mock.patch("apps.trips.views.counties_along", return_value=[denver]) as counties,
    ):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL})

    assert response.status_code == 200
    assert response.json() == {
        "distance_m": 158000,
        "duration_s": 6300,
        "points": [list(p) for p in DECODED],
        "counties": [{"fips": "08031", "name": "Denver", "state": "CO", "geometry": None}],
    }
    counties.assert_called_once_with(DECODED)
    sent = json.loads(urlopen.call_args.args[0].data)
    assert sent["origin"]["location"]["latLng"] == {"latitude": 39.7392, "longitude": -104.9903}
    assert sent["travelMode"] == "DRIVE"


def test_route_from_addresses(api_client):
    payload = {"routes": [{"distanceMeters": 1, "polyline": {"encodedPolyline": ENCODED}}]}
    with fake_urlopen(payload) as urlopen:
        response = api_client.post(
            URL, {"departure": {"address": "Denver, CO"}, "arrival": {"address": "Vail, CO"}}
        )
    assert response.status_code == 200
    sent = json.loads(urlopen.call_args.args[0].data)
    assert sent["origin"] == {"address": "Denver, CO"}
    assert sent["destination"] == {"address": "Vail, CO"}


@pytest.mark.parametrize(
    "point",
    [{}, {"lat": 39.7}, {"lat": 39.7, "lon": -105.0, "address": "Denver, CO"}, {"address": ""}],
)
def test_point_needs_coordinates_or_address(api_client, point):
    response = api_client.post(URL, {"departure": point, "arrival": VAIL})
    assert response.status_code == 400
    assert "departure" in response.json()


def test_example_routes(api_client):
    response = api_client.get("/api/v1/trips/examples/")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 10
    assert rows[0] | {"purpose": None} == {
        "id": 1,
        "departure": "Denver, CO",
        "arrival": "Vail, CO",
        "distance_km": 160,
        "purpose": None,
    }


def test_no_route_found(api_client):
    with fake_urlopen({}):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL})
    assert response.status_code == 400
    assert response.json()["code"] == "domain_error"


def test_google_error_is_bad_gateway(api_client):
    error = urllib.error.HTTPError(URL, 403, "Forbidden", {}, None)
    with mock.patch("apps.trips.routing.urllib.request.urlopen", side_effect=error):
        response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL})
    assert response.status_code == 502
    assert response.json() == {"code": "upstream_error", "detail": mock.ANY, "status": 403}


def test_missing_key_is_bad_gateway(api_client, settings):
    settings.GOOGLE_ROUTES_API_KEY = ""
    response = api_client.post(URL, {"departure": DENVER, "arrival": VAIL})
    assert response.status_code == 502


def test_invalid_coordinates(api_client):
    response = api_client.post(URL, {"departure": {"lat": 200, "lon": 0}, "arrival": VAIL})
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

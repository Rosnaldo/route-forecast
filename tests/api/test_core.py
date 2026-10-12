from unittest import mock

from rest_framework.throttling import AnonRateThrottle


def test_health(client, db):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "cache": "ok"}


def test_request_id_middleware(client, db):
    assert len(client.get("/health/")["X-Request-ID"]) == 32
    assert client.get("/health/", headers={"X-Request-ID": "abc"})["X-Request-ID"] == "abc"
    assert "Server-Timing" in client.get("/health/")


def test_home_page_renders_template(client, db):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Shop API" in response.content
    assert [t.name for t in response.templates][:2] == ["home.html", "base.html"]


def test_openapi_schema(client, db):
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert response.content.startswith(b"openapi: 3")


def test_api_is_throttled_per_client(api_client):
    # Rates are read into the class at import time, so patch the class attribute.
    with mock.patch.object(AnonRateThrottle, "THROTTLE_RATES", {"anon": "2/minute"}):
        codes = [api_client.get("/api/schema/").status_code for _ in range(3)]
    assert codes == [200, 200, 429]

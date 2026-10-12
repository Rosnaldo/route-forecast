import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _isolation():
    cache.clear()  # throttling counters live in the cache
    yield


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()

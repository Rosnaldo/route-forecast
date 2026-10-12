from rest_framework.exceptions import ValidationError

from apps.core.exception_handler import api_exception_handler
from apps.core.exceptions import ConflictError, NotFoundError


def test_domain_errors_map_to_status_and_payload():
    response = api_exception_handler(ConflictError("Route conflict.", route_id=3), {})
    assert response.status_code == 409
    assert response.data == {"code": "conflict", "detail": "Route conflict.", "route_id": 3}
    assert api_exception_handler(NotFoundError("Missing."), {}).status_code == 404


def test_other_exceptions_fall_back_to_drf():
    response = api_exception_handler(ValidationError({"field": ["bad"]}), {})
    assert response.status_code == 400 and response.data == {"field": ["bad"]}
    assert api_exception_handler(RuntimeError("boom"), {}) is None  # unhandled -> 500

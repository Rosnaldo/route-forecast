from rest_framework.response import Response
from rest_framework.views import exception_handler

from .exceptions import DomainError


def api_exception_handler(exc, context):
    """Map domain exceptions to HTTP responses; defer everything else to DRF."""
    if isinstance(exc, DomainError):
        return Response(
            {"code": exc.code, "detail": exc.message, **exc.details},
            status=exc.status_code,
        )
    return exception_handler(exc, context)

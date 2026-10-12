"""
Domain exceptions are plain Python: the service/domain layers raise them
without knowing about HTTP or DRF. The API layer translates them at the edge
(see apps/core/exception_handler.py).
"""

from http import HTTPStatus


class DomainError(Exception):
    status_code = HTTPStatus.BAD_REQUEST
    code = "domain_error"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class ConflictError(DomainError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"


class PermissionDeniedError(DomainError):
    status_code = HTTPStatus.FORBIDDEN
    code = "permission_denied"

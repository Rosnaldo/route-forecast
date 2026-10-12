from rest_framework.pagination import CursorPagination, PageNumberPagination


class StandardPagination(PageNumberPagination):
    """?page=2&page_size=50 — simple, supports jumping to any page, but
    COUNT(*) + OFFSET get slow on big tables and pages shift on inserts."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CreatedAtCursorPagination(CursorPagination):
    """Opaque ?cursor=... — O(1) per page using `WHERE created_at < x`, stable
    under concurrent inserts. Ideal for feeds and activity logs."""

    page_size = 30
    ordering = "-created_at"

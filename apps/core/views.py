from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def home(request: HttpRequest):
    """A server-rendered page (Django templates), using a static CSS file."""
    return render(request, "home.html")


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Liveness/readiness probe for Docker, ALB target groups, Kubernetes."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        cache.set("health", "ok", 5)
        checks["cache"] = "ok" if cache.get("health") == "ok" else "error"
    except Exception as exc:  # noqa: BLE001
        checks["cache"] = f"error: {exc.__class__.__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", **checks}, status=200 if healthy else 503
    )

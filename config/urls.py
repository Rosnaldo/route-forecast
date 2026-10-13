from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core import views as core_views

# Every API route lives under /backend/, which nginx proxies to Django as is.
# Add each domain app here: path("", include("apps.<name>.routes")),
api_patterns: list = [
    path("", include("apps.trips.routes")),
]

urlpatterns = [
    path("", core_views.home, name="home"),
    path("health/", core_views.health, name="health"),
    path("backend/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("backend/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("backend/", include(api_patterns)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core import views as core_views

# Every API route lives under /api/<version>/; URLPathVersioning reads `version`
# from the URL kwargs and exposes it as `request.version`.
# Add each domain app here: path("", include("apps.<name>.urls")),
api_patterns: list = []

urlpatterns = [
    path("", core_views.home, name="home"),
    path("health/", core_views.health, name="health"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    re_path(r"^api/(?P<version>v1|v2)/", include(api_patterns)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

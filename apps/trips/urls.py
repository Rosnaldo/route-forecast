from django.urls import path

from .views import RouteView

urlpatterns = [
    path("trips/route/", RouteView.as_view(), name="trip-route"),
]

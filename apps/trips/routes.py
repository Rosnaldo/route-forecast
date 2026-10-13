"""URL routes of the trip API, mounted under /backend/ (config/urls.py)."""

from django.urls import path

from .controllers.trips import CheckpointsView, ExampleRoutesView, RecommendationView, RouteView
from .controllers.weather import WeatherStreamView

urlpatterns = [
    path("trips/route/", RouteView.as_view(), name="trip-route"),
    path("trips/<str:trip_id>/weather/", WeatherStreamView.as_view(), name="trip-weather"),
    path("trips/checkpoints/", CheckpointsView.as_view(), name="trip-checkpoints"),
    path("trips/recommendation/", RecommendationView.as_view(), name="trip-recommendation"),
    path("trips/examples/", ExampleRoutesView.as_view(), name="trip-examples"),
]

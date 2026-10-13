from django.urls import path

from .views import CheckpointsView, ExampleRoutesView, RecommendationView, RouteView

urlpatterns = [
    path("trips/route/", RouteView.as_view(), name="trip-route"),
    path("trips/checkpoints/", CheckpointsView.as_view(), name="trip-checkpoints"),
    path("trips/recommendation/", RecommendationView.as_view(), name="trip-recommendation"),
    path("trips/examples/", ExampleRoutesView.as_view(), name="trip-examples"),
]

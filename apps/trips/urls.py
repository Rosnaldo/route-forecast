from django.urls import path

from .views import CheckpointsView, ExampleRoutesView, RouteView

urlpatterns = [
    path("trips/route/", RouteView.as_view(), name="trip-route"),
    path("trips/checkpoints/", CheckpointsView.as_view(), name="trip-checkpoints"),
    path("trips/examples/", ExampleRoutesView.as_view(), name="trip-examples"),
]

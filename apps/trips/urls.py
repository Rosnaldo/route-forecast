from django.urls import path

from .views import ExampleRoutesView, RouteView

urlpatterns = [
    path("trips/route/", RouteView.as_view(), name="trip-route"),
    path("trips/examples/", ExampleRoutesView.as_view(), name="trip-examples"),
]

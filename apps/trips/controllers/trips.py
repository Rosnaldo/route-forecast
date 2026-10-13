"""The trip JSON endpoints: validate the request, call the use case, serialize."""

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import trips
from .requests import CheckpointsRequestSerializer, RouteRequestSerializer, TripDepartureSerializer
from .responses import (
    CheckpointsResponseSerializer,
    RecommendationResponseSerializer,
    RouteResponseSerializer,
)


class RouteView(APIView):
    """Up to three driving routes between departure and arrival (Google's, plus fallbacks
    when it has fewer), returned as soon as Google answers. The counties they cross and
    the weather risk on a grid over them, for a truck carrying `weight_lb` of cargo,
    come from the weather stream for the returned `trip_id`."""

    serializer_class = RouteRequestSerializer

    def post(self, request: Request) -> Response:
        params = RouteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        departure, arrival, weight_lb = (
            params.validated_data[key] for key in ("departure", "arrival", "weight_lb")
        )
        trip_id, routes = trips.plan_trip(departure, arrival, weight_lb)
        data = {"trip_id": trip_id, "weight_lb": weight_lb, "routes": routes}
        return Response(RouteResponseSerializer(data).data)


class CheckpointsView(APIView):
    """Checkpoints every `distance_mi` miles along each route of a computed trip, with
    the expected travel time to each and the weather risk when the truck gets there,
    leaving at `departure`; plus each route's miles at each risk level."""

    serializer_class = CheckpointsRequestSerializer

    def post(self, request: Request) -> Response:
        params = CheckpointsRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        trip_id, distance_mi, departure = (
            params.validated_data[key] for key in ("trip_id", "distance_mi", "departure")
        )
        checkpoints = trips.plan_checkpoints(trip_id, distance_mi, departure.timestamp())
        data = {"distance_mi": distance_mi, "departure": departure, "routes": checkpoints}
        return Response(CheckpointsResponseSerializer(data).data)


class RecommendationView(APIView):
    """The route to take for a computed trip leaving at `departure`: routes ranked by
    Severe miles, High miles, average risk, then travel time (see recommendation.py)."""

    serializer_class = TripDepartureSerializer

    def post(self, request: Request) -> Response:
        params = TripDepartureSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        trip_id = params.validated_data["trip_id"]
        departure = params.validated_data["departure"]
        recommendation = trips.recommend_route(trip_id, departure.timestamp())
        data = {
            "departure": departure,
            "recommended": recommendation.ranking[0].route,
            **recommendation._asdict(),
        }
        return Response(RecommendationResponseSerializer(data).data)


class ExampleRoutesView(APIView):
    """Sample trips from example_routes.csv, for trying the route endpoint."""

    def get(self, request: Request) -> Response:
        return Response(trips.example_routes())

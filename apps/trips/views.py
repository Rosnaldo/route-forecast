from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .counties import counties_along
from .routing import compute_route


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class RouteRequestSerializer(serializers.Serializer):
    departure = PointSerializer()
    arrival = PointSerializer()


class CountySerializer(serializers.Serializer):
    fips = serializers.CharField()
    name = serializers.CharField()
    state = serializers.CharField()


class RouteResponseSerializer(serializers.Serializer):
    distance_m = serializers.IntegerField()
    duration_s = serializers.IntegerField()
    points = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))
    counties = CountySerializer(many=True)


class RouteView(APIView):
    """Driving route between departure and arrival: [lat, lon] points and counties crossed."""

    serializer_class = RouteRequestSerializer

    def post(self, request: Request, version: str) -> Response:
        params = RouteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        departure, arrival = params.validated_data["departure"], params.validated_data["arrival"]
        route = compute_route(
            (departure["lat"], departure["lon"]), (arrival["lat"], arrival["lon"])
        )
        data = {**vars(route), "counties": counties_along(route.points)}
        return Response(RouteResponseSerializer(data).data)

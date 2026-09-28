from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema

from .models import Booking, BookingStatus
from .serializers import BookingCreateSerializer, BookingSerializer
from .services import BookingError, cancel_booking, create_booking


class BookingViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Bookings of the authenticated user. Other users' bookings are invisible (404),
    so booking IDs can't be probed. Staff users see all bookings.
    Filter the list with `?status=PENDING|CONFIRMED|FAILED|CANCELLED`.
    """

    serializer_class = BookingSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Booking.objects.none()
        qs = Booking.objects.select_related("centre", "test")
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            if status_filter.upper() not in BookingStatus.values:
                raise serializers.ValidationError({"status": f"Must be one of {BookingStatus.values}."})
            qs = qs.filter(status=status_filter.upper())
        return qs

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingSerializer})
    def create(self, request, *args, **kwargs):
        payload = BookingCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            booking = create_booking(user=request.user, **payload.validated_data)
        except BookingError as exc:
            raise serializers.ValidationError({exc.field: [exc.message]})
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: BookingSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        # Ownership check first: only the patient who made the booking may cancel it.
        booking = self.get_object()
        if booking.user_id != request.user.id:
            return Response(
                {"error": {"code": "permission_denied", "message": "Only the booking owner can cancel it.", "details": None}},
                status=status.HTTP_403_FORBIDDEN,
            )
        booking = cancel_booking(booking_id=booking.pk, user=request.user)
        return Response(BookingSerializer(booking).data)

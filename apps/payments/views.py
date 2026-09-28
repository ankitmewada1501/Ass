import logging
import uuid

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.bookings.models import Booking

from .authentication import SIGNATURE_HEADER, is_valid_signature
from .models import Payment
from .serializers import DevWebhookSerializer, PaymentCreateSerializer, PaymentSerializer, WebhookAckSerializer, WebhookEventSerializer
from .services import IdempotencyKeyReused, create_payment, process_webhook_event

logger = logging.getLogger(__name__)


class PaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Simulated payments for the authenticated user's bookings."""

    serializer_class = PaymentSerializer
    throttle_scope = "payments"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Payment.objects.none()
        return Payment.objects.filter(user=self.request.user).select_related("booking")

    def get_throttles(self):
        # Tighter limit on the charge endpoint; reads use the default user rate.
        if self.action == "create":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        request=PaymentCreateSerializer,
        responses={201: PaymentSerializer, 200: PaymentSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=False)],
    )
    def create(self, request, *args, **kwargs):
        payload = PaymentCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "").strip() or None
        if key and len(key) > 64:
            raise serializers.ValidationError({"Idempotency-Key": ["Must be at most 64 characters."]})

        try:
            payment, created = create_payment(
                user=request.user,
                booking_id=payload.validated_data["booking_id"],
                idempotency_key=key,
                forced_outcome=payload.validated_data.get("simulate_outcome"),
            )
        except Booking.DoesNotExist:
            raise NotFound("Booking not found.")
        except IdempotencyKeyReused:
            return Response(
                {"error": {
                    "code": "idempotency_key_reused",
                    "message": "This Idempotency-Key was already used for a different booking.",
                    "details": None,
                }},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        payment.refresh_from_db()
        return Response(
            PaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PaymentWebhookView(APIView):
    """
    Receives payment status events from the (simulated) provider.

    Authenticated by an HMAC-SHA256 signature of the raw body in the
    `X-Webhook-Signature` header, not by JWT. Idempotent on `event_id`:
    redelivered events return 200 with `"duplicate": true` and change nothing.

    Response codes are chosen for provider retry semantics: 2xx = stop retrying,
    404 (unknown payment, may not be committed yet) and 5xx = retry later.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        request=WebhookEventSerializer,
        responses={200: WebhookAckSerializer},
        parameters=[OpenApiParameter(SIGNATURE_HEADER, str, OpenApiParameter.HEADER, required=True)],
    )
    def post(self, request):
        if not is_valid_signature(request.body, request.headers.get(SIGNATURE_HEADER)):
            logger.warning("webhook.bad_signature", extra={"remote_addr": request.META.get("REMOTE_ADDR")})
            return Response(
                {"error": {"code": "invalid_signature", "message": "Invalid webhook signature.", "details": None}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = WebhookEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            event, duplicate = process_webhook_event(
                event_id=data["event_id"],
                event_type=data["type"],
                provider_reference=data["data"]["provider_reference"],
                amount=data["data"].get("amount"),
                payload=request.data,
            )
        except Payment.DoesNotExist:
            raise NotFound("Unknown payment reference.")

        return Response(
            {
                "event_id": event.event_id,
                "duplicate": duplicate,
                "status": event.status,
                "note": event.note,
                "payment_status": event.payment.status,
                "booking_status": event.payment.booking.status,
            },
            status=status.HTTP_200_OK,
        )


class DevWebhookSimulateView(APIView):
    """
    DEBUG-only helper for the web UI: plays the payment provider and delivers a
    webhook event for one of the caller's own payments. Reusing `event_id`
    demonstrates idempotency. Returns 404 when DEBUG is off.
    """

    @extend_schema(request=DevWebhookSerializer, responses={200: WebhookAckSerializer})
    def post(self, request):
        if not settings.DEBUG:
            raise NotFound()
        serializer = DevWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not Payment.objects.filter(provider_reference=data["provider_reference"], user=request.user).exists():
            raise NotFound("Payment not found.")

        event_id = data.get("event_id") or f"evt_{uuid.uuid4().hex}"
        event_type = f"payment.{data['outcome']}"
        payload = {"event_id": event_id, "type": event_type, "data": {"provider_reference": data["provider_reference"]}}
        event, duplicate = process_webhook_event(
            event_id=event_id,
            event_type=event_type,
            provider_reference=data["provider_reference"],
            amount=None,
            payload=payload,
        )
        return Response(
            {
                "event_id": event.event_id,
                "duplicate": duplicate,
                "status": event.status,
                "note": event.note,
                "payment_status": event.payment.status,
                "booking_status": event.payment.booking.status,
            }
        )

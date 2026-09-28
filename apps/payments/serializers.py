from rest_framework import serializers

from .models import Payment, PaymentStatus
from .services import EVENT_TYPE_TO_STATUS


class PaymentSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(read_only=True)
    booking_status = serializers.CharField(source="booking.status", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "booking_id", "booking_status", "amount", "currency", "status",
            "provider_reference", "failure_reason", "created_at", "updated_at",
        ]
        read_only_fields = fields


class PaymentCreateSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField(min_value=1)
    simulate_outcome = serializers.ChoiceField(
        choices=PaymentStatus.values,
        required=False,
        help_text="Force the mock gateway result. PENDING leaves the payment awaiting a webhook. "
        "Omit for a random outcome.",
    )


class WebhookDataSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(max_length=64)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    failure_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WebhookEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=100)
    type = serializers.ChoiceField(choices=list(EVENT_TYPE_TO_STATUS))
    data = WebhookDataSerializer()


class WebhookAckSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    duplicate = serializers.BooleanField()
    status = serializers.CharField()
    note = serializers.CharField()
    payment_status = serializers.CharField()
    booking_status = serializers.CharField()

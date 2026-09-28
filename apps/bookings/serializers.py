from rest_framework import serializers

from apps.catalog.models import DiagnosticCentre, DiagnosticTest

from .models import Booking


class _CentreSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = ["id", "name", "city"]


class _TestSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "code", "name"]


class BookingSerializer(serializers.ModelSerializer):
    centre = _CentreSummarySerializer(read_only=True)
    test = _TestSummarySerializer(read_only=True)
    user_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "user_id", "centre", "test", "appointment_at", "amount",
            "status", "cancelled_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class BookingCreateSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField(min_value=1)
    test_id = serializers.IntegerField(min_value=1)
    appointment_at = serializers.DateTimeField()

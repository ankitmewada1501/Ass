from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import CentreTest, DiagnosticCentre, DiagnosticTest


class DiagnosticTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "code", "name", "description"]

    def validate_code(self, value):
        return value.strip().upper()


class CentreTestSerializer(serializers.ModelSerializer):
    """Offering of a test at a centre. Write with `test_id`, read the nested test."""

    test = DiagnosticTestSerializer(read_only=True)
    test_id = serializers.PrimaryKeyRelatedField(
        queryset=DiagnosticTest.objects.all(), source="test", write_only=True
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = CentreTest
        fields = ["id", "test", "test_id", "price", "is_active"]

    def validate(self, attrs):
        centre = self.context["centre"]
        test = attrs.get("test")
        if test and self.instance is None and CentreTest.objects.filter(centre=centre, test=test).exists():
            raise serializers.ValidationError({"test_id": "This centre already offers this test."})
        if self.instance is not None and test and test != self.instance.test:
            raise serializers.ValidationError({"test_id": "The test of an existing offering cannot be changed."})
        return attrs


class DiagnosticCentreSerializer(serializers.ModelSerializer):
    tests = serializers.SerializerMethodField()

    class Meta:
        model = DiagnosticCentre
        fields = ["id", "name", "address", "city", "pincode", "is_active", "tests"]
        read_only_fields = ["is_active"]

    @extend_schema_field(CentreTestSerializer(many=True))
    def get_tests(self, centre):
        # Uses the prefetched `active_offerings` from the viewset to avoid N+1 queries.
        offerings = getattr(centre, "active_offerings", None)
        if offerings is None:
            offerings = centre.offerings.filter(is_active=True).select_related("test")
        return CentreTestSerializer(offerings, many=True).data

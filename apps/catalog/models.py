from django.db import models
from django.db.models import Q


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DiagnosticCentre(TimestampedModel):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=100, db_index=True)
    pincode = models.CharField(max_length=10, blank=True)
    # Deactivated instead of deleted so historical bookings stay intact.
    is_active = models.BooleanField(default=True)
    tests = models.ManyToManyField("DiagnosticTest", through="CentreTest", related_name="centres")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="uniq_centre_name_city"),
        ]

    def __str__(self):
        return f"{self.name} ({self.city})"


class DiagnosticTest(TimestampedModel):
    """A test type in the global catalogue, e.g. 'Complete Blood Count'."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class CentreTest(TimestampedModel):
    """A test offered by a specific centre at a centre-specific price."""

    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.PROTECT, related_name="offerings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="offerings")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["test__name"]
        constraints = [
            models.UniqueConstraint(fields=["centre", "test"], name="uniq_centre_test"),
            models.CheckConstraint(condition=Q(price__gt=0), name="centre_test_price_positive"),
        ]

    def __str__(self):
        return f"{self.test.name} @ {self.centre.name}: {self.price}"

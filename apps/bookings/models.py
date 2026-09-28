from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import DiagnosticCentre, DiagnosticTest


class BookingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending payment"
    CONFIRMED = "CONFIRMED", "Confirmed"
    FAILED = "FAILED", "Payment failed"
    CANCELLED = "CANCELLED", "Cancelled"


# Allowed state machine transitions. FAILED is not terminal: the patient may retry
# payment, and a later successful payment confirms the booking.
ALLOWED_TRANSITIONS = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED},
    BookingStatus.FAILED: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}

# Statuses in which a booking still "holds" its slot.
ACTIVE_STATUSES = [BookingStatus.PENDING, BookingStatus.CONFIRMED]
PAYABLE_STATUSES = [BookingStatus.PENDING, BookingStatus.FAILED]


class InvalidTransition(Exception):
    pass


class Booking(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.PROTECT, related_name="bookings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="bookings")
    appointment_at = models.DateTimeField()
    # Snapshot of the centre's price at booking time; later price changes don't affect it.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=BookingStatus.choices, default=BookingStatus.PENDING)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="booking_amount_positive"),
            # Guards against double-submits: a user can hold only one active booking
            # for the same test, centre and slot. Enforced by the DB, not just the API.
            models.UniqueConstraint(
                fields=["user", "centre", "test", "appointment_at"],
                condition=Q(status__in=ACTIVE_STATUSES),
                name="uniq_active_booking_per_slot",
            ),
        ]

    def __str__(self):
        return f"Booking #{self.pk} {self.test.code} @ {self.centre.name} [{self.status}]"

    def can_transition_to(self, new_status) -> bool:
        return new_status in ALLOWED_TRANSITIONS[BookingStatus(self.status)]

    def transition_to(self, new_status, save=True):
        if not self.can_transition_to(new_status):
            raise InvalidTransition(f"Cannot move booking from {self.status} to {new_status}.")
        self.status = new_status
        if save:
            self.save(update_fields=["status", "cancelled_at", "updated_at"])

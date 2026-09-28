from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.bookings.models import Booking


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


TERMINAL_PAYMENT_STATUSES = {PaymentStatus.SUCCESS, PaymentStatus.FAILED}


class Payment(models.Model):
    """One payment attempt for a booking. A booking may have several failed attempts."""

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    # ID assigned by the (mock) provider; webhooks reference payments by it.
    provider_reference = models.CharField(max_length=64, unique=True)
    # Client-supplied Idempotency-Key header, so retried POST /payments/ calls
    # return the original attempt instead of charging twice.
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="uniq_payment_idempotency_key_per_user",
            ),
            # DB-level guarantees against double charging / parallel attempts.
            models.UniqueConstraint(
                fields=["booking"], condition=Q(status="SUCCESS"), name="uniq_successful_payment_per_booking"
            ),
            models.UniqueConstraint(
                fields=["booking"], condition=Q(status="PENDING"), name="uniq_pending_payment_per_booking"
            ),
        ]

    def __str__(self):
        return f"Payment {self.provider_reference} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PAYMENT_STATUSES


class WebhookEventStatus(models.TextChoices):
    PROCESSED = "PROCESSED"  # changed payment/booking state
    IGNORED = "IGNORED"  # valid, but a no-op (e.g. payment already final)


class WebhookEvent(models.Model):
    """
    Ledger of every provider event we have handled. The unique `event_id` is what
    makes the webhook idempotent: a redelivered event hits the constraint and is
    acknowledged without being applied again.
    """

    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=50)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="webhook_events")
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=WebhookEventStatus.choices)
    note = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_id} ({self.event_type}) [{self.status}]"

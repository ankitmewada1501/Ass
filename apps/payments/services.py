import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import PAYABLE_STATUSES, Booking, BookingStatus
from apps.core.exceptions import Conflict

from .gateway import gateway
from .models import Payment, PaymentStatus, WebhookEvent, WebhookEventStatus

logger = logging.getLogger(__name__)

EVENT_TYPE_TO_STATUS = {
    "payment.succeeded": PaymentStatus.SUCCESS,
    "payment.failed": PaymentStatus.FAILED,
}


class IdempotencyKeyReused(Exception):
    pass


def apply_payment_result(payment: Payment, new_status: str, failure_reason: str = "") -> str:
    """
    Move a PENDING payment to a final status and update its booking.
    Caller must hold row locks on the payment and its booking (select_for_update).
    Used by both the synchronous payment flow and the webhook, so there is
    exactly one place that encodes "payment result -> booking status".
    Returns a short note describing what happened to the booking.
    """
    payment.status = new_status
    payment.failure_reason = failure_reason if new_status == PaymentStatus.FAILED else ""
    payment.save(update_fields=["status", "failure_reason", "updated_at"])

    booking = payment.booking
    target = BookingStatus.CONFIRMED if new_status == PaymentStatus.SUCCESS else BookingStatus.FAILED

    if booking.status == target:
        return f"booking already {target}"
    if booking.status == BookingStatus.CANCELLED and new_status == PaymentStatus.SUCCESS:
        # Money was taken for a booking that no longer exists: flag, don't resurrect.
        logger.warning(
            "payment.success_for_cancelled_booking",
            extra={"payment_id": payment.pk, "booking_id": booking.pk, "refund_required": True},
        )
        return "booking is cancelled; refund required"
    if not booking.can_transition_to(target):
        # e.g. a late FAILED for one attempt while another attempt already confirmed it.
        return f"booking left as {booking.status}"

    booking.transition_to(target)
    logger.info(
        "booking.status_changed",
        extra={"booking_id": booking.pk, "status": target, "payment_id": payment.pk},
    )
    return f"booking moved to {target}"


def create_payment(*, user, booking_id: int, idempotency_key: str | None, forced_outcome: str | None):
    """
    Charge a booking through the mock gateway. Returns (payment, created).
    Retrying with the same Idempotency-Key returns the original payment.
    """
    if idempotency_key:
        existing = Payment.objects.filter(user=user, idempotency_key=idempotency_key).select_related("booking").first()
        if existing:
            if existing.booking_id != booking_id:
                raise IdempotencyKeyReused()
            return existing, False

    try:
        with transaction.atomic():
            # Lock the booking so concurrent payment attempts / cancellation serialize.
            booking = Booking.objects.select_for_update().get(pk=booking_id, user=user)
            if booking.status not in PAYABLE_STATUSES:
                raise Conflict(f"Booking is {booking.status} and cannot be paid for.")
            if booking.appointment_at <= timezone.now():
                raise Conflict("The appointment time has passed; this booking can no longer be paid for.")
            if booking.payments.filter(status=PaymentStatus.PENDING).exists():
                raise Conflict("A payment for this booking is already in progress.")

            payment = Payment.objects.create(
                booking=booking,
                user=user,
                amount=booking.amount,  # always charge the booking's amount
                provider_reference=gateway.new_reference(),
                idempotency_key=idempotency_key or None,
            )
            result = gateway.charge(
                reference=payment.provider_reference, amount=payment.amount, forced_outcome=forced_outcome
            )
            if result.status != PaymentStatus.PENDING:
                apply_payment_result(payment, result.status, result.failure_reason)
    except IntegrityError:
        # Lost a race: a parallel request with the same idempotency key, or a
        # parallel attempt for the same booking, committed first.
        if idempotency_key:
            existing = Payment.objects.filter(user=user, idempotency_key=idempotency_key).first()
            if existing and existing.booking_id == booking_id:
                return existing, False
        raise Conflict("A payment for this booking is already in progress or completed.")

    logger.info(
        "payment.created",
        extra={"payment_id": payment.pk, "booking_id": booking.pk, "status": payment.status},
    )
    return payment, True


def process_webhook_event(*, event_id: str, event_type: str, provider_reference: str, amount, payload: dict):
    """
    Idempotently apply a provider event. Returns (WebhookEvent, duplicate: bool).
    Raises Payment.DoesNotExist for unknown references (the provider should retry).
    """
    existing = WebhookEvent.objects.filter(event_id=event_id).first()
    if existing:
        return existing, True

    new_status = EVENT_TYPE_TO_STATUS[event_type]
    try:
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(provider_reference=provider_reference)
            # Lock the booking too: cancellation or another attempt may touch it concurrently.
            payment.booking = Booking.objects.select_for_update().get(pk=payment.booking_id)

            if amount is not None and amount != payment.amount:
                status, note = WebhookEventStatus.IGNORED, f"amount mismatch: expected {payment.amount}, got {amount}"
                logger.warning("webhook.amount_mismatch", extra={"event_id": event_id, "payment_id": payment.pk})
            elif payment.is_terminal:
                # Out-of-order or conflicting event: a final payment state never changes.
                status = WebhookEventStatus.IGNORED
                note = f"payment already {payment.status}"
            else:
                reason = payload.get("data", {}).get("failure_reason", "") or "Reported failed by provider."
                note = apply_payment_result(payment, new_status, reason)
                status = WebhookEventStatus.PROCESSED

            event = WebhookEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                payment=payment,
                payload=payload,
                status=status,
                note=note[:255],
            )
    except IntegrityError:
        # A concurrent delivery of the same event committed first; nothing was applied here.
        return WebhookEvent.objects.get(event_id=event_id), True

    logger.info(
        "webhook.handled",
        extra={"event_id": event_id, "event_type": event_type, "status": event.status, "note": event.note},
    )
    return event, False

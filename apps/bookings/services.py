import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import CentreTest
from apps.core.exceptions import Conflict

from .models import Booking, BookingStatus, InvalidTransition

logger = logging.getLogger(__name__)

MAX_ADVANCE_BOOKING = timedelta(days=90)


class BookingError(Exception):
    """Validation failure for a booking request, keyed by field."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def create_booking(*, user, centre_id, test_id, appointment_at) -> Booking:
    now = timezone.now()
    if appointment_at <= now:
        raise BookingError("appointment_at", "Appointment must be in the future.")
    if appointment_at > now + MAX_ADVANCE_BOOKING:
        raise BookingError("appointment_at", "Appointments can be booked at most 90 days in advance.")

    offering = (
        CentreTest.objects.select_related("centre", "test")
        .filter(centre_id=centre_id, test_id=test_id, is_active=True, centre__is_active=True)
        .first()
    )
    if offering is None:
        raise BookingError("test_id", "This centre does not offer the selected test.")

    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user,
                centre=offering.centre,
                test=offering.test,
                appointment_at=appointment_at,
                amount=offering.price,  # server-side price; never trust a client amount
            )
    except IntegrityError:
        raise Conflict("You already have an active booking for this test at this centre and time.")

    logger.info("booking.created", extra={"booking_id": booking.pk, "user_id": user.pk})
    return booking


def cancel_booking(*, booking_id, user) -> Booking:
    with transaction.atomic():
        # Row lock so a concurrent payment confirmation can't interleave with the cancel.
        booking = Booking.objects.select_for_update().get(pk=booking_id, user=user)
        if booking.appointment_at <= timezone.now():
            raise Conflict("Past appointments cannot be cancelled.")
        was_confirmed = booking.status == BookingStatus.CONFIRMED
        booking.cancelled_at = timezone.now()
        try:
            booking.transition_to(BookingStatus.CANCELLED)
        except InvalidTransition as exc:
            raise Conflict(str(exc))

    logger.info(
        "booking.cancelled",
        extra={"booking_id": booking.pk, "refund_required": was_confirmed},
    )
    return booking

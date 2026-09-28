import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.payments.models import Payment, PaymentStatus

pytestmark = pytest.mark.django_db


def _pay(client, booking_id, outcome=None, key=None):
    payload = {"booking_id": booking_id}
    if outcome:
        payload["simulate_outcome"] = outcome
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/payments/", payload, format="json", headers=headers)


def test_successful_payment_confirms_booking(client_user, booking):
    resp = _pay(client_user, booking.id, "SUCCESS")
    assert resp.status_code == 201
    assert resp.data["status"] == "SUCCESS"
    assert resp.data["amount"] == "350.00"
    assert resp.data["booking_status"] == "CONFIRMED"


def test_failed_payment_marks_booking_failed_and_allows_retry(client_user, booking):
    resp = _pay(client_user, booking.id, "FAILED")
    assert resp.data["status"] == "FAILED"
    assert resp.data["failure_reason"]
    assert resp.data["booking_status"] == "FAILED"

    retry = _pay(client_user, booking.id, "SUCCESS")
    assert retry.status_code == 201
    assert retry.data["booking_status"] == "CONFIRMED"
    assert Payment.objects.filter(booking=booking).count() == 2


def test_random_outcome_uses_success_rate(client_user, booking, settings):
    settings.PAYMENT_SUCCESS_RATE = 1.0
    assert _pay(client_user, booking.id).data["status"] == "SUCCESS"


def test_cannot_pay_confirmed_booking_twice(client_user, booking):
    _pay(client_user, booking.id, "SUCCESS")
    resp = _pay(client_user, booking.id, "SUCCESS")
    assert resp.status_code == 409
    assert Payment.objects.filter(booking=booking).count() == 1


def test_cannot_pay_cancelled_booking(client_user, booking):
    client_user.post(f"/bookings/{booking.id}/cancel/")
    assert _pay(client_user, booking.id, "SUCCESS").status_code == 409


def test_cannot_pay_past_appointment(client_user, booking):
    Booking.objects.filter(pk=booking.pk).update(appointment_at=timezone.now())
    assert _pay(client_user, booking.id, "SUCCESS").status_code == 409


def test_pending_payment_blocks_parallel_attempt(client_user, booking):
    first = _pay(client_user, booking.id, "PENDING")
    assert first.data["status"] == "PENDING"
    assert first.data["booking_status"] == "PENDING"
    assert _pay(client_user, booking.id, "SUCCESS").status_code == 409


def test_cannot_pay_for_other_users_booking(client_other, booking):
    resp = _pay(client_other, booking.id, "SUCCESS")
    assert resp.status_code == 404
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_invalid_booking_id(client_user):
    assert _pay(client_user, 99999, "SUCCESS").status_code == 404
    assert client_user.post("/payments/", {"booking_id": "abc"}, format="json").status_code == 400
    assert client_user.post("/payments/", {}, format="json").status_code == 400


def test_invalid_simulated_outcome(client_user, booking):
    assert _pay(client_user, booking.id, "MAYBE").status_code == 400


def test_payment_requires_auth(api, booking):
    assert _pay(api, booking.id, "SUCCESS").status_code == 401


def test_idempotency_key_returns_original_payment(client_user, booking):
    first = _pay(client_user, booking.id, "SUCCESS", key="abc-123")
    second = _pay(client_user, booking.id, "SUCCESS", key="abc-123")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["id"] == second.data["id"]
    assert Payment.objects.count() == 1


def test_idempotency_key_reuse_for_other_booking(client_user, booking, offering, user):
    other = Booking.objects.create(
        user=user, centre=offering.centre, test=offering.test,
        appointment_at=booking.appointment_at.replace(hour=(booking.appointment_at.hour + 1) % 24),
        amount=offering.price,
    )
    _pay(client_user, booking.id, "SUCCESS", key="k1")
    assert _pay(client_user, other.id, "SUCCESS", key="k1").status_code == 422


def test_payment_list_is_scoped_to_user(client_user, client_other, booking):
    _pay(client_user, booking.id, "SUCCESS")
    assert client_user.get("/payments/").data["count"] == 1
    assert client_other.get("/payments/").data["count"] == 0
    payment_id = Payment.objects.get().id
    assert client_other.get(f"/payments/{payment_id}/").status_code == 404


def test_db_forbids_two_successful_payments_for_one_booking(booking, user):
    Payment.objects.create(booking=booking, user=user, amount=booking.amount, status="SUCCESS", provider_reference="a")
    with pytest.raises(IntegrityError):
        Payment.objects.create(
            booking=booking, user=user, amount=booking.amount, status=PaymentStatus.SUCCESS, provider_reference="b"
        )

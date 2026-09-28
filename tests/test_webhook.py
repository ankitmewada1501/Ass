import pytest

from apps.bookings.models import BookingStatus
from apps.payments.models import Payment, PaymentStatus, WebhookEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending_payment(client_user, booking):
    resp = client_user.post("/payments/", {"booking_id": booking.id, "simulate_outcome": "PENDING"}, format="json")
    return Payment.objects.get(pk=resp.data["id"])


def test_success_webhook_confirms_booking(send_webhook, pending_payment):
    resp = send_webhook("evt_1", "payment.succeeded", pending_payment.provider_reference, amount="350.00")
    assert resp.status_code == 200
    assert resp.data["duplicate"] is False
    assert resp.data["status"] == "PROCESSED"
    pending_payment.refresh_from_db()
    assert pending_payment.status == PaymentStatus.SUCCESS
    assert pending_payment.booking.status == BookingStatus.CONFIRMED


def test_failed_webhook_fails_booking(send_webhook, pending_payment):
    resp = send_webhook("evt_1", "payment.failed", pending_payment.provider_reference, failure_reason="Insufficient funds")
    assert resp.status_code == 200
    pending_payment.refresh_from_db()
    assert pending_payment.status == PaymentStatus.FAILED
    assert pending_payment.failure_reason == "Insufficient funds"
    assert pending_payment.booking.status == BookingStatus.FAILED


def test_repeated_event_is_idempotent(send_webhook, pending_payment):
    ref = pending_payment.provider_reference
    first = send_webhook("evt_dup", "payment.succeeded", ref)
    for _ in range(3):
        again = send_webhook("evt_dup", "payment.succeeded", ref)
        assert again.status_code == 200
        assert again.data["duplicate"] is True
    assert first.data["duplicate"] is False
    assert WebhookEvent.objects.count() == 1
    assert Payment.objects.count() == 1
    pending_payment.refresh_from_db()
    assert pending_payment.booking.status == BookingStatus.CONFIRMED


def test_conflicting_later_event_does_not_regress_state(send_webhook, pending_payment):
    ref = pending_payment.provider_reference
    send_webhook("evt_a", "payment.succeeded", ref)
    resp = send_webhook("evt_b", "payment.failed", ref)
    assert resp.status_code == 200
    assert resp.data["status"] == "IGNORED"
    pending_payment.refresh_from_db()
    assert pending_payment.status == PaymentStatus.SUCCESS
    assert pending_payment.booking.status == BookingStatus.CONFIRMED


def test_webhook_for_already_final_sync_payment_is_ignored(send_webhook, client_user, booking):
    resp = client_user.post("/payments/", {"booking_id": booking.id, "simulate_outcome": "SUCCESS"}, format="json")
    ref = resp.data["provider_reference"]
    hook = send_webhook("evt_x", "payment.succeeded", ref)
    assert hook.data["status"] == "IGNORED"
    assert hook.data["booking_status"] == "CONFIRMED"


def test_success_after_cancellation_does_not_resurrect_booking(send_webhook, client_user, pending_payment):
    client_user.post(f"/bookings/{pending_payment.booking_id}/cancel/")
    resp = send_webhook("evt_1", "payment.succeeded", pending_payment.provider_reference)
    assert resp.status_code == 200
    assert "refund" in resp.data["note"]
    pending_payment.refresh_from_db()
    assert pending_payment.status == PaymentStatus.SUCCESS
    assert pending_payment.booking.status == BookingStatus.CANCELLED


def test_amount_mismatch_is_not_applied(send_webhook, pending_payment):
    resp = send_webhook("evt_1", "payment.succeeded", pending_payment.provider_reference, amount="1.00")
    assert resp.data["status"] == "IGNORED"
    pending_payment.refresh_from_db()
    assert pending_payment.status == PaymentStatus.PENDING


def test_invalid_signature_rejected(send_webhook, pending_payment):
    resp = send_webhook("evt_1", "payment.succeeded", pending_payment.provider_reference, signature="deadbeef")
    assert resp.status_code == 401
    assert WebhookEvent.objects.count() == 0


def test_missing_signature_rejected(api, pending_payment):
    resp = api.post("/payments/webhook/", {"event_id": "e"}, format="json")
    assert resp.status_code == 401


def test_unknown_payment_reference_returns_404_and_is_not_recorded(send_webhook, db):
    resp = send_webhook("evt_1", "payment.succeeded", "mockpay_does_not_exist")
    assert resp.status_code == 404
    assert WebhookEvent.objects.count() == 0  # a provider retry can still succeed later


def test_malformed_event_rejected(send_webhook, pending_payment):
    resp = send_webhook("evt_1", "payment.refunded", pending_payment.provider_reference)
    assert resp.status_code == 400

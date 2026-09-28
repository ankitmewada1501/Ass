import pytest

from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def test_home_page_renders(api):
    resp = api.get("/")
    assert resp.status_code == 200
    assert b"EVE Diagnostics" in resp.content


@pytest.fixture
def pending_payment(client_user, booking):
    resp = client_user.post("/payments/", {"booking_id": booking.id, "simulate_outcome": "PENDING"}, format="json")
    return Payment.objects.get(pk=resp.data["id"])


def test_dev_webhook_disabled_without_debug(client_user, pending_payment, settings):
    settings.DEBUG = False
    payload = {"provider_reference": pending_payment.provider_reference, "outcome": "succeeded"}
    assert client_user.post("/payments/dev/simulate-webhook/", payload, format="json").status_code == 404


def test_dev_webhook_applies_and_replays_idempotently(client_user, pending_payment, settings):
    settings.DEBUG = True
    payload = {"provider_reference": pending_payment.provider_reference, "outcome": "succeeded", "event_id": "evt_ui"}
    first = client_user.post("/payments/dev/simulate-webhook/", payload, format="json")
    again = client_user.post("/payments/dev/simulate-webhook/", payload, format="json")
    assert first.data["duplicate"] is False and first.data["booking_status"] == "CONFIRMED"
    assert again.data["duplicate"] is True


def test_dev_webhook_only_for_own_payments(client_other, pending_payment, settings):
    settings.DEBUG = True
    payload = {"provider_reference": pending_payment.provider_reference, "outcome": "succeeded"}
    assert client_other.post("/payments/dev/simulate-webhook/", payload, format="json").status_code == 404

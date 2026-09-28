import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.payments.authentication import SIGNATURE_HEADER, compute_signature


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; keep tests independent.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="patient@example.com", password="S3cure-pass!", full_name="Pat Ient")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="other@example.com", password="S3cure-pass!", full_name="Other Person")


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        email="admin@example.com", password="S3cure-pass!", full_name="Admin", is_staff=True
    )


def _authed(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def client_user(user):
    return _authed(user)


@pytest.fixture
def client_other(other_user):
    return _authed(other_user)


@pytest.fixture
def client_staff(staff):
    return _authed(staff)


@pytest.fixture
def centre(db):
    return DiagnosticCentre.objects.create(name="EVE Koramangala", address="80 Feet Rd", city="Bengaluru")


@pytest.fixture
def cbc(db):
    return DiagnosticTest.objects.create(code="CBC", name="Complete Blood Count")


@pytest.fixture
def offering(centre, cbc):
    return CentreTest.objects.create(centre=centre, test=cbc, price=Decimal("350.00"))


@pytest.fixture
def future_slot():
    return (timezone.now() + timedelta(days=2)).replace(microsecond=0)


@pytest.fixture
def booking(user, offering, future_slot):
    return Booking.objects.create(
        user=user, centre=offering.centre, test=offering.test, appointment_at=future_slot, amount=offering.price
    )


@pytest.fixture
def send_webhook(api):
    """POST a correctly signed webhook event."""

    def _send(event_id, event_type, provider_reference, amount=None, signature=None, **extra):
        data = {"provider_reference": provider_reference, **extra}
        if amount is not None:
            data["amount"] = str(amount)
        body = json.dumps({"event_id": event_id, "type": event_type, "data": data}).encode()
        sig = signature if signature is not None else compute_signature(body)
        return api.post(
            "/payments/webhook/", data=body, content_type="application/json", headers={SIGNATURE_HEADER: sig}
        )

    return _send

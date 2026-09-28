from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus

pytestmark = pytest.mark.django_db


def _book(client, offering, when, **overrides):
    payload = {"centre_id": offering.centre_id, "test_id": offering.test_id, "appointment_at": when.isoformat()}
    payload.update(overrides)
    return client.post("/bookings/", payload, format="json")


def test_create_booking_uses_server_side_price(client_user, offering, future_slot):
    resp = _book(client_user, offering, future_slot, amount="1.00")  # client amount is ignored
    assert resp.status_code == 201
    assert resp.data["status"] == "PENDING"
    assert resp.data["amount"] == "350.00"


def test_booking_price_is_snapshotted(client_user, offering, future_slot):
    resp = _book(client_user, offering, future_slot)
    offering.price = "999.00"
    offering.save()
    assert Booking.objects.get(pk=resp.data["id"]).amount == 350


def test_booking_in_past_rejected(client_user, offering):
    resp = _book(client_user, offering, timezone.now() - timedelta(hours=1))
    assert resp.status_code == 400
    assert "appointment_at" in resp.data["error"]["details"]


def test_booking_too_far_ahead_rejected(client_user, offering):
    resp = _book(client_user, offering, timezone.now() + timedelta(days=120))
    assert resp.status_code == 400


def test_booking_test_not_offered_by_centre(client_user, offering, future_slot):
    resp = _book(client_user, offering, future_slot, test_id=9999)
    assert resp.status_code == 400
    assert "test_id" in resp.data["error"]["details"]


def test_booking_inactive_offering_rejected(client_user, offering, future_slot):
    offering.is_active = False
    offering.save()
    assert _book(client_user, offering, future_slot).status_code == 400


@pytest.mark.parametrize("payload", [{}, {"centre_id": "x", "test_id": 1, "appointment_at": "tomorrow"}])
def test_booking_invalid_payload(client_user, payload):
    assert client_user.post("/bookings/", payload, format="json").status_code == 400


def test_duplicate_active_booking_rejected(client_user, offering, future_slot):
    assert _book(client_user, offering, future_slot).status_code == 201
    resp = _book(client_user, offering, future_slot)
    assert resp.status_code == 409


def test_can_rebook_slot_after_cancelling(client_user, offering, future_slot):
    first = _book(client_user, offering, future_slot)
    client_user.post(f"/bookings/{first.data['id']}/cancel/")
    assert _book(client_user, offering, future_slot).status_code == 201


def test_users_only_see_own_bookings(client_user, client_other, booking):
    assert client_user.get("/bookings/").data["count"] == 1
    assert client_other.get("/bookings/").data["count"] == 0
    assert client_other.get(f"/bookings/{booking.id}/").status_code == 404


def test_status_filter(client_user, booking):
    assert client_user.get("/bookings/?status=pending").data["count"] == 1
    assert client_user.get("/bookings/?status=CONFIRMED").data["count"] == 0
    assert client_user.get("/bookings/?status=bogus").status_code == 400


def test_cancel_booking(client_user, booking):
    resp = client_user.post(f"/bookings/{booking.id}/cancel/")
    assert resp.status_code == 200
    assert resp.data["status"] == "CANCELLED"
    assert resp.data["cancelled_at"] is not None


def test_cancel_twice_conflicts(client_user, booking):
    client_user.post(f"/bookings/{booking.id}/cancel/")
    assert client_user.post(f"/bookings/{booking.id}/cancel/").status_code == 409


def test_cannot_cancel_someone_elses_booking(client_other, booking):
    assert client_other.post(f"/bookings/{booking.id}/cancel/").status_code == 404
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_staff_can_view_but_not_cancel_others_booking(client_staff, booking):
    assert client_staff.get(f"/bookings/{booking.id}/").status_code == 200
    assert client_staff.post(f"/bookings/{booking.id}/cancel/").status_code == 403


def test_cannot_cancel_past_appointment(client_user, booking):
    Booking.objects.filter(pk=booking.pk).update(appointment_at=timezone.now() - timedelta(hours=1))
    assert client_user.post(f"/bookings/{booking.id}/cancel/").status_code == 409


def test_state_machine_rejects_invalid_transition(booking):
    booking.status = BookingStatus.CANCELLED
    assert not booking.can_transition_to(BookingStatus.CONFIRMED)
    booking.status = BookingStatus.FAILED
    assert booking.can_transition_to(BookingStatus.CONFIRMED)


def test_unknown_booking_returns_404(client_user):
    assert client_user.get("/bookings/12345/").status_code == 404
    assert client_user.post("/bookings/12345/cancel/").status_code == 404

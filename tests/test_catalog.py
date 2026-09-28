import pytest

from apps.catalog.models import DiagnosticCentre

pytestmark = pytest.mark.django_db


def test_list_centres_is_public_and_includes_tests(api, offering):
    resp = api.get("/centres/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    centre = resp.data["results"][0]
    assert centre["tests"][0]["test"]["code"] == "CBC"
    assert centre["tests"][0]["price"] == "350.00"


def test_filter_centres_by_city_and_test(api, offering, cbc):
    DiagnosticCentre.objects.create(name="EVE Andheri", address="Link Rd", city="Mumbai")
    assert api.get("/centres/?city=bengaluru").data["count"] == 1
    assert api.get("/centres/?city=Mumbai").data["count"] == 1
    assert api.get(f"/centres/?test={cbc.id}").data["count"] == 1
    assert api.get("/centres/?test=abc").data["count"] == 0


def test_non_staff_cannot_create_centre(client_user):
    resp = client_user.post("/centres/", {"name": "X", "address": "Y", "city": "Z"}, format="json")
    assert resp.status_code == 403


def test_anonymous_cannot_create_centre(api):
    resp = api.post("/centres/", {"name": "X", "address": "Y", "city": "Z"}, format="json")
    assert resp.status_code == 401


def test_staff_manages_centre_and_offerings(client_staff, cbc):
    resp = client_staff.post("/centres/", {"name": "New", "address": "Addr", "city": "Pune"}, format="json")
    assert resp.status_code == 201
    centre_id = resp.data["id"]

    resp = client_staff.post(f"/centres/{centre_id}/tests/", {"test_id": cbc.id, "price": "299.00"}, format="json")
    assert resp.status_code == 201
    offering_id = resp.data["id"]

    dup = client_staff.post(f"/centres/{centre_id}/tests/", {"test_id": cbc.id, "price": "10.00"}, format="json")
    assert dup.status_code == 400

    resp = client_staff.patch(f"/centres/{centre_id}/tests/{offering_id}/", {"price": "320.00"}, format="json")
    assert resp.status_code == 200 and resp.data["price"] == "320.00"


@pytest.mark.parametrize("price", ["0", "-5", "abc"])
def test_offering_price_must_be_positive(client_staff, centre, cbc, price):
    resp = client_staff.post(f"/centres/{centre.id}/tests/", {"test_id": cbc.id, "price": price}, format="json")
    assert resp.status_code == 400


def test_delete_centre_soft_deactivates(client_staff, api, centre):
    assert client_staff.delete(f"/centres/{centre.id}/").status_code == 204
    centre.refresh_from_db()
    assert centre.is_active is False
    assert api.get(f"/centres/{centre.id}/").status_code == 404


def test_unknown_centre_returns_404(api):
    assert api.get("/centres/999/").status_code == 404
    assert api.get("/centres/999/tests/").status_code == 404

import pytest

pytestmark = pytest.mark.django_db


def test_signup_returns_tokens_and_user(api):
    resp = api.post(
        "/auth/signup/",
        {"email": "New@Example.com", "password": "S3cure-pass!", "full_name": "New User"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["user"]["email"] == "new@example.com"  # normalised
    assert resp.data["access"] and resp.data["refresh"]
    assert "password" not in resp.data["user"]


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"password": "S3cure-pass!", "full_name": "X"}, "email"),
        ({"email": "not-an-email", "password": "S3cure-pass!", "full_name": "X"}, "email"),
        ({"email": "a@b.com", "password": "123", "full_name": "X"}, "non_field_errors"),
        ({"email": "a@b.com", "password": "S3cure-pass!", "full_name": "   "}, "full_name"),
        ({"email": "a@b.com", "password": "S3cure-pass!", "full_name": "X", "phone": "abc"}, "phone"),
    ],
)
def test_signup_validation(api, payload, field):
    resp = api.post("/auth/signup/", payload, format="json")
    assert resp.status_code == 400
    assert field in resp.data["error"]["details"]


def test_signup_duplicate_email_case_insensitive(api, user):
    resp = api.post(
        "/auth/signup/", {"email": "PATIENT@example.com", "password": "S3cure-pass!", "full_name": "Dup"}, format="json"
    )
    assert resp.status_code == 400
    assert "email" in resp.data["error"]["details"]


def test_login_and_use_token(api, user):
    resp = api.post("/auth/login/", {"email": "Patient@Example.com", "password": "S3cure-pass!"}, format="json")
    assert resp.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    me = api.get("/auth/me/")
    assert me.status_code == 200
    assert me.data["email"] == user.email


def test_login_wrong_password(api, user):
    resp = api.post("/auth/login/", {"email": user.email, "password": "wrong"}, format="json")
    assert resp.status_code == 401


def test_protected_endpoint_requires_token(api):
    assert api.get("/bookings/").status_code == 401
    api.credentials(HTTP_AUTHORIZATION="Bearer garbage")
    assert api.get("/bookings/").status_code == 401


def test_login_is_rate_limited(api, user, settings):
    for _ in range(10):
        api.post("/auth/login/", {"email": user.email, "password": "wrong"}, format="json")
    resp = api.post("/auth/login/", {"email": user.email, "password": "wrong"}, format="json")
    assert resp.status_code == 429

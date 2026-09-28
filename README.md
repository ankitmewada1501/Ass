# EVE Diagnostics — Booking & Payments API

A backend service for booking diagnostic tests at diagnostic centres and paying for them
through a simulated payment provider, with an **idempotent payment webhook**.

**Stack:** Python · Django · Django REST Framework · SimpleJWT · PostgreSQL · Redis · drf-spectacular (OpenAPI) · pytest · Docker

---

## Contents

1. [Quick start](#quick-start)
2. [Project layout](#project-layout)
3. [API reference and examples](#api-reference-and-examples)
4. [Database design](#database-design)
5. [Booking and payment lifecycle](#booking-and-payment-lifecycle)
6. [Webhook idempotency](#webhook-idempotency)
7. [Edge cases handled](#edge-cases-handled)
8. [Tests](#tests)
9. [Assumptions](#assumptions)
10. [What I'd improve with more time](#what-id-improve-with-more-time)

---

## Quick start

### Option A — Docker (PostgreSQL + Redis)

```bash
docker compose up --build
docker compose exec web python manage.py seed_catalog          # sample centres & tests
docker compose exec web python manage.py createsuperuser       # staff user for catalogue writes
```

The API runs at http://localhost:8000. Interactive Swagger docs are at http://localhost:8000/docs/.

### Option B — Local Python (SQLite by default)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_catalog
python manage.py runserver
```

To use PostgreSQL locally, set `DATABASE_URL=postgres://user:pass@localhost:5432/eve`.
The other settings are listed in `.env.example`.

### Run the tests

```bash
pytest                                     # local
docker compose exec web pytest             # inside the container, against PostgreSQL
```

---

## Project layout

```
config/                 settings, root URLs
apps/
  core/                 cross-cutting: JSON logging, request-id middleware, error envelope,
                        pagination, permissions, health check
  accounts/             custom User (email login), signup / login / JWT
  catalog/              DiagnosticCentre, DiagnosticTest, CentreTest (priced offering)
  bookings/             Booking model + state machine, services.py (business rules)
  payments/             Payment, WebhookEvent, mock gateway, services.py, HMAC webhook auth
tests/                  pytest suite (auth, catalog, bookings, payments, webhook)
scripts/send_webhook.py acts as the payment provider and sends signed webhook events
```

**Design choice:** views stay thin. They handle HTTP, validation and status codes. The business
rules and transactions live in `services.py` in each app (`create_booking`, `cancel_booking`,
`create_payment`, `process_webhook_event`). The mapping from a payment result to a booking
status is written once, in `apply_payment_result`. Both the synchronous payment flow and the
webhook call it, so the two paths can't drift apart.

---

## API reference and examples

All error responses share one shape:

```json
{ "error": { "code": "conflict", "message": "Booking is CONFIRMED and cannot be paid for.", "details": null } }
```

Validation errors put the per-field messages in `details`. List endpoints are paginated
(`?page=`, `?page_size=` up to 100).

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup/` | – | Create an account. Returns the user and a JWT pair |
| POST | `/auth/login/` | – | Log in with email and password. Returns a JWT pair and the user |
| POST | `/auth/token/refresh/` | – | Exchange a refresh token for a new access token |
| GET | `/auth/me/` | JWT | Current user |
| GET | `/centres/` | – | List centres with their tests and prices. Filters: `?city=`, `?test=<id>`, `?search=` |
| GET | `/centres/{id}/` | – | Centre detail |
| POST/PATCH/DELETE | `/centres/` · `/centres/{id}/` | staff | Manage centres. DELETE deactivates the centre instead of removing it |
| GET | `/centres/{id}/tests/` | – | Tests offered by a centre, with prices |
| POST/PATCH/DELETE | `/centres/{id}/tests/` · `/centres/{id}/tests/{offering_id}/` | staff | Manage a centre's offerings and prices |
| GET/POST/PATCH | `/tests/` · `/tests/{id}/` | read: – / write: staff | Global test catalogue (`?search=`) |
| POST | `/bookings/` | JWT | Book a test |
| GET | `/bookings/` · `/bookings/{id}/` | JWT | Your bookings (`?status=`) |
| POST | `/bookings/{id}/cancel/` | JWT (owner) | Cancel a booking |
| POST | `/payments/` | JWT | Pay for a booking through the mock gateway (optional `Idempotency-Key` header) |
| GET | `/payments/` · `/payments/{id}/` | JWT | Your payment attempts |
| POST | `/payments/webhook/` | HMAC signature | Provider status callback (idempotent) |
| GET | `/docs/` · `/schema/` · `/health/` | – | Swagger UI, OpenAPI schema, health check |

### Walkthrough (curl)

```bash
B=http://localhost:8000

# 1. Sign up (login works the same way at /auth/login/ with email + password)
curl -s -X POST $B/auth/signup/ -H 'Content-Type: application/json' \
  -d '{"email":"asha@example.com","password":"S3cure-pass!","full_name":"Asha Rao"}'
# -> {"user": {...}, "access": "<JWT>", "refresh": "<JWT>"}
TOKEN=<access token>

# 2. Browse centres
curl -s "$B/centres/?city=Bengaluru"

# 3. Book. The amount is taken from the centre's price, never from the client.
curl -s -X POST $B/bookings/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-10-01T10:00:00+05:30"}'
# -> {"id":1, "amount":"350.00", "status":"PENDING", ...}

# 4a. Pay synchronously. simulate_outcome is SUCCESS | FAILED | PENDING, or omit it for a
#     random result (PAYMENT_SUCCESS_RATE, default 0.8).
curl -s -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 7f1c-booking-1-attempt-1' \
  -d '{"booking_id":1,"simulate_outcome":"SUCCESS"}'
# -> 201 {"status":"SUCCESS","booking_status":"CONFIRMED","provider_reference":"mockpay_...", ...}
#    Repeating the same request with the same Idempotency-Key -> 200 with the same payment.

# 4b. Or pay asynchronously: PENDING leaves the result to the provider's webhook
curl -s -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id":1,"simulate_outcome":"PENDING"}'
python scripts/send_webhook.py mockpay_<ref> succeeded --event-id evt_1
# <- 200 {"duplicate": false, "status": "PROCESSED", "note": "booking moved to CONFIRMED", ...}
python scripts/send_webhook.py mockpay_<ref> succeeded --event-id evt_1   # same event again
# <- 200 {"duplicate": true, ...}   nothing changes

# 5. Cancel
curl -s -X POST $B/bookings/1/cancel/ -H "Authorization: Bearer $TOKEN"
```

### Webhook contract

```http
POST /payments/webhook/
Content-Type: application/json
X-Webhook-Signature: <hex HMAC-SHA256 of the raw body, keyed with PAYMENT_WEBHOOK_SECRET>

{
  "event_id": "evt_123",                    // unique per event, the idempotency key
  "type": "payment.succeeded",              // or "payment.failed"
  "data": {
    "provider_reference": "mockpay_...",    // returned by POST /payments/
    "amount": "350.00",                     // optional, checked against the payment when sent
    "failure_reason": "Insufficient funds"  // optional, used for failed payments
  }
}
```

The status codes follow common provider retry rules:

| Code | When | Provider should |
|---|---|---|
| **200** | Processed, ignored as a no-op, or a duplicate | stop retrying |
| **400** | Malformed payload | stop retrying (fix the payload) |
| **401** | Missing or invalid signature | stop retrying |
| **404** | Unknown `provider_reference`. The event is **not** recorded | retry later |
| **5xx** | Unexpected error. The transaction is rolled back and nothing is recorded | retry later |

---

## Database design

```
User 1───* Booking *───1 DiagnosticCentre 1───* CentreTest *───1 DiagnosticTest
              │                                  (price, is_active)
              │ 1
              *
           Payment 1───* WebhookEvent
```

| Table | Key columns | Constraints and indexes |
|---|---|---|
| `accounts_user` | email (login), full_name, phone | `email` unique. Emails are stored lowercase |
| `catalog_diagnosticcentre` | name, address, city, pincode, is_active | unique (name, city). Index on city |
| `catalog_diagnostictest` | code, name, description | `code` unique |
| `catalog_centretest` | centre_id, test_id, **price**, is_active | unique (centre, test). CHECK price > 0 |
| `bookings_booking` | user_id, centre_id, test_id, appointment_at, **amount**, status, cancelled_at | CHECK amount > 0. **Partial unique** (user, centre, test, appointment_at) WHERE status IN (PENDING, CONFIRMED). Indexes (user, -created_at) and (status) |
| `payments_payment` | booking_id, user_id, amount, currency, status, provider_reference, idempotency_key, failure_reason | `provider_reference` unique. **Partial unique** (user, idempotency_key). **Partial unique** (booking) WHERE status = SUCCESS. **Partial unique** (booking) WHERE status = PENDING. CHECK amount > 0 |
| `payments_webhookevent` | **event_id**, event_type, payment_id, payload (JSON), status, note | `event_id` unique |

Why it's modelled this way:

- **Price is per centre.** `CentreTest` is the join between a centre and a test and holds that
  centre's price. The same test can cost different amounts at different centres.
- **The booking amount is a snapshot.** It is copied from `CentreTest.price` when the booking is
  made, so a later price change doesn't change what the patient owes.
- **Payments are separate from bookings.** A booking can have several attempts, for example a
  failed one followed by a successful one. This keeps an audit trail. The partial unique
  indexes make sure there is at most one successful payment and at most one in-flight payment
  per booking, and **the database enforces this**, not only application code.
- **Protected foreign keys and soft deletes.** Centres and offerings are deactivated instead of
  deleted. `on_delete=PROTECT` stops anyone deleting data that bookings or payments still
  point to.
- **WebhookEvent is an append-only ledger.** Its unique `event_id` is what makes the webhook
  idempotent, and it is useful for audits and debugging.

---

## Booking and payment lifecycle

| From \ To | CONFIRMED | FAILED | CANCELLED |
|---|---|---|---|
| **PENDING** (on create) | payment SUCCESS | payment FAILED | patient cancels |
| **FAILED** | retry payment SUCCESS | – | patient cancels |
| **CONFIRMED** | – | – | patient cancels (refund needed) |
| **CANCELLED** | – | – | – (final) |

- The transitions are listed in one table, `ALLOWED_TRANSITIONS` in `apps/bookings/models.py`.
  `Booking.transition_to()` rejects any move that isn't in it.
- `FAILED` means the last payment attempt failed. The patient can pay again. `CANCELLED` is final.
- Payment statuses are `PENDING → SUCCESS | FAILED`. **A payment in a final status never
  changes again.**

## Webhook idempotency

`process_webhook_event` in `apps/payments/services.py` works in layers:

1. **Fast path.** If `event_id` is already in `WebhookEvent`, return `200 duplicate: true`
   without doing anything.
2. **One transaction.** Take row locks (`SELECT … FOR UPDATE`) on the payment and its booking,
   apply the state change, and insert the `WebhookEvent` row, all in one database transaction.
3. **Race safety.** If two copies of the same event arrive at the same moment, both can pass
   step 1. The second one then fails on the unique `event_id` constraint, its whole transaction
   rolls back (including any state change), and it returns `duplicate: true`. **An event is
   recorded if and only if its effects were committed.**
4. **Semantic idempotency.** A *different* event for a payment that is already final is
   recorded as `IGNORED`. For example, a late `payment.failed` after `payment.succeeded` does
   not undo the success. This covers events that arrive out of order.
5. **Retries.** An event for an unknown payment returns 404 and is not recorded, so a provider
   retry can still succeed once the payment exists. An unexpected error rolls everything back
   and returns 5xx, so the provider retries.

`POST /payments/` is also idempotent. If the client sends an `Idempotency-Key` header,
repeating the request returns the original payment instead of charging again. Reusing a key
for a different booking returns 422.

---

## Edge cases handled

| Case | Behaviour |
|---|---|
| Invalid or missing fields, bad email, weak password, bad phone | 400 with per-field `details` |
| Duplicate signup (email match ignores case) | 400 |
| Missing or invalid JWT | 401 |
| Non-staff user writes to the catalogue | 403 |
| Viewing, paying for or cancelling **another user's** booking | 404. The booking's existence isn't revealed, so IDs can't be probed |
| Staff user tries to cancel someone else's booking | 403. Staff can view bookings but not act for the patient |
| Unknown booking, centre or payment ID | 404 |
| Appointment in the past or more than 90 days ahead | 400 |
| Centre doesn't offer the test, or the offering or centre is inactive | 400 |
| Same user books the same test, centre and slot twice while the first is active | 409 (enforced by a DB constraint) |
| Client sends an `amount` when booking | Ignored. The server uses the centre's price |
| Paying for a CONFIRMED or CANCELLED booking, or one whose appointment has passed | 409 |
| Second payment while one is PENDING | 409 (enforced by a DB constraint, even under concurrency) |
| Repeated `POST /payments/` with the same Idempotency-Key | 200 with the original payment |
| Failed payment | Booking becomes FAILED. The patient can retry |
| Repeated webhook event | 200 `duplicate: true`. No state change and no duplicate rows |
| Conflicting or out-of-order webhook event | Recorded as IGNORED. The final status stays as it was |
| Webhook amount differs from the payment | Recorded as IGNORED and logged as a warning |
| Payment succeeds after the booking was cancelled | Payment is marked SUCCESS, the booking stays CANCELLED, and a warning with `refund_required` is logged |
| Invalid webhook signature | 401 (the HMAC is compared in constant time) |
| Cancelling twice, or cancelling a past appointment | 409 |
| Cancel and payment confirmation at the same moment | Row locks make them run one after the other |
| Brute-force login or signup | Throttled: `auth` scope 10/min. `payments` scope 20/min. Default 60/min anonymous and 300/min per user |

---

## Tests

There are 66 tests in `tests/`, run with pytest-django. They cover:

- **Auth:** signup and login, field validation, email normalisation, token use, rate limiting
- **Catalogue:** public reads, filters, staff-only writes, price validation, soft delete
- **Bookings:** server-side price, price snapshot, date rules, duplicate slots, ownership,
  cancel rules, state machine
- **Payments:** success, failure and retry, double payment, cancelled or past bookings,
  ownership, idempotency keys, DB-level uniqueness
- **Webhook:** success and failure events, repeated events, conflicting events, cancelled
  bookings, amount mismatch, signature checks, unknown references, malformed payloads

Other bonus pieces: Docker and docker-compose, Swagger/OpenAPI, structured JSON logs with a
request ID (`X-Request-ID`), pagination, rate limiting (backed by Redis when `REDIS_URL` is
set), a retry-safe webhook, and a seed command.

---

## Assumptions

- **Price.** One price per (centre, test). Currency is INR. There are no discounts or taxes.
- **Sync vs async payments.** `POST /payments/` calls the mock gateway directly. The client can
  force an outcome with `simulate_outcome`, which keeps demos and tests predictable. `PENDING`
  simulates an async provider whose result arrives later through the webhook.
- **Retries.** A failed payment leaves the booking FAILED, and the patient can try again.
- **Slots.** There is no capacity model. Any future time within 90 days can be booked, and the
  only rule is that the same user can't book the same test, centre and time twice.
- **Cancellation.** Allowed until the appointment time. Cancelling a CONFIRMED booking would
  start a refund. That is only logged here, because refunds are out of scope.
- **Access.** The catalogue is public to read, and only staff can change it (through the API or
  Django admin at `/admin/`). Patients can only see their own bookings and payments.
- **Webhook security.** The webhook uses an HMAC shared secret, which is the common provider
  pattern. It does not use JWT.
- **Time zone.** Datetimes are stored in UTC and returned in the Asia/Kolkata time zone. Clients
  should send ISO-8601 with an offset.

## What I'd improve with more time

- **Background processing:** a Celery worker. The webhook would only record the event and reply
  200, and a task would apply it, with exponential-backoff retries and a dead-letter queue.
  A scheduled job would expire PENDING bookings and payments that are never paid.
- **Slot capacity:** a real availability model (centre opening hours and capacity per slot)
  with locking, so a centre can't be overbooked.
- **Refunds:** a refund workflow for cancelled CONFIRMED bookings and for payments that succeed
  after cancellation.
- **Concurrency tests:** threaded tests against PostgreSQL (parallel webhooks and parallel
  payments) to prove the locking and constraint behaviour, run in CI with GitHub Actions.
- **Caching:** cache the centre list in Redis, cleared whenever the catalogue changes.
- **Auth:** refresh-token rotation and a blacklist (logout), email verification, and roles
  beyond "staff".
- **Webhook replay protection:** a signed timestamp in the signature, and rejecting events
  older than a few minutes.
- **Observability:** metrics (Prometheus) and tracing. Settings split by environment. Linting
  (ruff) and type checks (mypy) in pre-commit.

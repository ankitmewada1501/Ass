# EVE Diagnostics - Booking & Payments API

Backend for booking diagnostic tests at centres and paying for them through a mock payment
provider. Built with Django, Django REST Framework, SimpleJWT, PostgreSQL and Redis.

## Running it

You need Docker. From the project folder:

```bash
docker compose up --build
```

In another terminal, load some sample centres/tests and create an admin user:

```bash
docker compose exec web python manage.py seed_catalog
docker compose exec web python manage.py createsuperuser
```

Then open:

- http://localhost:8000 - web app
- http://localhost:8000/docs/ - Swagger docs
- http://localhost:8000/admin/ - Django admin

To run the tests:

```bash
docker compose exec web pytest
```

Config is read from environment variables (see `.env.example`). The defaults in
`docker-compose.yml` are fine for running it locally.

## Web app

I added a small frontend at `/` so the flow can be tried without curl. It's plain HTML/CSS/JS
served by Django. You can browse centres, sign up, book a test, pay, and see your bookings and
payments.

On the payment step you can pick what the mock gateway should do (succeed, fail, stay pending,
or random). For a pending payment there are buttons to act as the provider and approve/decline
it through the webhook. On the Payments page, "Replay webhook" sends the same event again, so
you can see that a duplicate event doesn't change anything.

These provider buttons call `POST /payments/dev/simulate-webhook/`. That endpoint only works when
`DEBUG` is on, and only for the logged-in user's own payments.

## Project structure

```
config/          settings and urls
apps/core/       logging, request id middleware, error format, pagination, permissions
apps/accounts/   user model (login with email), signup/login
apps/catalog/    centres, tests and per-centre prices
apps/bookings/   booking model, status rules, booking logic
apps/payments/   payments, webhook events, mock gateway, webhook handling
apps/web/        frontend
tests/           pytest tests
scripts/         send_webhook.py - sends a signed webhook like a real provider would
```

Views are kept thin. The actual logic is in `services.py` inside bookings and payments. The part
that decides what happens to a booking after a payment result is one function
(`apply_payment_result`), and both the normal payment flow and the webhook use it.

## API

Errors always come back in the same format:

```json
{"error": {"code": "conflict", "message": "Booking is CONFIRMED and cannot be paid for.", "details": null}}
```

For validation errors, `details` has the messages per field. Lists are paginated with `?page=`
and `?page_size=` (max 100).

| Method | Endpoint | Auth | What it does |
|---|---|---|---|
| POST | `/auth/signup/` | - | create account, returns user + tokens |
| POST | `/auth/login/` | - | login with email/password, returns tokens |
| POST | `/auth/token/refresh/` | - | get a new access token |
| GET | `/auth/me/` | JWT | current user |
| GET | `/centres/` | - | centres with their tests and prices. Filters: `city`, `test`, `search` |
| GET | `/centres/{id}/` | - | one centre |
| GET | `/centres/{id}/tests/` | - | tests offered by a centre |
| POST/PATCH/DELETE | `/centres/`, `/centres/{id}/tests/` ... | staff | manage centres and prices (delete only deactivates) |
| GET/POST/PATCH | `/tests/` | staff for writes | list of test types |
| POST | `/bookings/` | JWT | book a test |
| GET | `/bookings/`, `/bookings/{id}/` | JWT | your bookings, filter with `?status=` |
| POST | `/bookings/{id}/cancel/` | JWT | cancel your booking |
| POST | `/payments/` | JWT | pay for a booking (mock) |
| GET | `/payments/`, `/payments/{id}/` | JWT | your payments |
| POST | `/payments/webhook/` | signature | payment status from the provider |

### Example

```bash
B=http://localhost:8000

# sign up
curl -X POST $B/auth/signup/ -H 'Content-Type: application/json' \
  -d '{"email":"asha@example.com","password":"S3cure-pass!","full_name":"Asha Rao"}'
# copy "access" from the response
TOKEN=...

# list centres in a city
curl "$B/centres/?city=Bengaluru"

# book (amount is taken from the centre's price, not from the request)
curl -X POST $B/bookings/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-10-01T10:00:00+05:30"}'

# pay
curl -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: booking-1-try-1' \
  -d '{"booking_id":1,"simulate_outcome":"SUCCESS"}'

# cancel
curl -X POST $B/bookings/1/cancel/ -H "Authorization: Bearer $TOKEN"
```

`simulate_outcome` can be `SUCCESS`, `FAILED` or `PENDING`. If you leave it out the result is
random (80% success by default, `PAYMENT_SUCCESS_RATE`). `PENDING` means the result will come
later through the webhook.

If the same request is sent again with the same `Idempotency-Key`, you get the first payment back
instead of a second charge.

### Webhook

The provider sends:

```
POST /payments/webhook/
X-Webhook-Signature: <HMAC-SHA256 of the raw body using PAYMENT_WEBHOOK_SECRET>

{
  "event_id": "evt_123",
  "type": "payment.succeeded",          (or "payment.failed")
  "data": {
    "provider_reference": "mockpay_...",
    "amount": "350.00",                 (optional)
    "failure_reason": "..."             (optional)
  }
}
```

To try it from the terminal, pay with `"simulate_outcome":"PENDING"` and then:

```bash
docker compose exec web python scripts/send_webhook.py <provider_reference> succeeded --event-id evt_1
```

Run the same command again and the response says `"duplicate": true`.

Responses: 200 when handled (including duplicates), 400 for a bad payload, 401 for a bad
signature, and 404 if the payment reference isn't known. For 404 the event isn't saved, so the
provider can retry later.

## Database design

```
User 1---* Booking *---1 DiagnosticCentre 1---* CentreTest *---1 DiagnosticTest
              |                                  (price)
              1
              *
           Payment 1---* WebhookEvent
```

- **User**: login is the email (unique, stored lowercase).
- **DiagnosticCentre**: name, address, city, pincode, is_active. Name + city is unique.
- **DiagnosticTest**: code (unique), name, description.
- **CentreTest**: which centre offers which test and at what price. Unique on (centre, test),
  price must be > 0. Different centres can charge differently for the same test.
- **Booking**: user, centre, test, appointment time, amount, status. The amount is copied from
  the price when booking, so changing the price later doesn't affect existing bookings.
  A partial unique index stops the same user booking the same test/centre/time twice while
  the first one is still active.
- **Payment**: every payment attempt for a booking (a booking can have a failed attempt and
  then a successful one). Partial unique indexes allow only one successful and one pending
  payment per booking, so double charging is blocked by the database itself. Also stores the
  provider reference and the idempotency key.
- **WebhookEvent**: every webhook event handled. `event_id` is unique, which is what stops the
  same event from being applied twice.

Centres and offerings are deactivated, not deleted, and foreign keys use `PROTECT`, so old
bookings and payments never lose their data.

## Booking status

A booking starts as `PENDING`.

- payment succeeds -> `CONFIRMED`
- payment fails -> `FAILED` (the user can pay again, and a later success confirms it)
- user cancels -> `CANCELLED` (possible from PENDING, FAILED or CONFIRMED, and it's final)

Allowed moves are defined in one place (`ALLOWED_TRANSITIONS` in `apps/bookings/models.py`) and
anything else is rejected. Once a payment is `SUCCESS` or `FAILED` it never changes again.

## How the webhook avoids duplicates

1. If the `event_id` is already saved, return 200 with `duplicate: true` and do nothing.
2. Otherwise lock the payment and booking rows, apply the change and save the event, all in one
   transaction.
3. If two copies of the same event arrive at the same moment, the second one fails on the
   unique `event_id`, its transaction is rolled back, and it's treated as a duplicate. So an
   event is only saved if its changes were saved too.
4. If a different event comes for a payment that is already final (e.g. `failed` after
   `succeeded`), it's saved as `IGNORED` and nothing changes.

## Edge cases

- Invalid input (missing fields, bad email, weak password, wrong types) gives 400 with field
  errors.
- No token or a bad token gives 401. A normal user trying to change centres/prices gets 403.
- Another user's booking or payment returns 404, so booking ids can't be guessed.
- Unknown booking/centre/payment ids return 404.
- An appointment in the past or more than 90 days ahead is rejected, and so is a test the
  centre doesn't offer.
- Booking the same slot twice, paying for a confirmed/cancelled/past booking, or starting a
  second payment while one is pending all give 409.
- A failed payment marks the booking FAILED and the user can retry.
- Repeated webhook events are ignored, and so is a webhook whose amount doesn't match.
- If a payment succeeds after the booking was cancelled, the booking stays cancelled and a
  warning is logged saying a refund is needed.
- Cancelling twice or cancelling a past appointment gives 409. Cancel and payment can't run
  over each other because both lock the booking row.
- Login/signup is rate limited (10/min), and payments are limited to 20/min.

## Tests

70 tests with pytest, covering auth, catalogue, bookings, payments, the webhook (duplicates,
conflicting events, bad signatures, unknown references) and the demo endpoint.

```bash
docker compose exec web pytest
```

Other extras: Docker, Swagger docs, JSON logs with a request id, pagination, rate limiting with
Redis, and a seed command.

## Assumptions

- One price per test per centre, in INR, no discounts or taxes.
- The mock gateway answers straight away. You can force the result for testing, or choose
  `PENDING` to simulate a provider that confirms later through the webhook.
- There's no slot capacity. Any future time in the next 90 days can be booked.
- Cancelling is allowed until the appointment time. Refunds aren't implemented, only logged.
- Anyone can view centres and tests. Only staff users can edit them (API or admin).
- The webhook is authenticated with a shared secret signature, not JWT, because that's how
  payment providers usually do it.
- Times are stored in UTC and returned in IST. Clients should send ISO dates with a timezone.

## What I would improve with more time

- Process webhooks in a Celery worker with retries, and auto-expire bookings that are never paid.
- Proper slots with centre timings and capacity, so a centre can't be overbooked.
- A refund flow for cancelled paid bookings.
- Tests that run parallel requests on PostgreSQL to check the locking, plus CI on GitHub Actions.
- Cache the centre list in Redis.
- Logout with token blacklisting and email verification.
- A timestamp in the webhook signature to block replaying old events.
- Linting (ruff) and type checks.

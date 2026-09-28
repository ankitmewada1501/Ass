#!/usr/bin/env python3
"""
Act as the payment provider: send a signed webhook event to the API.

    python scripts/send_webhook.py mockpay_abc123 succeeded
    python scripts/send_webhook.py mockpay_abc123 failed --event-id evt_42 --reason "Insufficient funds"

Re-run with the same --event-id to see idempotency in action.
"""

import argparse
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("provider_reference")
    parser.add_argument("outcome", choices=["succeeded", "failed"])
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--amount", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--url", default=os.environ.get("API_URL", "http://localhost:8000") + "/payments/webhook/")
    parser.add_argument("--secret", default=os.environ.get("PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret"))
    args = parser.parse_args()

    data = {"provider_reference": args.provider_reference}
    if args.amount:
        data["amount"] = args.amount
    if args.reason:
        data["failure_reason"] = args.reason
    event = {"event_id": args.event_id or f"evt_{uuid.uuid4().hex}", "type": f"payment.{args.outcome}", "data": data}
    body = json.dumps(event).encode()
    signature = hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()

    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
    print(f"-> {event}")
    try:
        with urllib.request.urlopen(request) as resp:
            print(f"<- {resp.status} {resp.read().decode()}")
    except urllib.error.HTTPError as exc:
        print(f"<- {exc.code} {exc.read().decode()}")


if __name__ == "__main__":
    main()

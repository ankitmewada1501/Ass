"""A stand-in for a real payment provider (Razorpay, Stripe, ...)."""

import random
import uuid
from dataclasses import dataclass

from django.conf import settings

from .models import PaymentStatus


@dataclass(frozen=True)
class ChargeResult:
    provider_reference: str
    status: str  # a PaymentStatus value
    failure_reason: str = ""


class MockPaymentGateway:
    def new_reference(self) -> str:
        return f"mockpay_{uuid.uuid4().hex}"

    def charge(self, *, reference: str, amount, forced_outcome: str | None = None) -> ChargeResult:
        """
        Simulate a charge. `forced_outcome` makes the result deterministic
        (SUCCESS / FAILED, or PENDING to simulate an async provider that will
        report the final result later via webhook). Otherwise the outcome is
        random with probability PAYMENT_SUCCESS_RATE of success.
        """
        outcome = forced_outcome
        if outcome is None:
            outcome = PaymentStatus.SUCCESS if random.random() < settings.PAYMENT_SUCCESS_RATE else PaymentStatus.FAILED
        reason = "Card declined by issuer (simulated)." if outcome == PaymentStatus.FAILED else ""
        return ChargeResult(provider_reference=reference, status=outcome, failure_reason=reason)


gateway = MockPaymentGateway()

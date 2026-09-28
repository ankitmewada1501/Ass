import hashlib
import hmac

from django.conf import settings

SIGNATURE_HEADER = "X-Webhook-Signature"


def compute_signature(body: bytes, secret: str | None = None) -> str:
    secret = secret if secret is not None else settings.PAYMENT_WEBHOOK_SECRET
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def is_valid_signature(body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 of the raw body with the shared secret, compared in constant time."""
    if not signature:
        return False
    return hmac.compare_digest(compute_signature(body), signature)

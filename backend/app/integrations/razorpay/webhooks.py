"""Webhook signature verification and event parsing.

Verified against `razorpay==2.0.1`'s `razorpay/utility/utility.py`:
`Utility.verify_webhook_signature(body, signature, secret)` computes an
HMAC-SHA256 hex digest of `body` keyed with `secret` and compares it
(constant-time, via `hmac.compare_digest`) against `signature`, raising
`SignatureVerificationError` on a mismatch. Confirmed from source that
`verify_signature` does `body = bytes(body, 'utf-8')` internally -- `body`
**must** be a `str` (the raw request body decoded as UTF-8 text), not a
`bytes` object, or that line raises a `TypeError`.

`Utility` doesn't use `self.client` for this particular method (only its
sibling `verify_payment_signature`/`verify_payment_link_signature` do, as a
fallback secret source) -- so verifying a webhook needs no authenticated
Razorpay client, just the webhook secret from `RAZORPAY_WEBHOOK_SECRET`.

Per the docs (https://razorpay.com/docs/webhooks/validate-test/), the
signature arrives in the `X-Razorpay-Signature` header, and
`x-razorpay-event-id` is unique per event for deduplication.
"""

from __future__ import annotations

import json

from razorpay.errors import SignatureVerificationError
from razorpay.utility.utility import Utility

from app.integrations.razorpay.exceptions import RazorpayWebhookSignatureError

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "x-razorpay-event-id"


def verify_webhook_signature(raw_body: str, signature: str, secret: str) -> None:
    """Raises RazorpayWebhookSignatureError if `signature` doesn't match
    the HMAC-SHA256 of `raw_body` keyed with `secret`. `raw_body` must be
    the exact, unparsed request body as UTF-8 text (see module docstring)."""
    try:
        Utility().verify_webhook_signature(raw_body, signature, secret)
    except SignatureVerificationError as exc:
        raise RazorpayWebhookSignatureError(str(exc)) from exc


def parse_webhook_payload(raw_body: str) -> dict:
    """Only call after `verify_webhook_signature` has succeeded."""
    return json.loads(raw_body)

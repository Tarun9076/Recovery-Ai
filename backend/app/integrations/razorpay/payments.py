"""Payment read operations.

Verified against `razorpay==2.0.1`'s `razorpay/resources/payment.py`:
`client.payment.fetch(payment_id)` -> `GET /v1/payments/{id}`.
"""

from __future__ import annotations

from app.integrations.razorpay.exceptions import translate_sdk_error


def get_payment(client, payment_id: str) -> dict:
    """Fetches a payment's current state from Razorpay."""
    try:
        return client.payment.fetch(payment_id)
    except Exception as exc:
        raise translate_sdk_error(exc) from exc


def get_payment_details(client, payment_id: str) -> dict:
    """Same call as `get_payment` -- Razorpay exposes a single fetch-a-
    payment endpoint (`GET /v1/payments/{id}`); there is no separate
    "details" endpoint to distinguish this from `get_payment`. Kept as a
    distinct function only because the spec names both operations."""
    return get_payment(client, payment_id)


def verify_payment(client, payment_id: str) -> bool:
    """Confirms whether a payment actually succeeded by fetching its
    current status. Razorpay Payment Links (what this integration creates)
    don't produce the order_id/payment_id/signature triple that
    `Utility.verify_payment_signature` checks -- that flow is specific to
    the Checkout.js embedded-order integration, which this project does not
    use. The authoritative way to confirm a Payment-Link-originated payment
    is to check its status via the Payments API, which is what this does."""
    payment = get_payment(client, payment_id)
    return payment.get("status") == "captured"

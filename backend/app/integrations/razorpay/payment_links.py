"""Payment Link operations.

Verified against `razorpay==2.0.1`'s `razorpay/resources/payment_link.py`
(`create`/`fetch`/`cancel` map to `POST/GET /v1/payment_links/` and
`POST /v1/payment_links/{id}/cancel`) and the official docs at
https://razorpay.com/docs/api/payments/payment-links/create-standard/,
whose documented request fields this module's `create_payment_link`
payload is built from (amount in the smallest currency unit, description
capped at 2048 chars, reference_id capped at 40 chars, customer/notify/
reminder_enable as shown in the docs' own example payload).
"""

from __future__ import annotations

from app.integrations.razorpay.exceptions import translate_sdk_error


def _to_smallest_currency_unit(amount: float) -> int:
    """The docs' own example: to receive $300 (or ₹300), send 30000 -- i.e.
    amount * 100, rounded to the nearest integer subunit."""
    return round(amount * 100)


def create_payment_link(
    client, *, amount: float, currency: str, description: str,
    customer_name: str, customer_email: str, customer_contact: str,
    reference_id: str, notes: dict | None = None,
) -> dict:
    payload = {
        "amount": _to_smallest_currency_unit(amount),
        "currency": currency,
        "description": description[:2048],
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_contact,
        },
        "notify": {"sms": True, "email": True},
        "reminder_enable": True,
        "reference_id": reference_id[:40],
        "notes": notes or {},
    }
    try:
        return client.payment_link.create(payload)
    except Exception as exc:
        raise translate_sdk_error(exc) from exc


def fetch_payment_link(client, payment_link_id: str) -> dict:
    try:
        return client.payment_link.fetch(payment_link_id)
    except Exception as exc:
        raise translate_sdk_error(exc) from exc


def cancel_payment_link(client, payment_link_id: str) -> dict:
    """Only valid on a link that hasn't been paid yet (per the docs)."""
    try:
        return client.payment_link.cancel(payment_link_id)
    except Exception as exc:
        raise translate_sdk_error(exc) from exc

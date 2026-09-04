"""Tests for app/integrations/razorpay/ -- using stub SDK objects (never a
real network call; the actual Razorpay test-mode API was verified manually
against real credentials during development, see docs/architecture.md).

The stubs mimic the razorpay==2.0.1 SDK's *exact* verified behavior (see
this project's integrations/razorpay module docstrings for the source
citations): `client.payment_link.create/fetch/cancel`, `client.payment.fetch`,
and the BadRequestError/GatewayError/ServerError exception shapes.
"""

import pytest
import requests
from razorpay.errors import BadRequestError, GatewayError, ServerError

from app.integrations.razorpay import payment_links, payments, webhooks
from app.integrations.razorpay.exceptions import (
    RazorpayGatewayError,
    RazorpayNetworkError,
    RazorpayServerError,
    RazorpayTimeoutError,
    RazorpayValidationError,
    RazorpayWebhookSignatureError,
    translate_sdk_error,
)


class _StubPaymentLinkResource:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.last_create_payload = None

    def create(self, data):
        self.last_create_payload = data
        if self._exc:
            raise self._exc
        return self._response

    def fetch(self, payment_link_id):
        if self._exc:
            raise self._exc
        return self._response

    def cancel(self, payment_link_id):
        if self._exc:
            raise self._exc
        return self._response


class _StubPaymentResource:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def fetch(self, payment_id):
        if self._exc:
            raise self._exc
        return self._response


class _StubClient:
    def __init__(self, payment_link=None, payment=None):
        self.payment_link = payment_link
        self.payment = payment


# -- exception translation ---------------------------------------------

def test_translate_bad_request_error():
    result = translate_sdk_error(BadRequestError("invalid amount"))
    assert isinstance(result, RazorpayValidationError)
    assert "invalid amount" in str(result)


def test_translate_gateway_error():
    assert isinstance(translate_sdk_error(GatewayError("bank down")), RazorpayGatewayError)


def test_translate_server_error():
    assert isinstance(translate_sdk_error(ServerError("oops")), RazorpayServerError)


def test_translate_timeout():
    assert isinstance(translate_sdk_error(requests.exceptions.Timeout("timed out")), RazorpayTimeoutError)


def test_translate_connection_error():
    assert isinstance(translate_sdk_error(requests.exceptions.ConnectionError("no route")), RazorpayNetworkError)


def test_translate_unknown_exception_falls_back_to_base():
    from app.integrations.razorpay.exceptions import RazorpayIntegrationError
    result = translate_sdk_error(ValueError("something else"))
    assert type(result) is RazorpayIntegrationError


# -- payment_links.py ----------------------------------------------------

def test_create_payment_link_converts_amount_to_paise():
    stub = _StubPaymentLinkResource(response={"id": "plink_x", "short_url": "https://rzp.io/x", "status": "created"})
    client = _StubClient(payment_link=stub)

    result = payment_links.create_payment_link(
        client, amount=300.0, currency="INR", description="test",
        customer_name="A", customer_email="a@example.com", customer_contact="+919876543210",
        reference_id="ref-1",
    )
    assert stub.last_create_payload["amount"] == 30000  # ₹300 -> 30000 paise
    assert result["id"] == "plink_x"


def test_create_payment_link_truncates_long_fields():
    stub = _StubPaymentLinkResource(response={"id": "plink_x", "short_url": "u", "status": "created"})
    client = _StubClient(payment_link=stub)

    payment_links.create_payment_link(
        client, amount=100.0, currency="INR", description="x" * 3000,
        customer_name="A", customer_email="a@example.com", customer_contact="+919876543210",
        reference_id="y" * 100,
    )
    assert len(stub.last_create_payload["description"]) == 2048
    assert len(stub.last_create_payload["reference_id"]) == 40


def test_create_payment_link_wraps_sdk_error():
    client = _StubClient(payment_link=_StubPaymentLinkResource(exc=BadRequestError("Recurring digits in customer contact are disallowed")))
    with pytest.raises(RazorpayValidationError):
        payment_links.create_payment_link(
            client, amount=100.0, currency="INR", description="x",
            customer_name="A", customer_email="a@example.com", customer_contact="+919999999999",
            reference_id="ref-2",
        )


def test_fetch_and_cancel_payment_link():
    stub = _StubPaymentLinkResource(response={"id": "plink_x", "status": "cancelled"})
    client = _StubClient(payment_link=stub)
    assert payment_links.fetch_payment_link(client, "plink_x")["id"] == "plink_x"
    assert payment_links.cancel_payment_link(client, "plink_x")["status"] == "cancelled"


# -- payments.py -----------------------------------------------------------

def test_get_payment_and_details_are_the_same_call():
    stub = _StubPaymentResource(response={"id": "pay_x", "status": "captured"})
    client = _StubClient(payment=stub)
    assert payments.get_payment(client, "pay_x") == payments.get_payment_details(client, "pay_x")


def test_verify_payment_true_only_when_captured():
    captured_client = _StubClient(payment=_StubPaymentResource(response={"id": "pay_x", "status": "captured"}))
    assert payments.verify_payment(captured_client, "pay_x") is True

    failed_client = _StubClient(payment=_StubPaymentResource(response={"id": "pay_y", "status": "failed"}))
    assert payments.verify_payment(failed_client, "pay_y") is False


def test_get_payment_wraps_sdk_error():
    client = _StubClient(payment=_StubPaymentResource(exc=ServerError("boom")))
    with pytest.raises(RazorpayServerError):
        payments.get_payment(client, "pay_x")


# -- webhooks.py -------------------------------------------------------

def test_verify_webhook_signature_accepts_valid_signature():
    import hashlib
    import hmac as hmac_module

    secret = "whsec_test"
    body = '{"event":"payment_link.paid"}'
    signature = hmac_module.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    webhooks.verify_webhook_signature(body, signature, secret)  # must not raise


def test_verify_webhook_signature_rejects_bad_signature():
    with pytest.raises(RazorpayWebhookSignatureError):
        webhooks.verify_webhook_signature('{"event":"x"}', "0" * 64, "whsec_test")


def test_parse_webhook_payload():
    payload = webhooks.parse_webhook_payload('{"event": "payment_link.paid", "payload": {}}')
    assert payload["event"] == "payment_link.paid"

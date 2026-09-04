import uuid

import pytest

from app.integrations.razorpay.exceptions import RazorpayValidationError
from app.services.payment_provider import (
    MockPaymentProvider,
    PaymentProvider,
    RazorpayPaymentProvider,
    get_payment_provider,
)


def _call(provider, **overrides):
    kwargs = dict(
        payment_id=uuid.uuid4(), amount=100.0, currency="INR",
        customer_name="Test Customer", customer_email="a@example.com", customer_contact="+919876543210",
        reference_id="ref-1",
    )
    kwargs.update(overrides)
    return provider.create_recovery_link(**kwargs)


def test_mock_provider_response_shape():
    response = _call(MockPaymentProvider())
    assert response["success"] is True
    assert response["status"] == "created"
    assert response["payment_link_id"].startswith("plink_")
    assert response["payment_link"].startswith("https://")
    assert response["payment_link_id"] in response["payment_link"]


def test_mock_provider_generates_unique_links():
    provider = MockPaymentProvider()
    ids = {_call(provider)["payment_link_id"] for _ in range(20)}
    assert len(ids) == 20


def test_mock_provider_is_a_payment_provider():
    assert isinstance(MockPaymentProvider(), PaymentProvider)


def test_get_payment_provider_defaults_to_mock():
    """Spec section 9: the app must keep working in mock mode -- this is
    also what runs when RAZORPAY_MODE is unset/absent."""
    assert isinstance(get_payment_provider(), MockPaymentProvider)


def test_get_payment_provider_returns_razorpay_in_test_mode(monkeypatch):
    from app.core import config

    monkeypatch.setenv("RAZORPAY_MODE", "test")
    config.get_settings.cache_clear()
    try:
        assert isinstance(get_payment_provider(), RazorpayPaymentProvider)
    finally:
        config.get_settings.cache_clear()


class _FakePaymentLinkResource:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def create(self, data):
        if self._exc:
            raise self._exc
        return self._response


class _FakeClient:
    def __init__(self, payment_link):
        self.payment_link = payment_link


def test_razorpay_provider_success_shape():
    fake_client = _FakeClient(_FakePaymentLinkResource(
        response={"id": "plink_real123", "short_url": "https://rzp.io/abc", "status": "created"}
    ))
    provider = RazorpayPaymentProvider(client=fake_client)
    response = _call(provider)
    assert response == {
        "success": True, "payment_link_id": "plink_real123",
        "payment_link": "https://rzp.io/abc", "status": "created",
    }


def test_razorpay_provider_propagates_translated_errors():
    from razorpay.errors import BadRequestError

    fake_client = _FakeClient(_FakePaymentLinkResource(exc=BadRequestError("Recurring digits in customer contact are disallowed")))
    provider = RazorpayPaymentProvider(client=fake_client)
    with pytest.raises(RazorpayValidationError):
        _call(provider)


def test_razorpay_provider_without_injected_client_requires_credentials(monkeypatch):
    from app.core import config
    from app.integrations.razorpay.exceptions import RazorpayAuthenticationError
    from app.integrations.razorpay import client as razorpay_client_module

    monkeypatch.setenv("RAZORPAY_KEY_ID", "")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "")
    config.get_settings.cache_clear()
    razorpay_client_module._client = None
    try:
        provider = RazorpayPaymentProvider()
        with pytest.raises(RazorpayAuthenticationError):
            _call(provider)
    finally:
        config.get_settings.cache_clear()


def test_razorpay_client_refuses_a_non_test_key(monkeypatch):
    """Security audit (Phase 8): live Razorpay execution is out of scope for
    this whole project -- a key without the `rzp_test_` prefix (i.e. a live
    key, `rzp_live_...`) must never be usable, even if RAZORPAY_MODE=test."""
    from app.core import config
    from app.integrations.razorpay.exceptions import RazorpayAuthenticationError
    from app.integrations.razorpay import client as razorpay_client_module

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_someRealKeyId")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "someRealSecret")
    config.get_settings.cache_clear()
    razorpay_client_module._client = None
    try:
        with pytest.raises(RazorpayAuthenticationError, match="test-mode key"):
            razorpay_client_module.get_razorpay_client()
    finally:
        config.get_settings.cache_clear()
        razorpay_client_module._client = None

"""Provider abstraction for actually delivering a recovery action (a
payment link, a retry, etc.) to a customer. Two implementations share one
interface: `MockPaymentProvider` (Phase 4, still the default) and
`RazorpayPaymentProvider` (Phase 5, real Razorpay test-mode API calls via
`app/integrations/razorpay/`) -- `campaign_service.py` never needs to know
which one it's talking to.

Creating a link is a delivery event, not a financial one: `create_recovery_link`
returning `success: True` means a payment link was generated, never that the
customer paid. See `RecoveryCampaign`'s docstring, and
`app/integrations/razorpay/webhooks.py` for the one legitimate path
(a verified webhook) that may ever record an actual recovery.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.integrations.razorpay.exceptions import RazorpayTimeoutError


class PaymentProvider(ABC):
    @abstractmethod
    def create_recovery_link(
        self, *, payment_id: uuid.UUID, amount: float, currency: str,
        customer_name: str, customer_email: str, customer_contact: str, reference_id: str,
    ) -> dict:
        """Returns at least {success, payment_link_id, payment_link, status}.
        May raise an `app.integrations.razorpay.exceptions.RazorpayIntegrationError`
        subclass on failure -- callers (see `campaign_service._execute_campaign`)
        catch that and record a FAILED action rather than letting it propagate."""
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    """Simulation only -- generates a fake link deterministically shaped
    like a real one, makes no network call, and never fails (there is no
    real payment gateway behind it to fail)."""

    def create_recovery_link(
        self, *, payment_id: uuid.UUID, amount: float, currency: str,
        customer_name: str, customer_email: str, customer_contact: str, reference_id: str,
    ) -> dict:
        link_id = f"plink_{uuid.uuid4().hex[:14]}"
        return {
            "success": True,
            "payment_link_id": link_id,
            "payment_link": f"https://mock-payments.recoverai.local/l/{link_id}",
            "status": "created",
        }


class FailingPaymentProvider(PaymentProvider):
    """Demo-only (spec section 4: "Simulate Provider Failure"): always
    raises, exactly like a real gateway timeout would. Used by
    `app.services.demo_service.simulate_provider_failure` so the demo can
    show `_execute_campaign`'s real failure path -- a FAILED action, an
    audit trail entry, zero revenue recorded as recovered, and the payment
    still eligible for a fresh retry campaign (see
    `campaign_service._has_active_recovery_action`, which excludes FAILED
    actions) -- without needing an actual unreliable network call to
    demonstrate it."""

    def create_recovery_link(
        self, *, payment_id: uuid.UUID, amount: float, currency: str,
        customer_name: str, customer_email: str, customer_contact: str, reference_id: str,
    ) -> dict:
        raise RazorpayTimeoutError("Simulated provider timeout (demo).")


class RazorpayPaymentProvider(PaymentProvider):
    """Real Razorpay Payment Links, created against whichever base URL the
    configured key_id/key_secret resolve to -- in practice this project only
    ever configures test-mode keys (RAZORPAY_MODE=test), per spec: live
    execution is explicitly out of scope."""

    def __init__(self, client=None):
        self._client = client  # lazily resolved via get_razorpay_client() if not injected (tests inject a fake)

    def _resolve_client(self):
        if self._client is not None:
            return self._client
        from app.integrations.razorpay.client import get_razorpay_client
        return get_razorpay_client()

    def create_recovery_link(
        self, *, payment_id: uuid.UUID, amount: float, currency: str,
        customer_name: str, customer_email: str, customer_contact: str, reference_id: str,
    ) -> dict:
        from app.integrations.razorpay import payment_links

        client = self._resolve_client()
        link = payment_links.create_payment_link(
            client, amount=amount, currency=currency,
            description=f"RecoverAI recovery link for payment {reference_id}",
            customer_name=customer_name, customer_email=customer_email, customer_contact=customer_contact,
            reference_id=reference_id,
            notes={"recoverai_payment_id": str(payment_id)},
        )
        return {
            "success": True,
            "payment_link_id": link["id"],
            "payment_link": link["short_url"],
            "status": link["status"],
        }


def get_payment_provider() -> PaymentProvider:
    """RAZORPAY_MODE=test -> real (test-mode) Razorpay calls.
    RAZORPAY_MODE=mock (the default, and what runs when credentials are
    absent) -> MockPaymentProvider, so the application keeps working
    without any Razorpay account at all."""
    settings = get_settings()
    if settings.razorpay_mode == "test":
        return RazorpayPaymentProvider()
    return MockPaymentProvider()

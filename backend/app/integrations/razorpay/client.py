"""Thin factory around the official `razorpay` SDK's `Client`.

Verified against `razorpay==2.0.1`'s `razorpay/client.py`: `Client(auth=(key_id,
key_secret))` -- Basic Auth is handled internally by the SDK (it passes
`auth=(key_id, key_secret)` straight to `requests`, which builds the
`Authorization: Basic base64(key_id:key_secret)` header itself). Nothing in
this codebase constructs that header manually, and the key_secret never
leaves the backend process -- it's read from environment/`.env` only.

## Live-key guard (Phase 8 security audit)

Razorpay has no separate sandbox base URL -- whether a call is test-mode or
real money moving is determined entirely by which *key* was used, not by
this application's own `RAZORPAY_MODE` setting. `RAZORPAY_MODE=test` only
controls whether this codebase calls Razorpay at all (see
`app/services/payment_provider.get_payment_provider`) -- it does not by
itself guarantee the configured key is actually a test key. Since live
Razorpay execution is explicitly out of scope for this entire project (see
`docs/architecture.md` / project history), this factory refuses to build a
client unless `RAZORPAY_KEY_ID` has the `rzp_test_` prefix Razorpay itself
uses for every test-mode key -- a live key (`rzp_live_...`) fails loudly
here instead of silently being able to create a real payment link.
"""

from __future__ import annotations

import razorpay

from app.core.config import get_settings
from app.integrations.razorpay.exceptions import RazorpayAuthenticationError

_client: razorpay.Client | None = None


def get_razorpay_client(force_reload: bool = False) -> razorpay.Client:
    global _client
    if _client is not None and not force_reload:
        return _client

    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RazorpayAuthenticationError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured. "
            "Set RAZORPAY_MODE=mock to run without real credentials, or "
            "provide test-mode keys from the Razorpay Dashboard."
        )
    if not settings.razorpay_key_id.startswith("rzp_test_"):
        raise RazorpayAuthenticationError(
            "RAZORPAY_KEY_ID does not look like a Razorpay test-mode key (expected the "
            "'rzp_test_' prefix). Live execution is out of scope for this project -- refusing "
            "to build a Razorpay client rather than risk moving real money."
        )

    _client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    return _client

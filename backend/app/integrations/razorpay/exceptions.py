"""Our own exception hierarchy for the Razorpay integration -- callers
(payment_provider.py, campaign_service.py) never need to import the
`razorpay` SDK's own exception types directly.

The mapping below is verified against the *installed* `razorpay==2.0.1`
package source (`razorpay/client.py`'s `request()` method), not guessed:

    if code == "BAD_REQUEST_ERROR": raise BadRequestError(msg)
    elif code == "GATEWAY_ERROR":   raise GatewayError(msg)
    elif code == "SERVER_ERROR":    raise ServerError(msg)
    else:                           raise ServerError(msg)   # <- default

Two consequences worth knowing:
  * The SDK only distinguishes these three types by the `error.code` field
    in the JSON response body -- it does not attach the raw HTTP status
    code to the exception. A 429 (rate limit) response therefore surfaces
    as a plain `ServerError` unless Razorpay happens to send one of the
    three known codes, which the docs don't specify for 429. We cannot
    honestly claim a distinct "rate limited" exception from this SDK, so
    `RazorpayServerError` is what a 429 becomes -- see `RazorpayServerError`'s
    own docstring.
  * `requests.exceptions.ConnectionError` / `.Timeout` are *not* wrapped by
    the SDK at all when its own retries (off by default -- `retry_enabled`
    starts `False`) are exhausted or disabled; they propagate as-is. We
    translate those into `RazorpayNetworkError` / `RazorpayTimeoutError`
    ourselves.
"""

from __future__ import annotations


class RazorpayIntegrationError(Exception):
    """Base class for every error this integration layer raises."""


class RazorpayAuthenticationError(RazorpayIntegrationError):
    """Raised by *our* code, before ever calling Razorpay, when
    RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are missing while RAZORPAY_MODE=test.
    (Not a translation of a Razorpay API response -- see module docstring:
    the SDK does not expose a distinct authentication-failure exception.)"""


class RazorpayValidationError(RazorpayIntegrationError):
    """The request was rejected as malformed (SDK: BadRequestError /
    BAD_REQUEST_ERROR) -- e.g. an invalid amount, email, or contact."""


class RazorpayGatewayError(RazorpayIntegrationError):
    """An upstream bank/payment-gateway issue (SDK: GatewayError /
    GATEWAY_ERROR)."""


class RazorpayServerError(RazorpayIntegrationError):
    """A Razorpay-side server error, or any response whose `error.code`
    isn't one of the two above -- including, per the SDK's own default
    branch, a 429 rate-limit response (see module docstring)."""


class RazorpayNetworkError(RazorpayIntegrationError):
    """The request could not reach Razorpay at all (SDK: raw
    requests.exceptions.ConnectionError)."""


class RazorpayTimeoutError(RazorpayIntegrationError):
    """The request timed out waiting for a response (SDK: raw
    requests.exceptions.Timeout)."""


class RazorpayWebhookSignatureError(RazorpayIntegrationError):
    """A webhook's X-Razorpay-Signature did not match (SDK:
    SignatureVerificationError)."""


def translate_sdk_error(exc: Exception) -> RazorpayIntegrationError:
    """Wraps a raw exception from the `razorpay` SDK (or the `requests`
    library it calls into) into our own hierarchy. Never invents a
    category the source code above doesn't actually produce."""
    import requests
    from razorpay.errors import BadRequestError, GatewayError, ServerError

    if isinstance(exc, BadRequestError):
        return RazorpayValidationError(str(exc))
    if isinstance(exc, GatewayError):
        return RazorpayGatewayError(str(exc))
    if isinstance(exc, ServerError):
        return RazorpayServerError(str(exc))
    if isinstance(exc, requests.exceptions.Timeout):
        return RazorpayTimeoutError(str(exc))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return RazorpayNetworkError(str(exc))
    return RazorpayIntegrationError(str(exc))

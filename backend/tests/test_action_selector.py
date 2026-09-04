"""Unit tests for RecoveryActionSelector -- the dedicated action-selection
layer (spec: separate "is this recoverable" (ML) from "what should we do
about it" (this module)).

Every test constructs its own fully-controlled Customer/Order/Payment/
PaymentFailure fixture (reusing only `dataset.merchant["id"]`, which
already exists) rather than depending on the seeded dataset's random
failure-category distribution at some index -- so each scenario is
deterministic and self-explaining, and adding/reordering seed data can
never silently change what these tests exercise.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import delete

from app.models.customer import Customer
from app.models.enums import (
    DeviceType,
    FailureCategory,
    FailureSeverity,
    PaymentMethod,
    PaymentStatus,
    Platform,
    Recoverability,
    RecommendedAction,
)
from app.models.merchant_policy import MerchantPolicy
from app.models.order import Order
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.services.action_selector import (
    EXECUTABLE_ACTIONS,
    RecoveryActionSelector,
    compute_category_spike_map,
)

ALL_FAILURE_CATEGORIES = [
    FailureCategory.UPI_FAILURE,
    FailureCategory.NETWORK_ERROR,
    FailureCategory.BANK_DECLINED,
    FailureCategory.CARD_DECLINED,
    FailureCategory.INSUFFICIENT_FUNDS,
    FailureCategory.TIMEOUT,
    FailureCategory.TECHNICAL_ERROR,
    FailureCategory.AUTHENTICATION_FAILURE,
    FailureCategory.CARD_LIMIT,
    FailureCategory.INVALID_DETAILS,
]


def _policy(**overrides) -> MerchantPolicy:
    defaults = dict(
        merchant_id=uuid.uuid4(), minimum_recovery_probability=0.65, max_customer_contacts=1,
        max_campaign_amount=None, approval_required=True, allowed_actions=["email", "sms", "whatsapp"],
    )
    defaults.update(overrides)
    return MerchantPolicy(**defaults)


@pytest.fixture()
def seed_payment(db_session):
    """Yields a factory that creates a fully self-contained failed payment,
    and deletes every row it created afterwards -- the shared test database
    is session-scoped and NOT reset between tests except for the workflow
    tables `clean_campaign_state` covers (campaigns/actions/opportunities/
    audit_logs), so a fixture inserting its own Customer/Order/Payment/
    PaymentFailure rows without cleaning them up would silently inflate
    every other test's row counts (`total_payments`, dashboard totals,
    opportunity-list totals, etc.) -- exactly the kind of test pollution
    this fixture exists to prevent."""
    created: list[Payment] = []

    def factory(
        dataset, *,
        failure_category: FailureCategory,
        attempt_number: int = 2,
        successful_payment_count: int = 0,
        amount: float = 1000.0,
    ) -> tuple[Payment, PaymentFailure, Customer]:
        payment, failure, customer = _seed_payment(
            db_session, dataset, failure_category=failure_category, attempt_number=attempt_number,
            successful_payment_count=successful_payment_count, amount=amount,
        )
        created.append(payment)
        return payment, failure, customer

    yield factory

    for payment in created:
        db_session.exec(delete(PaymentFailure).where(PaymentFailure.payment_id == payment.id))
        order_id, customer_id = payment.order_id, payment.customer_id
        db_session.exec(delete(Payment).where(Payment.id == payment.id))
        db_session.exec(delete(Order).where(Order.id == order_id))
        db_session.exec(delete(Customer).where(Customer.id == customer_id))
    db_session.commit()


def _seed_payment(
    session, dataset, *,
    failure_category: FailureCategory,
    attempt_number: int = 2,
    successful_payment_count: int = 0,
    amount: float = 1000.0,
) -> tuple[Payment, PaymentFailure, Customer]:
    """A fully self-contained failed payment -- attempt_number=2 (not 1) by
    default specifically so the RETRY (passive-monitoring) special case
    doesn't accidentally fire in tests that aren't about it; individual
    tests override it when they need attempt_number=1."""
    customer = Customer(
        merchant_id=dataset.merchant["id"], name="Test Customer", email=f"{uuid.uuid4().hex}@example.com",
        phone="9876543210", customer_since=datetime.now(timezone.utc),
        successful_payment_count=successful_payment_count,
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)

    order = Order(merchant_id=dataset.merchant["id"], customer_id=customer.id, amount=amount)
    session.add(order)
    session.commit()
    session.refresh(order)

    payment = Payment(
        merchant_id=dataset.merchant["id"], order_id=order.id, customer_id=customer.id,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:14]}", amount=amount, status=PaymentStatus.failed,
        method=PaymentMethod.upi, email=customer.email, contact=customer.phone,
        device_type=DeviceType.mobile, platform=Platform.android, location="Bengaluru",
        attempt_number=attempt_number,
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    failure = PaymentFailure(
        payment_id=payment.id, failure_category=failure_category, failure_severity=FailureSeverity.MEDIUM,
        recoverability=Recoverability.MEDIUM, raw_failure_code="TEST", raw_failure_reason="test fixture",
    )
    session.add(failure)
    session.commit()
    session.refresh(failure)

    return payment, failure, customer


# ---------------------------------------------------------------------------
# Step 13: every currently-supported failure category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", ALL_FAILURE_CATEGORIES)
def test_every_failure_category_produces_a_decision(db_session, dataset, clean_campaign_state, seed_payment, category):
    """For every category: a probability was available, an action was
    selected, and it's one of the real RecommendedAction values -- never
    None, never a made-up string."""
    payment, failure, _customer = seed_payment(dataset, failure_category=category)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(),
    )
    assert isinstance(decision.action, RecommendedAction)
    assert decision.reason
    assert 0.0 <= decision.confidence <= 1.0


def test_card_declined_recommends_alternative_method_not_executable(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.CARD_DECLINED)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.ALTERNATIVE_PAYMENT_METHOD
    assert decision.executable is False


def test_card_limit_recommends_alternative_method_not_executable(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.CARD_LIMIT)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.ALTERNATIVE_PAYMENT_METHOD
    assert decision.executable is False


def test_invalid_details_recommends_customer_correction(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.INVALID_DETAILS)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.REQUEST_CUSTOMER_CORRECTION
    assert decision.executable is False


def test_insufficient_funds_low_probability_defers(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.INSUFFICIENT_FUNDS)
    selector = RecoveryActionSelector(db_session)
    # Qualifies (>= 0.65 threshold) but not by the wider margin the
    # insufficient-funds policy requires before assuming funds are available.
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.70, expected_recovery=700.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.DEFER
    assert decision.executable is False


def test_insufficient_funds_high_probability_sends_payment_link(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.INSUFFICIENT_FUNDS)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.95, expected_recovery=950.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.PAYMENT_LINK
    assert decision.executable is True


def test_technical_error_recommends_manual_review(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.TECHNICAL_ERROR)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(),
    )
    assert decision.action == RecommendedAction.MANUAL_REVIEW
    assert decision.executable is False


def test_timeout_isolated_and_qualifying_sends_payment_link(db_session, dataset, clean_campaign_state, seed_payment):
    """The base case for a transient, non-spiking, non-first-attempt
    failure: a real payment link, actually executable."""
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.TIMEOUT, attempt_number=2)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(), spike_map={},
    )
    assert decision.action == RecommendedAction.PAYMENT_LINK
    assert decision.executable is True


def test_timeout_retry_limit_exceeded_recommends_manual_review(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.TIMEOUT, attempt_number=5)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(), spike_map={},
    )
    assert decision.action == RecommendedAction.MANUAL_REVIEW
    assert decision.executable is False
    assert "attempt #5" in decision.reason


def test_timeout_near_certain_first_attempt_established_customer_recommends_passive_retry(
    db_session, dataset, clean_campaign_state, seed_payment,
):
    """Spec's own worked example: TIMEOUT + high probability + customer has
    previous successful payments + retry limit not exceeded -> a retry-style
    outcome, not an automatic payment link."""
    payment, failure, _ = seed_payment(
        dataset, failure_category=FailureCategory.TIMEOUT,
        attempt_number=1, successful_payment_count=3,
    )
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.97, expected_recovery=970.0,
        confidence=0.9, policy=_policy(), spike_map={},
    )
    assert decision.action == RecommendedAction.RETRY
    assert decision.executable is False


def test_upi_failure_spike_defers_instead_of_mass_contacting(db_session, dataset, clean_campaign_state, seed_payment):
    """Spec's explicit example: a recent UPI failure spike should defer
    rather than immediately contacting every affected customer."""
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.UPI_FAILURE)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.8, policy=_policy(), spike_map={FailureCategory.UPI_FAILURE: True},
    )
    assert decision.action == RecommendedAction.DEFER
    assert decision.executable is False


# ---------------------------------------------------------------------------
# Step 14: the critical regression test
# ---------------------------------------------------------------------------


def test_regression_not_every_failed_payment_becomes_payment_link(db_session, dataset, clean_campaign_state, seed_payment):
    """THE regression test for the reported bug: a batch of different
    failure reasons must NOT all resolve to the same action, and must NOT
    all resolve to PAYMENT_LINK."""
    selector = RecoveryActionSelector(db_session)
    actions = set()
    for category in ALL_FAILURE_CATEGORIES:
        payment, failure, _ = seed_payment(dataset, failure_category=category)
        decision = selector.select(
            payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
            confidence=0.8, policy=_policy(), spike_map={},
        )
        actions.add(decision.action)

    assert len(actions) > 1, "every failure category resolved to the same action -- the bug is back"
    assert actions != {RecommendedAction.PAYMENT_LINK}, "every category resolved to PAYMENT_LINK -- the bug is back"


def test_unknown_failure_category_never_becomes_payment_link(db_session, dataset, clean_campaign_state, seed_payment):
    """The specific fail-closed case named in the bug report: an
    unrecognized failure reason must resolve to MANUAL_REVIEW, never to a
    financial action, regardless of how high the probability is."""
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.UNKNOWN)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.99, expected_recovery=990.0,
        confidence=0.99, policy=_policy(),
    )
    assert decision.action == RecommendedAction.MANUAL_REVIEW
    assert decision.action != RecommendedAction.PAYMENT_LINK
    assert decision.executable is False


def test_missing_failure_record_never_becomes_payment_link(db_session, dataset, clean_campaign_state, seed_payment):
    """Same fail-closed guarantee when there's no PaymentFailure row at all
    (failure=None) -- not just for the UNKNOWN enum value."""
    payment, _failure, _ = seed_payment(dataset, failure_category=FailureCategory.TIMEOUT)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=None, recovery_probability=0.99, expected_recovery=990.0,
        confidence=0.99, policy=_policy(),
    )
    assert decision.action == RecommendedAction.MANUAL_REVIEW
    assert decision.executable is False


def test_policy_violation_is_not_executable(db_session, dataset, clean_campaign_state, seed_payment):
    """Low probability (policy violation) must never be executable,
    regardless of failure category."""
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.TIMEOUT)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.1, expected_recovery=100.0,
        confidence=0.8, policy=_policy(minimum_recovery_probability=0.65),
    )
    assert decision.eligible is False
    assert decision.executable is False
    assert decision.action != RecommendedAction.PAYMENT_LINK


def test_low_confidence_forces_manual_review_regardless_of_category(db_session, dataset, clean_campaign_state, seed_payment):
    payment, failure, _ = seed_payment(dataset, failure_category=FailureCategory.TIMEOUT)
    selector = RecoveryActionSelector(db_session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=0.9, expected_recovery=900.0,
        confidence=0.1, policy=_policy(),
    )
    assert decision.action == RecommendedAction.MANUAL_REVIEW
    assert decision.executable is False


def test_only_payment_link_is_executable():
    """EXECUTABLE_ACTIONS names exactly the one action the current
    PaymentProvider abstraction can actually deliver -- see
    app/services/payment_provider.py, which only implements
    create_recovery_link (a payment link), nothing else."""
    assert EXECUTABLE_ACTIONS == frozenset({RecommendedAction.PAYMENT_LINK})


def test_compute_category_spike_map_returns_a_dict(db_session, dataset):
    spike_map = compute_category_spike_map(db_session)
    assert isinstance(spike_map, dict)
    for value in spike_map.values():
        assert isinstance(value, bool)

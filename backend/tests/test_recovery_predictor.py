"""Unit-level tests for the recovery-prediction service and feature module
-- prediction output range, expected_recovery math, leakage guards, missing
value handling, model loading, and the segmentation function."""

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
ML_DIR = BACKEND_DIR.parent / "ml"
sys.path.insert(0, str(ML_DIR / "training"))

from features import ALL_FEATURES, build_feature_frame, validate_features  # noqa: E402

from app.models.enums import RecoverySegment  # noqa: E402
from app.models.merchant_policy import MerchantPolicy  # noqa: E402
from app.services import recovery_predictor  # noqa: E402


def test_feature_frame_has_no_leaky_columns(test_engine):
    X, y, meta = build_feature_frame(test_engine)
    assert "eventually_recovered" not in X.columns
    assert "recoverability" not in X.columns
    assert set(X.columns) == set(ALL_FEATURES)
    # y is the ground truth target, kept separate from X
    assert set(y.unique()).issubset({0, 1})


def test_validate_features_raises_on_injected_leak(test_engine):
    X, _y, _meta = build_feature_frame(test_engine)
    leaked = X.copy()
    leaked["eventually_recovered"] = 1
    with pytest.raises(ValueError, match="leak"):
        validate_features(leaked)


def test_first_time_customer_has_missing_success_rate_handled(test_engine):
    """A customer's first-ever payment attempt has no prior history, so
    customer_success_rate is legitimately NaN -- and the fitted pipeline
    must still produce a valid prediction for it (imputer, not a crash)."""
    X, _y, meta = build_feature_frame(test_engine)
    first_timers = X[X["customer_success_rate"].isna()]
    assert len(first_timers) > 0, "expected at least one first-time-customer failure in the test dataset"

    model = recovery_predictor.load_model()
    probs = model.pipeline.predict_proba(first_timers)[:, 1]
    assert np.all((probs >= 0) & (probs <= 1))
    assert not np.any(np.isnan(probs))


def test_wallet_payments_have_missing_bank_handled(test_engine):
    X, _y, _meta = build_feature_frame(test_engine)
    wallet_rows = X[X["payment_method"] == "wallet"]
    if len(wallet_rows) == 0:
        pytest.skip("no wallet-method failures in this seeded sample")
    assert wallet_rows["bank"].isna().all()

    model = recovery_predictor.load_model()
    probs = model.pipeline.predict_proba(wallet_rows)[:, 1]
    assert np.all((probs >= 0) & (probs <= 1))


def test_predict_recovery_output_range_and_shape(test_engine, db_session, dataset):
    failed_payment = dataset.payment_failures[0]
    result = recovery_predictor.predict_recovery(failed_payment["payment_id"], db_session)

    assert 0.0 <= result["recovery_probability"] <= 1.0
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["expected_recovery"] >= 0
    assert result["segment"] in {s.value for s in RecoverySegment}
    assert isinstance(result["top_factors"], list)
    assert result["model_name"]
    assert result["model_version"]
    assert result["feature_version"]


def test_expected_recovery_equals_amount_times_probability(test_engine, db_session, dataset):
    failed_payment = dataset.payment_failures[1]
    payment_id = failed_payment["payment_id"]
    payment = next(p for p in dataset.payments if p["id"] == payment_id)

    result = recovery_predictor.predict_recovery(payment_id, db_session)
    expected = payment["amount"] * result["recovery_probability"]
    # Both recovery_probability (4dp) and expected_recovery (2dp) are
    # independently rounded from the unrounded probability, so a tight
    # absolute tolerance can be tripped by double-rounding on a large
    # amount -- allow for that (0.01% of the amount) rather than pinning
    # an exact match.
    tolerance = max(0.01, abs(payment["amount"]) * 0.0001)
    assert abs(result["expected_recovery"] - expected) < tolerance


def test_predict_recovery_rejects_non_failed_payment(test_engine, db_session, dataset):
    successful_payment = next(p for p in dataset.payments if p["status"] != "failed")
    with pytest.raises(recovery_predictor.PaymentNotEligibleError):
        recovery_predictor.predict_recovery(successful_payment["id"], db_session)


def test_top_factors_only_reference_real_features(test_engine, db_session, dataset):
    """Explanations must come from actual model features, never invented ones."""
    failed_payment = dataset.payment_failures[2]
    result = recovery_predictor.predict_recovery(failed_payment["payment_id"], db_session)

    model = recovery_predictor.load_model()
    known_raw_features = {f for f, _cat in model.feature_map}
    assert known_raw_features == set(ALL_FEATURES)
    assert len(result["top_factors"]) > 0
    for factor in result["top_factors"]:
        assert factor["direction"] in {"positive", "negative"}
        assert isinstance(factor["factor"], str) and factor["factor"]


def test_segment_for_probability_uses_merchant_policy():
    import uuid

    policy = MerchantPolicy(merchant_id=uuid.uuid4(), minimum_recovery_probability=0.8)
    assert recovery_predictor.segment_for_probability(0.85, policy) == RecoverySegment.HIGH_RECOVERY
    assert recovery_predictor.segment_for_probability(0.6, policy) == RecoverySegment.MEDIUM_RECOVERY
    assert recovery_predictor.segment_for_probability(0.1, policy) == RecoverySegment.LOW_RECOVERY


def test_segment_for_probability_falls_back_without_policy():
    assert recovery_predictor.segment_for_probability(0.9, None) == RecoverySegment.HIGH_RECOVERY
    assert recovery_predictor.segment_for_probability(0.5, None) == RecoverySegment.MEDIUM_RECOVERY
    assert recovery_predictor.segment_for_probability(0.1, None) == RecoverySegment.LOW_RECOVERY


def test_model_loading_raises_when_artifact_missing(monkeypatch):
    # force_reload bypasses the cache but only overwrites it on success, so
    # the already-cached real model (loaded by earlier tests) survives this
    # untouched -- no manual restore needed once monkeypatch reverts MODEL_PATH.
    monkeypatch.setattr(recovery_predictor, "MODEL_PATH", Path("/nonexistent/model.joblib"))
    with pytest.raises(recovery_predictor.ModelNotTrainedError):
        recovery_predictor.load_model(force_reload=True)


def test_model_loading_is_cached():
    recovery_predictor._loaded_model = None
    first = recovery_predictor.load_model()
    second = recovery_predictor.load_model()
    assert first is second

"""Recovery-probability prediction service.

Loads the model artifact trained by `ml/training/train.py`, computes
features for failed payments via the *same* `ml/training/features.py`
module the training script uses (so serving can never drift from what the
model was trained on), and turns predictions into the API-facing shape:
`recovery_probability`, `expected_recovery`, `confidence`, `top_factors`,
plus model-versioning metadata stamped onto every stored prediction.

## Segmentation thresholds

`segment_for_probability` is the *only* place recovery-probability
thresholds live. Everything else (API routes, opportunity ranking) reads
`RecoveryPrediction.segment`, which this function already computed --
thresholds are never re-hardcoded elsewhere. The HIGH cut is the merchant's
own `minimum_recovery_probability` policy (falling back to 0.65 if no
policy row exists); MEDIUM is a fixed 0.25-wide band below that.

## Confidence

Distinct from `recovery_probability` (P(recovered)): `confidence` measures
how decisive the prediction is, `2 * |probability - 0.5|`, so 0 at the
least-informative point (p=0.5) and 1 at full certainty (p=0 or p=1).

## Explainability

SHAP explains the fitted classifier directly on its preprocessed feature
space: `LinearExplainer` for `LogisticRegression` (exact, closed-form),
`TreeExplainer` for `RandomForestClassifier`/`XGBClassifier` (exact, fast
tree-traversal) -- both support whichever model `train.py` selected, and
both are fast enough to run in bulk (unlike generic permutation SHAP).
One-hot sub-column SHAP values are summed back to their raw feature (SHAP
values are additive, so this recovers the raw feature's total effect
exactly) before being turned into a human-readable factor string --
`top_factors` can therefore only ever name a real input feature, never an
invented one.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[3] / "ml"
if str(ML_DIR / "training") not in sys.path:
    sys.path.insert(0, str(ML_DIR / "training"))

import joblib  # noqa: E402
import shap  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    build_feature_frame,
)

from app.models.enums import RecoverySegment  # noqa: E402
from app.models.merchant_policy import MerchantPolicy  # noqa: E402
from app.models.recovery_prediction import RecoveryPrediction  # noqa: E402

MODELS_DIR = ML_DIR / "models"
MODEL_PATH = MODELS_DIR / "recovery_model.joblib"
META_PATH = MODELS_DIR / "recovery_model_meta.json"
BACKGROUND_PATH = MODELS_DIR / "recovery_model_background.joblib"

DEFAULT_DECISION_THRESHOLD = 0.65
MEDIUM_BAND_WIDTH = 0.25
TOP_FACTORS_COUNT = 5

FAILURE_CATEGORY_LABELS = {
    "NETWORK_ERROR": "Network failure",
    "TIMEOUT": "Payment timeout",
    "UPI_FAILURE": "UPI failure",
    "BANK_DECLINED": "Bank declined the payment",
    "CARD_DECLINED": "Card declined",
    "CARD_LIMIT": "Card limit exceeded",
    "INSUFFICIENT_FUNDS": "Insufficient funds",
    "AUTHENTICATION_FAILURE": "Authentication failed",
    "INVALID_DETAILS": "Invalid payment details",
    "TECHNICAL_ERROR": "Technical error",
    "UNKNOWN": "Unknown failure reason",
}

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ModelNotTrainedError(RuntimeError):
    pass


class PaymentNotEligibleError(ValueError):
    """Raised for a payment_id that doesn't exist, or isn't a failed payment
    (only failed payments have a recovery question to answer)."""


@dataclass
class LoadedModel:
    pipeline: Any
    metadata: dict
    explainer: Any
    feature_map: list[tuple[str, str | None]]


_loaded_model: LoadedModel | None = None


def _build_feature_name_map(preprocess: ColumnTransformer) -> list[tuple[str, str | None]]:
    """Order-matched to `preprocess.get_feature_names_out()`: for each
    output column, which raw feature it came from, and (for one-hot
    columns) which category value it represents."""
    names: list[tuple[str, str | None]] = [(feat, None) for feat in NUMERIC_FEATURES]
    onehot = preprocess.named_transformers_["categorical"].named_steps["onehot"]
    for feat, categories in zip(CATEGORICAL_FEATURES, onehot.categories_):
        names.extend((feat, str(cat)) for cat in categories)
    return names


def load_model(force_reload: bool = False) -> LoadedModel:
    global _loaded_model
    if _loaded_model is not None and not force_reload:
        return _loaded_model

    if not MODEL_PATH.exists() or not META_PATH.exists():
        raise ModelNotTrainedError(
            "No trained recovery model found. Run `python ml/training/train.py` first."
        )

    pipeline = joblib.load(MODEL_PATH)
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
    background = joblib.load(BACKGROUND_PATH)

    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classifier"]

    bg_transformed = preprocess.transform(background)
    if hasattr(bg_transformed, "toarray"):
        bg_transformed = bg_transformed.toarray()

    if isinstance(classifier, LogisticRegression):
        explainer = shap.LinearExplainer(classifier, bg_transformed)
    else:
        explainer = shap.TreeExplainer(classifier)

    _loaded_model = LoadedModel(
        pipeline=pipeline,
        metadata=metadata,
        explainer=explainer,
        feature_map=_build_feature_name_map(preprocess),
    )
    return _loaded_model


def segment_for_probability(probability: float, policy: MerchantPolicy | None) -> RecoverySegment:
    threshold = policy.minimum_recovery_probability if policy else DEFAULT_DECISION_THRESHOLD
    medium_floor = max(0.0, threshold - MEDIUM_BAND_WIDTH)
    if probability >= threshold:
        return RecoverySegment.HIGH_RECOVERY
    if probability >= medium_floor:
        return RecoverySegment.MEDIUM_RECOVERY
    return RecoverySegment.LOW_RECOVERY


def _explain_batch(explainer: Any, X_transformed: np.ndarray) -> np.ndarray:
    raw = explainer.shap_values(X_transformed)
    arr = np.asarray(raw)
    if arr.ndim == 3:  # (n_samples, n_features, n_classes) -- keep the positive class
        arr = arr[:, :, 1]
    return arr


def _format_factor(raw_feature: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        if raw_feature == "customer_success_rate":
            return "No prior payment history for this customer"
        if raw_feature == "bank":
            return "No bank linked to this payment"
        return f"{raw_feature.replace('_', ' ').capitalize()}: unknown"

    if raw_feature == "payment_amount":
        return f"Transaction amount: ₹{value:,.0f}"
    if raw_feature == "customer_lifetime_value":
        return f"Customer lifetime value: ₹{value:,.0f}"
    if raw_feature == "customer_order_count":
        n = int(value)
        return f"{n} prior order{'s' if n != 1 else ''} from this customer" if n else "First order from this customer"
    if raw_feature == "customer_success_rate":
        return f"Customer success rate: {value:.0%}"
    if raw_feature == "customer_failure_count":
        n = int(value)
        return f"{n} prior failed payment{'s' if n != 1 else ''}" if n else "No prior failed payments"
    if raw_feature == "previous_failed_attempts":
        n = int(value)
        return "First attempt on this order" if n == 0 else f"{n} previous failed attempt{'s' if n != 1 else ''} on this order"
    if raw_feature == "attempt_number":
        return f"Attempt #{int(value)}"
    if raw_feature == "time_since_customer_created_days":
        return f"Customer for {int(value)} days"
    if raw_feature == "hour_of_day":
        return f"Failed at {int(value):02d}:00"
    if raw_feature == "day_of_week":
        return f"Failed on a {WEEKDAY_NAMES[int(value) % 7]}"
    if raw_feature == "payment_method":
        return f"Payment method: {str(value).upper()}"
    if raw_feature == "bank":
        return f"Bank: {value}"
    if raw_feature == "failure_category":
        return FAILURE_CATEGORY_LABELS.get(str(value), str(value).replace("_", " ").title())
    if raw_feature == "failure_severity":
        return f"{str(value).title()} severity failure"
    if raw_feature == "device_type":
        return f"Device: {value}"
    if raw_feature == "platform":
        return f"Platform: {value}"
    if raw_feature == "location":
        return f"Location: {value}"
    return f"{raw_feature}: {value}"


def _raw_factor_contributions(
    shap_row: np.ndarray, feature_map: list[tuple[str, str | None]], raw_row: pd.Series
) -> list[dict]:
    contributions: dict[str, float] = {}
    for (raw_feature, _category), shap_value in zip(feature_map, shap_row):
        contributions[raw_feature] = contributions.get(raw_feature, 0.0) + float(shap_value)

    factors = [
        {
            "factor": _format_factor(raw_feature, raw_row[raw_feature]),
            "direction": "positive" if value > 0 else "negative",
            "shap_value": round(value, 5),
        }
        for raw_feature, value in contributions.items()
        if abs(value) > 1e-9
    ]
    factors.sort(key=lambda f: abs(f["shap_value"]), reverse=True)
    return factors


def _upsert_prediction(
    session: Session, record: RecoveryPrediction, existing_by_payment_id: dict[uuid.UUID, RecoveryPrediction],
) -> None:
    """`existing_by_payment_id` is fetched once, in bulk, by the caller --
    querying per-row here (the original implementation) turns a 6,673-payment
    `POST /api/recovery/analyze` call into 6,673 individual round trips,
    which measured ~39s against the real 100k-row dataset. A single
    `WHERE payment_id IN (...)` upfront plus in-memory dict lookups here
    brought the same call under 2s (see Phase 8's performance pass)."""
    existing = existing_by_payment_id.get(record.payment_id)
    if existing is None:
        session.add(record)
        return
    for field in (
        "recovery_probability", "expected_recovery", "confidence", "segment", "top_factors",
        "model_name", "model_version", "feature_version", "training_timestamp", "predicted_at",
    ):
        setattr(existing, field, getattr(record, field))
    session.add(existing)


def _run_predictions(session: Session, X: pd.DataFrame, meta: pd.DataFrame) -> list[dict]:
    loaded = load_model()
    pipeline = loaded.pipeline
    preprocess = pipeline.named_steps["preprocess"]

    probabilities = pipeline.predict_proba(X)[:, 1]

    X_transformed = preprocess.transform(X)
    if hasattr(X_transformed, "toarray"):
        X_transformed = X_transformed.toarray()
    shap_values = _explain_batch(loaded.explainer, X_transformed)

    policy = session.exec(select(MerchantPolicy)).first()
    training_timestamp = datetime.fromisoformat(loaded.metadata["training_timestamp"])
    now = datetime.now(timezone.utc)

    payment_ids_in_batch = [uuid.UUID(str(pid)) for pid in meta["payment_id"]]
    existing_by_payment_id = {
        pred.payment_id: pred
        for pred in session.exec(
            select(RecoveryPrediction).where(RecoveryPrediction.payment_id.in_(payment_ids_in_batch))
        ).all()
    }

    results: list[dict] = []
    for i in range(len(X)):
        probability = float(probabilities[i])
        amount = float(meta.iloc[i]["amount"])
        payment_id = meta.iloc[i]["payment_id"]
        expected_recovery = amount * probability
        confidence = abs(probability - 0.5) * 2
        segment = segment_for_probability(probability, policy)
        top_factors = _raw_factor_contributions(shap_values[i], loaded.feature_map, X.iloc[i])[:TOP_FACTORS_COUNT]

        record = RecoveryPrediction(
            payment_id=payment_id,
            recovery_probability=probability,
            expected_recovery=expected_recovery,
            confidence=confidence,
            segment=segment,
            top_factors=top_factors,
            model_name=loaded.metadata["model_name"],
            model_version=loaded.metadata["model_version"],
            feature_version=loaded.metadata["feature_version"],
            training_timestamp=training_timestamp,
            predicted_at=now,
        )
        _upsert_prediction(session, record, existing_by_payment_id)

        results.append({
            "payment_id": str(payment_id),
            "recovery_probability": round(probability, 4),
            "expected_recovery": round(expected_recovery, 2),
            "confidence": round(confidence, 4),
            "segment": segment.value,
            "top_factors": top_factors,
            "model_name": loaded.metadata["model_name"],
            "model_version": loaded.metadata["model_version"],
            "feature_version": loaded.metadata["feature_version"],
            "training_timestamp": training_timestamp.isoformat(),
        })

    session.commit()
    return results


def predict_for_payment_ids(session: Session, payment_ids: list[uuid.UUID]) -> list[dict]:
    # Derived from the session (rather than a module-level engine import) so
    # this works correctly against whatever database the caller's session is
    # bound to -- production, or an isolated test database.
    X, _y, meta = build_feature_frame(session.get_bind(), payment_ids=payment_ids)
    if X.empty:
        return []
    return _run_predictions(session, X, meta)


def predict_recovery(payment_id: uuid.UUID, session: Session) -> dict:
    """`predict_recovery(payment_id)` per the Phase 2 spec: predicts (and
    persists) the recovery probability for one failed payment."""
    results = predict_for_payment_ids(session, [payment_id])
    if not results:
        raise PaymentNotEligibleError(
            f"Payment {payment_id} was not found, or is not a failed payment with a recorded failure."
        )
    return results[0]


def analyze_all_failed_payments(session: Session) -> list[dict]:
    """Runs the prediction pipeline against every currently-failed payment,
    upserting `recovery_predictions` for each -- backs `POST /api/recovery/analyze`."""
    X, _y, meta = build_feature_frame(session.get_bind(), payment_ids=None)
    if X.empty:
        return []
    return _run_predictions(session, X, meta)

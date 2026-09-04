"""Feature engineering for the recovery-prediction model.

Single source of truth for turning raw `payments` / `payment_failures` /
`customers` rows into a model-ready feature frame -- used by both
`ml/training/train.py` (bulk, all failed payments) and
`backend/app/services/recovery_predictor.py` (a handful of payment_ids at
serving time), so training and serving can never drift apart.

## Avoiding target leakage

Two distinct kinds of leakage matter here:

1. **The obvious one**: `payment_failures.eventually_recovered` is ground
   truth and never appears in the feature frame `X` -- only in `y`.
   `validate_features` asserts this.
2. **The subtler one**: `customers.lifetime_value` / `order_count` /
   `successful_payment_count` / `failed_payment_count` (Phase 1's stored
   columns) are *all-time* aggregates -- they include transactions that
   happened *after* any given failed payment. Feeding those in directly
   would let the model see the customer's future. Instead, every
   customer-history feature here (`customer_success_rate`,
   `customer_failure_count`, `customer_order_count`,
   `customer_lifetime_value`) is recomputed point-in-time: only prior
   transactions (strictly before the payment being scored) count.
   `previous_failed_attempts` is simply `attempt_number - 1`, which is
   observed at the moment the payment fails, not leaked information.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402

FEATURE_VERSION = "v1"

SUCCESS_LIKE_STATUSES = ("success", "captured", "authorized", "refunded")

NUMERIC_FEATURES = [
    "payment_amount",
    "customer_lifetime_value",
    "customer_order_count",
    "customer_success_rate",
    "customer_failure_count",
    "previous_failed_attempts",
    "attempt_number",
    "time_since_customer_created_days",
    "hour_of_day",
    "day_of_week",
]

CATEGORICAL_FEATURES = [
    "payment_method",
    "bank",
    "failure_category",
    "failure_severity",
    "device_type",
    "platform",
    "location",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

LEAKY_COLUMNS = {"eventually_recovered", "recoverability"}
"""`recoverability` is Phase 1's own weak heuristic label, not a real feature
-- including it here would let the model just learn to copy that heuristic
instead of the richer signal in `eventually_recovered`."""


def get_engine() -> Engine:
    from sqlalchemy import create_engine

    return create_engine(get_settings().database_url)


def _load_payments(engine: Engine, customer_ids: list[uuid.UUID] | None = None) -> pd.DataFrame:
    """All payments (any status) for the given customers, or everyone if
    `customer_ids` is None. Needed in full so point-in-time customer-history
    features can be computed correctly even for a single target payment."""
    where = ""
    params: dict = {}
    if customer_ids is not None:
        where = "WHERE p.customer_id = ANY(:customer_ids)"
        params["customer_ids"] = customer_ids

    query = text(f"""
        SELECT p.id AS payment_id, p.customer_id, p.order_id, p.amount, p.status,
               p.method, p.bank, p.device_type, p.platform, p.location,
               p.attempt_number, p.created_at,
               c.customer_since
        FROM payments p
        JOIN customers c ON c.id = p.customer_id
        {where}
        ORDER BY p.customer_id, p.created_at
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)
    return df


def _load_failures(engine: Engine, payment_ids: list[uuid.UUID] | None = None) -> pd.DataFrame:
    where = ""
    params: dict = {}
    if payment_ids is not None:
        where = "WHERE payment_id = ANY(:payment_ids)"
        params["payment_ids"] = payment_ids

    query = text(f"""
        SELECT payment_id, failure_category, failure_severity, eventually_recovered
        FROM payment_failures
        {where}
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)
    return df


def _compute_point_in_time_stats(payments_df: pd.DataFrame) -> pd.DataFrame:
    """Adds prior-history columns to every payment row, computed strictly
    from that customer's *earlier* payments (sorted by created_at)."""
    df = payments_df.sort_values(["customer_id", "created_at"]).reset_index(drop=True).copy()

    is_success = df["status"].isin(SUCCESS_LIKE_STATUSES).astype(int)
    is_failed = (df["status"] == "failed").astype(int)
    success_amount = df["amount"].where(df["status"].isin(SUCCESS_LIKE_STATUSES), 0.0)
    is_first_attempt_of_order = ~df.duplicated(subset=["customer_id", "order_id"])

    df["prior_successful_count"] = is_success.groupby(df["customer_id"]).cumsum() - is_success
    df["prior_failed_count"] = is_failed.groupby(df["customer_id"]).cumsum() - is_failed
    df["prior_lifetime_value"] = (
        success_amount.groupby(df["customer_id"]).cumsum() - success_amount
    )
    df["prior_order_count"] = (
        is_first_attempt_of_order.astype(int).groupby(df["customer_id"]).cumsum()
        - is_first_attempt_of_order.astype(int)
    )
    return df


def build_feature_frame(
    engine: Engine | None = None, payment_ids: list[uuid.UUID] | None = None
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Returns (X, y, meta) for the given failed payment_ids, or for every
    failed payment in the database if `payment_ids` is None (training)."""
    engine = engine or get_engine()

    customer_ids = None
    if payment_ids is not None:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT customer_id FROM payments WHERE id = ANY(:ids)"),
                {"ids": payment_ids},
            ).all()
        customer_ids = [r[0] for r in rows]
        if not customer_ids:
            empty = pd.DataFrame(columns=ALL_FEATURES)
            return empty, pd.Series(dtype=int), pd.DataFrame(columns=["payment_id", "customer_id", "created_at", "amount"])

    payments_df = _load_payments(engine, customer_ids=customer_ids)
    payments_df = _compute_point_in_time_stats(payments_df)

    # payment_failures rows only exist for failed payments, so this inner
    # merge naturally restricts to the prediction target population.
    failures_df = _load_failures(engine, payment_ids=payment_ids)
    merged = payments_df.merge(failures_df, on="payment_id", how="inner")

    if payment_ids is not None:
        merged = merged[merged["payment_id"].isin(set(payment_ids))]

    merged = merged.reset_index(drop=True)

    denom = merged["prior_successful_count"] + merged["prior_failed_count"]
    customer_success_rate = (merged["prior_successful_count"] / denom).where(denom > 0)

    created_at = pd.to_datetime(merged["created_at"])
    customer_since = pd.to_datetime(merged["customer_since"])

    X = pd.DataFrame({
        "payment_amount": merged["amount"].astype(float),
        "customer_lifetime_value": merged["prior_lifetime_value"].astype(float),
        "customer_order_count": merged["prior_order_count"].astype(float),
        "customer_success_rate": customer_success_rate.astype(float),
        "customer_failure_count": merged["prior_failed_count"].astype(float),
        "previous_failed_attempts": (merged["attempt_number"] - 1).astype(float),
        "attempt_number": merged["attempt_number"].astype(float),
        "time_since_customer_created_days": (created_at - customer_since).dt.total_seconds() / 86400.0,
        "hour_of_day": created_at.dt.hour.astype(float),
        "day_of_week": created_at.dt.dayofweek.astype(float),
        "payment_method": merged["method"].astype(str),
        "bank": merged["bank"],
        "failure_category": merged["failure_category"].astype(str),
        "failure_severity": merged["failure_severity"].astype(str),
        "device_type": merged["device_type"].astype(str),
        "platform": merged["platform"].astype(str),
        "location": merged["location"].astype(str),
    })

    y = merged["eventually_recovered"].astype(int)
    y.name = "eventually_recovered"

    meta = pd.DataFrame({
        "payment_id": merged["payment_id"],
        "customer_id": merged["customer_id"],
        "created_at": created_at,
        "amount": merged["amount"].astype(float),
    })

    validate_features(X)
    return X, y, meta


def validate_features(X: pd.DataFrame) -> None:
    """Fails loudly on target leakage or a schema drift, rather than
    silently training/serving on the wrong columns."""
    leaked = LEAKY_COLUMNS.intersection(X.columns)
    if leaked:
        raise ValueError(f"Target-leaking columns present in feature frame: {leaked}")

    missing = set(ALL_FEATURES) - set(X.columns)
    if missing:
        raise ValueError(f"Feature frame is missing expected columns: {missing}")

    unexpected = set(X.columns) - set(ALL_FEATURES)
    if unexpected:
        raise ValueError(f"Feature frame has unexpected columns: {unexpected}")

    # Only these are allowed to be missing: a first-ever attempt has no
    # prior history to compute a success rate from, and wallet payments
    # have no linked bank.
    allowed_na_columns = {"customer_success_rate", "bank"}
    na_columns = set(X.columns[X.isna().any()]) - allowed_na_columns
    if na_columns:
        raise ValueError(f"Unexpected missing values in columns: {na_columns}")

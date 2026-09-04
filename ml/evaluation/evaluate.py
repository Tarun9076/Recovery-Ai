"""Pure metric-computation functions shared by the training script and the
evaluation report -- nothing here touches the database or a specific model,
so the same functions can be re-run against any (y_true, y_prob, amount)
triple without re-training.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class ClassificationMetrics:
    precision: float
    recall: float
    f1: float
    roc_auc: float
    pr_auc: float
    brier_score: float
    threshold: float
    false_positive_count: int
    false_negative_count: int
    true_positive_count: int
    true_negative_count: int
    false_positive_revenue_cost: float
    false_negative_revenue_cost: float

    def as_dict(self) -> dict:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "roc_auc": self.roc_auc,
            "pr_auc": self.pr_auc,
            "brier_score": self.brier_score,
            "threshold": self.threshold,
            "false_positive_count": self.false_positive_count,
            "false_negative_count": self.false_negative_count,
            "true_positive_count": self.true_positive_count,
            "true_negative_count": self.true_negative_count,
            "false_positive_revenue_cost": self.false_positive_revenue_cost,
            "false_negative_revenue_cost": self.false_negative_revenue_cost,
        }


def compute_classification_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, amount: np.ndarray, threshold: float
) -> ClassificationMetrics:
    """`threshold` decides the recoverable/not-recoverable cut used for the
    confusion-matrix-based metrics (precision/recall/F1/FP/FN counts and
    their revenue cost). ROC-AUC, PR-AUC, and Brier score are
    threshold-independent and score the full probability output.

    Revenue cost definitions (no external "cost per campaign" figure exists
    in this dataset, so cost is defined directly in terms of the payment
    amounts actually misclassified):
      - false_positive_revenue_cost: sum of `amount` for payments predicted
        recoverable that were NOT actually recovered (money the business
        would expect that never materializes).
      - false_negative_revenue_cost: sum of `amount` for payments predicted
        NOT recoverable that WERE actually recovered (real revenue that a
        recovery flow driven by this model would never attempt to reach).
    """
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob).astype(float)
    amount = np.asarray(amount).astype(float)
    y_pred = (y_prob >= threshold).astype(int)

    fp_mask = (y_pred == 1) & (y_true == 0)
    fn_mask = (y_pred == 0) & (y_true == 1)
    tp_mask = (y_pred == 1) & (y_true == 1)
    tn_mask = (y_pred == 0) & (y_true == 0)

    return ClassificationMetrics(
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        f1=float(f1_score(y_true, y_pred, zero_division=0)),
        roc_auc=float(roc_auc_score(y_true, y_prob)),
        pr_auc=float(average_precision_score(y_true, y_prob)),
        brier_score=float(brier_score_loss(y_true, y_prob)),
        threshold=float(threshold),
        false_positive_count=int(fp_mask.sum()),
        false_negative_count=int(fn_mask.sum()),
        true_positive_count=int(tp_mask.sum()),
        true_negative_count=int(tn_mask.sum()),
        false_positive_revenue_cost=float(amount[fp_mask].sum()),
        false_negative_revenue_cost=float(amount[fn_mask].sum()),
    )


@dataclass
class BusinessMetrics:
    predicted_recoverable_revenue: float
    actual_recovered_revenue: float
    prediction_error: float
    prediction_error_pct: float
    calibration_bins: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "predicted_recoverable_revenue": self.predicted_recoverable_revenue,
            "actual_recovered_revenue": self.actual_recovered_revenue,
            "prediction_error": self.prediction_error,
            "prediction_error_pct": self.prediction_error_pct,
            "calibration_bins": self.calibration_bins,
        }


def compute_business_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, amount: np.ndarray, n_bins: int = 10
) -> BusinessMetrics:
    """expected_recovery = amount * recovery_probability, summed, compared
    against the actual recovered revenue (sum of amount where the payment
    truly was eventually recovered). Also bins predictions into deciles of
    predicted probability and compares each bin's mean predicted probability
    against its actual recovery rate -- a simple reliability/calibration
    check without pulling in a plotting dependency.
    """
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob).astype(float)
    amount = np.asarray(amount).astype(float)

    predicted_recoverable_revenue = float((amount * y_prob).sum())
    actual_recovered_revenue = float(amount[y_true == 1].sum())
    prediction_error = predicted_recoverable_revenue - actual_recovered_revenue
    prediction_error_pct = (
        prediction_error / actual_recovered_revenue if actual_recovered_revenue else float("nan")
    )

    df = pd.DataFrame({"y_true": y_true, "y_prob": y_prob})
    df["bin"] = pd.qcut(df["y_prob"], q=n_bins, duplicates="drop")
    calibration = (
        df.groupby("bin", observed=True)
        .agg(mean_predicted=("y_prob", "mean"), actual_rate=("y_true", "mean"), count=("y_true", "size"))
        .reset_index(drop=True)
    )
    calibration_bins = [
        {
            "mean_predicted": float(row.mean_predicted),
            "actual_rate": float(row.actual_rate),
            "count": int(row.count),
        }
        for row in calibration.itertuples()
    ]

    return BusinessMetrics(
        predicted_recoverable_revenue=predicted_recoverable_revenue,
        actual_recovered_revenue=actual_recovered_revenue,
        prediction_error=prediction_error,
        prediction_error_pct=prediction_error_pct,
        calibration_bins=calibration_bins,
    )

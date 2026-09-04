"""Phase 8 evaluation reporting. `load_model_evaluation` reads the exact
JSON file `ml/training/train.py` wrote after its last real training run
(`ml/models/recovery_model_meta.json`) -- the same file
`recovery_predictor.py` loads to serve live predictions. Nothing here
recomputes or re-derives a number: precision/recall/F1/ROC-AUC/PR-AUC/Brier
score/FP-cost/FN-cost all came from `ml/evaluation/evaluate.py` scoring the
model against its held-out temporal test split, not this API layer.
Re-running `python ml/training/train.py` and re-calling this endpoint picks
up the new numbers automatically -- there is no cached/hardcoded copy here.
"""

from __future__ import annotations

import json

from app.services.recovery_predictor import META_PATH


class ModelNotEvaluatedError(RuntimeError):
    pass


def load_model_evaluation() -> dict:
    if not META_PATH.exists():
        raise ModelNotEvaluatedError(
            "No trained model metadata found. Run `python ml/training/train.py` first."
        )

    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    classification = meta.get("test_classification_metrics", {})
    business = meta.get("test_business_metrics", {})

    return {
        "model_name": meta["model_name"],
        "model_version": meta["model_version"],
        "feature_version": meta["feature_version"],
        "algorithm": meta["algorithm"],
        "training_timestamp": meta["training_timestamp"],
        "decision_threshold": meta["decision_threshold"],
        "dataset_size": meta.get("dataset_size"),
        "positive_rate": meta.get("positive_rate"),
        "precision": classification.get("precision"),
        "recall": classification.get("recall"),
        "f1": classification.get("f1"),
        "roc_auc": classification.get("roc_auc"),
        "pr_auc": classification.get("pr_auc"),
        "brier_score": classification.get("brier_score"),
        "false_positive_count": classification.get("false_positive_count"),
        "false_negative_count": classification.get("false_negative_count"),
        "true_positive_count": classification.get("true_positive_count"),
        "true_negative_count": classification.get("true_negative_count"),
        "false_positive_revenue_cost": classification.get("false_positive_revenue_cost"),
        "false_negative_revenue_cost": classification.get("false_negative_revenue_cost"),
        "test_predicted_recoverable_revenue": business.get("predicted_recoverable_revenue"),
        "test_actual_recovered_revenue": business.get("actual_recovered_revenue"),
        "test_prediction_error": business.get("prediction_error"),
        "test_prediction_error_pct": business.get("prediction_error_pct"),
        "calibration_bins": business.get("calibration_bins", []),
    }

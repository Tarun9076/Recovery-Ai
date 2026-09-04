"""Trains the recovery-prediction model: Logistic Regression baseline vs.
Random Forest vs. XGBoost, temporal train/val/test split, model selection
on validation PR-AUC, final metrics on the held-out test set, and an
artifact (`ml/models/recovery_model.joblib` + a metadata JSON) the backend
loads at serving time.

Run: `python ml/training/train.py` (from the repo root, or anywhere -- it
locates paths relative to this file).
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR / "training"))
sys.path.insert(0, str(ML_DIR / "evaluation"))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

from evaluate import compute_business_metrics, compute_classification_metrics  # noqa: E402
from features import (  # noqa: E402
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    FEATURE_VERSION,
    NUMERIC_FEATURES,
    build_feature_frame,
    get_engine,
)

try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

MODEL_NAME = "recovery-prediction"
MODEL_VERSION = "1.0.0"
DEFAULT_DECISION_THRESHOLD = 0.65  # falls back to this if no merchant_policy row exists

MODELS_DIR = ML_DIR / "models"
DOCS_PATH = ML_DIR.parent / "docs" / "ml-evaluation.md"


def build_preprocessor() -> ColumnTransformer:
    numeric_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="constant", fill_value="MISSING")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    return ColumnTransformer([
        ("numeric", numeric_pipeline, NUMERIC_FEATURES),
        ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
    ])


def temporal_split(X: pd.DataFrame, y: pd.Series, meta: pd.DataFrame):
    order = meta["created_at"].sort_values().index
    n = len(order)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    train_idx = order[:train_end]
    val_idx = order[train_end:val_end]
    test_idx = order[val_end:]

    split_info = {
        "train_start": str(meta.loc[train_idx, "created_at"].min()),
        "train_end": str(meta.loc[train_idx, "created_at"].max()),
        "val_start": str(meta.loc[val_idx, "created_at"].min()),
        "val_end": str(meta.loc[val_idx, "created_at"].max()),
        "test_start": str(meta.loc[test_idx, "created_at"].min()),
        "test_end": str(meta.loc[test_idx, "created_at"].max()),
        "train_size": len(train_idx),
        "val_size": len(val_idx),
        "test_size": len(test_idx),
    }
    return (
        (X.loc[train_idx], y.loc[train_idx], meta.loc[train_idx]),
        (X.loc[val_idx], y.loc[val_idx], meta.loc[val_idx]),
        (X.loc[test_idx], y.loc[test_idx], meta.loc[test_idx]),
        split_info,
    )


def get_decision_threshold(engine) -> float:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT minimum_recovery_probability FROM merchant_policies LIMIT 1")
        ).first()
    return float(row[0]) if row else DEFAULT_DECISION_THRESHOLD


def candidate_models() -> dict:
    # No class_weight="balanced": the positive rate (~61%) is mild, and the
    # business math (expected_recovery = amount * probability, and the
    # merchant-policy probability threshold) both depend on well-calibrated
    # probabilities. Balancing class weight shifts the decision boundary to
    # optimize for a 50/50 prior and measurably distorts calibration here --
    # it's a precision/recall lever, not something to reach for by default.
    models = {
        "LogisticRegression": LogisticRegression(max_iter=1000),
        "RandomForestClassifier": RandomForestClassifier(
            n_estimators=300, max_depth=8, min_samples_leaf=5,
            random_state=42, n_jobs=-1,
        ),
    }
    if HAS_XGBOOST:
        models["XGBClassifier"] = XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, eval_metric="logloss", random_state=42,
        )
    return models


def get_feature_importance(pipeline: Pipeline, top_n: int = 20) -> list[dict]:
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classifier"]
    feature_names = preprocess.get_feature_names_out()

    if hasattr(classifier, "feature_importances_"):
        importances = classifier.feature_importances_
    elif hasattr(classifier, "coef_"):
        importances = np.abs(classifier.coef_[0])
    else:
        return []

    order = np.argsort(importances)[::-1][:top_n]
    return [{"feature": feature_names[i], "importance": float(importances[i])} for i in order]


def main() -> None:
    warnings.filterwarnings("ignore", category=FutureWarning)
    engine = get_engine()

    print("Loading features from database...")
    X, y, meta = build_feature_frame(engine)
    print(f"Loaded {len(X)} failed payments, recovery rate = {y.mean():.3f}")

    (X_train, y_train, meta_train), (X_val, y_val, meta_val), (X_test, y_test, meta_test), split_info = \
        temporal_split(X, y, meta)
    print(f"Split: train={len(X_train)} val={len(X_val)} test={len(X_test)}")
    print(f"  train: {split_info['train_start']} -> {split_info['train_end']}")
    print(f"  val:   {split_info['val_start']} -> {split_info['val_end']}")
    print(f"  test:  {split_info['test_start']} -> {split_info['test_end']}")

    threshold = get_decision_threshold(engine)
    print(f"Decision threshold (merchant_policy.minimum_recovery_probability): {threshold}")

    validation_results = {}
    fitted_pipelines = {}
    for name, estimator in candidate_models().items():
        pipeline = Pipeline([("preprocess", build_preprocessor()), ("classifier", estimator)])
        pipeline.fit(X_train, y_train)
        val_prob = pipeline.predict_proba(X_val)[:, 1]
        pr_auc = average_precision_score(y_val, val_prob)
        roc_auc = roc_auc_score(y_val, val_prob)
        validation_results[name] = {"pr_auc": float(pr_auc), "roc_auc": float(roc_auc)}
        fitted_pipelines[name] = pipeline
        print(f"  [{name}] val PR-AUC={pr_auc:.4f} val ROC-AUC={roc_auc:.4f}")

    best_name = max(validation_results, key=lambda k: validation_results[k]["pr_auc"])
    print(f"Selected model: {best_name} (highest validation PR-AUC)")

    # Refit the winning model type on train+val before final test evaluation,
    # to use as much data as possible for the model the backend will actually serve.
    X_trainval = pd.concat([X_train, X_val])
    y_trainval = pd.concat([y_train, y_val])
    final_pipeline = Pipeline([("preprocess", build_preprocessor()), ("classifier", candidate_models()[best_name])])
    final_pipeline.fit(X_trainval, y_trainval)

    test_prob = final_pipeline.predict_proba(X_test)[:, 1]
    classification_metrics = compute_classification_metrics(
        y_test.to_numpy(), test_prob, meta_test["amount"].to_numpy(), threshold
    )
    business_metrics = compute_business_metrics(
        y_test.to_numpy(), test_prob, meta_test["amount"].to_numpy()
    )
    print(f"Test PR-AUC={classification_metrics.pr_auc:.4f} ROC-AUC={classification_metrics.roc_auc:.4f} "
          f"F1={classification_metrics.f1:.4f} Brier={classification_metrics.brier_score:.4f}")

    feature_importance = get_feature_importance(final_pipeline)

    training_timestamp = datetime.now(timezone.utc).isoformat()
    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "algorithm": best_name,
        "training_timestamp": training_timestamp,
        "decision_threshold": threshold,
        "features": ALL_FEATURES,
        "split": split_info,
        "validation_results": validation_results,
        "test_classification_metrics": classification_metrics.as_dict(),
        "test_business_metrics": business_metrics.as_dict(),
        "feature_importance": feature_importance,
        "dataset_size": int(len(X)),
        "positive_rate": float(y.mean()),
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "recovery_model.joblib"
    meta_path = MODELS_DIR / "recovery_model_meta.json"
    background_path = MODELS_DIR / "recovery_model_background.joblib"
    joblib.dump(final_pipeline, model_path)
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    # A small raw-feature sample for SHAP's background/baseline distribution
    # at serving time (backend/app/services/recovery_predictor.py) -- avoids
    # re-querying the training set just to explain a single prediction.
    background_sample = X_trainval.sample(min(100, len(X_trainval)), random_state=42)
    joblib.dump(background_sample, background_path)
    print(f"Saved model to {model_path}")
    print(f"Saved metadata to {meta_path}")
    print(f"Saved SHAP background sample to {background_path}")

    write_evaluation_report(metadata)
    print(f"Wrote evaluation report to {DOCS_PATH}")


def write_evaluation_report(metadata: dict) -> None:
    cm = metadata["test_classification_metrics"]
    bm = metadata["test_business_metrics"]
    split = metadata["split"]

    lines = [
        "# RecoverAI — ML Evaluation Report (Phase 2)",
        "",
        f"Generated automatically by `ml/training/train.py` at "
        f"{metadata['training_timestamp']}. All numbers below come directly "
        f"from that training run against the live database — nothing here "
        f"is hand-typed.",
        "",
        "## Model selection",
        "",
        f"Trained on {metadata['dataset_size']} failed payments "
        f"(recovery rate {metadata['positive_rate']:.1%}). Candidates were "
        f"compared on **validation PR-AUC** rather than ROC-AUC alone: the "
        f"business decision this model drives — act on a payment only above "
        f"a probability threshold — is precision/recall-shaped, and PR-AUC "
        f"is more sensitive to the positive-class ranking quality that "
        f"decision depends on:",
        "",
        "| Model | Validation PR-AUC | Validation ROC-AUC |",
        "| --- | --- | --- |",
    ]
    for name, res in metadata["validation_results"].items():
        marker = " **(selected)**" if name == metadata["algorithm"] else ""
        lines.append(f"| {name}{marker} | {res['pr_auc']:.4f} | {res['roc_auc']:.4f} |")

    lines += [
        "",
        f"**Selected model: {metadata['algorithm']}**, refit on train+validation "
        f"data before final test evaluation below.",
        "",
        "## Train / validation / test split",
        "",
        "Temporal split (not random) — sorted by `payments.created_at`, "
        "70% earliest / 15% / 15% latest — so validation and test always "
        "evaluate the model on data chronologically *after* what it trained "
        "on, matching how it would actually be used in production.",
        "",
        f"- Train: {split['train_size']} payments, {split['train_start']} → {split['train_end']}",
        f"- Validation: {split['val_size']} payments, {split['val_start']} → {split['val_end']}",
        f"- Test: {split['test_size']} payments, {split['test_start']} → {split['test_end']}",
        "",
        "## Test set metrics",
        "",
        f"Decision threshold for precision/recall/F1/FP/FN: **{cm['threshold']}** "
        f"(the merchant's `minimum_recovery_probability` policy value).",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision | {cm['precision']:.4f} |",
        f"| Recall | {cm['recall']:.4f} |",
        f"| F1 | {cm['f1']:.4f} |",
        f"| ROC-AUC | {cm['roc_auc']:.4f} |",
        f"| PR-AUC | {cm['pr_auc']:.4f} |",
        f"| Brier score | {cm['brier_score']:.4f} |",
        "",
        "| Confusion outcome | Count | Revenue cost |",
        "| --- | --- | --- |",
        f"| False positives (predicted recoverable, wasn't) | {cm['false_positive_count']} | ₹{cm['false_positive_revenue_cost']:,.2f} |",
        f"| False negatives (predicted not recoverable, was) | {cm['false_negative_count']} | ₹{cm['false_negative_revenue_cost']:,.2f} |",
        f"| True positives | {cm['true_positive_count']} | — |",
        f"| True negatives | {cm['true_negative_count']} | — |",
        "",
        "Revenue cost definitions: a false positive's cost is the `amount` "
        "of payments the model told the business to expect back that never "
        "recovered; a false negative's cost is the `amount` of payments that "
        "*were* actually recoverable but the model would have told the "
        "business to skip. No separate outreach/campaign cost figure exists "
        "in this dataset, so cost is expressed directly in the transaction "
        "amounts misclassified.",
        "",
        "## Business metric: expected recoverable revenue",
        "",
        f"- Predicted recoverable revenue (Σ amount × recovery_probability): "
        f"₹{bm['predicted_recoverable_revenue']:,.2f}",
        f"- Actual recovered revenue (Σ amount where `eventually_recovered` "
        f"is true): ₹{bm['actual_recovered_revenue']:,.2f}",
        f"- Prediction error: ₹{bm['prediction_error']:,.2f} "
        f"({bm['prediction_error_pct']:+.2%} of actual)",
        "",
        "### Calibration (predicted probability deciles vs. actual recovery rate)",
        "",
        "| Mean predicted probability | Actual recovery rate | Count |",
        "| --- | --- | --- |",
    ]
    for b in bm["calibration_bins"]:
        lines.append(f"| {b['mean_predicted']:.3f} | {b['actual_rate']:.3f} | {b['count']} |")

    lines += [
        "",
        "A well-calibrated model has these two columns track closely — see "
        "`compute_business_metrics` in `ml/evaluation/evaluate.py`.",
        "",
        "## Top feature importances",
        "",
        "| Feature | Importance |",
        "| --- | --- |",
    ]
    for f in metadata["feature_importance"][:15]:
        lines.append(f"| {f['feature']} | {f['importance']:.4f} |")

    lines += [
        "",
        "Feature names are post-one-hot-encoding (e.g. "
        "`categorical__failure_category_NETWORK_ERROR`); see "
        "`ml/training/features.py` for the pre-encoding feature list and the "
        "point-in-time leakage-avoidance design.",
        "",
        "## Artifacts",
        "",
        f"- `ml/models/recovery_model.joblib` — the fitted sklearn `Pipeline` "
        f"(preprocessing + `{metadata['algorithm']}`)",
        "- `ml/models/recovery_model_meta.json` — this same metadata, "
        "consumed by `backend/app/services/recovery_predictor.py` and "
        "stamped onto every stored prediction "
        "(`model_name`, `model_version`, `feature_version`, `training_timestamp`)",
    ]

    DOCS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

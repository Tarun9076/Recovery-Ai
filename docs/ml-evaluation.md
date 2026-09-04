# RecoverAI — ML Evaluation Report (Phase 2)

Generated automatically by `ml/training/train.py` at 2026-09-03T20:46:45.915391+00:00. All numbers below come directly from that training run against the live database — nothing here is hand-typed.

## Model selection

Trained on 6673 failed payments (recovery rate 61.1%). Candidates were compared on **validation PR-AUC** rather than ROC-AUC alone: the business decision this model drives — act on a payment only above a probability threshold — is precision/recall-shaped, and PR-AUC is more sensitive to the positive-class ranking quality that decision depends on:

| Model | Validation PR-AUC | Validation ROC-AUC |
| --- | --- | --- |
| LogisticRegression **(selected)** | 0.7092 | 0.6305 |
| RandomForestClassifier | 0.7085 | 0.6327 |
| XGBClassifier | 0.7030 | 0.6136 |

**Selected model: LogisticRegression**, refit on train+validation data before final test evaluation below.

## Train / validation / test split

Temporal split (not random) — sorted by `payments.created_at`, 70% earliest / 15% / 15% latest — so validation and test always evaluate the model on data chronologically *after* what it trained on, matching how it would actually be used in production.

- Train: 4671 payments, 2026-07-09 02:02:52 → 2026-08-16 19:07:21
- Validation: 1001 payments, 2026-08-16 19:10:29 → 2026-08-25 07:32:27
- Test: 1001 payments, 2026-08-25 07:54:41 → 2026-09-03 01:32:39

## Test set metrics

Decision threshold for precision/recall/F1/FP/FN: **0.65** (the merchant's `minimum_recovery_probability` policy value).

| Metric | Value |
| --- | --- |
| Precision | 0.7084 |
| Recall | 0.5359 |
| F1 | 0.6102 |
| ROC-AUC | 0.6507 |
| PR-AUC | 0.7235 |
| Brier score | 0.2201 |

| Confusion outcome | Count | Revenue cost |
| --- | --- | --- |
| False positives (predicted recoverable, wasn't) | 135 | ₹413,183.24 |
| False negatives (predicted not recoverable, was) | 284 | ₹565,537.28 |
| True positives | 328 | — |
| True negatives | 254 | — |

Revenue cost definitions: a false positive's cost is the `amount` of payments the model told the business to expect back that never recovered; a false negative's cost is the `amount` of payments that *were* actually recoverable but the model would have told the business to skip. No separate outreach/campaign cost figure exists in this dataset, so cost is expressed directly in the transaction amounts misclassified.

## Business metric: expected recoverable revenue

- Predicted recoverable revenue (Σ amount × recovery_probability): ₹1,599,276.47
- Actual recovered revenue (Σ amount where `eventually_recovered` is true): ₹1,581,456.45
- Prediction error: ₹17,820.02 (+1.13% of actual)

### Calibration (predicted probability deciles vs. actual recovery rate)

| Mean predicted probability | Actual recovery rate | Count |
| --- | --- | --- |
| 0.330 | 0.317 | 101 |
| 0.502 | 0.530 | 100 |
| 0.559 | 0.540 | 100 |
| 0.596 | 0.530 | 100 |
| 0.628 | 0.660 | 100 |
| 0.654 | 0.620 | 100 |
| 0.678 | 0.680 | 100 |
| 0.710 | 0.680 | 100 |
| 0.743 | 0.760 | 100 |
| 0.805 | 0.800 | 100 |

A well-calibrated model has these two columns track closely — see `compute_business_metrics` in `ml/evaluation/evaluate.py`.

## Top feature importances

| Feature | Importance |
| --- | --- |
| categorical__failure_category_INSUFFICIENT_FUNDS | 1.1603 |
| categorical__failure_category_TECHNICAL_ERROR | 0.6533 |
| categorical__failure_category_INVALID_DETAILS | 0.5134 |
| categorical__failure_category_NETWORK_ERROR | 0.4297 |
| categorical__failure_category_TIMEOUT | 0.4240 |
| categorical__location_Chandigarh | 0.2889 |
| categorical__failure_category_AUTHENTICATION_FAILURE | 0.2277 |
| categorical__location_Ahmedabad | 0.2149 |
| categorical__device_type_desktop | 0.2001 |
| categorical__platform_android | 0.1945 |
| categorical__location_Chennai | 0.1642 |
| categorical__failure_category_UPI_FAILURE | 0.1465 |
| categorical__failure_severity_LOW | 0.1305 |
| numeric__payment_amount | 0.1275 |
| categorical__bank_Falcon Bank | 0.1209 |

Feature names are post-one-hot-encoding (e.g. `categorical__failure_category_NETWORK_ERROR`); see `ml/training/features.py` for the pre-encoding feature list and the point-in-time leakage-avoidance design.

## Artifacts

- `ml/models/recovery_model.joblib` — the fitted sklearn `Pipeline` (preprocessing + `LogisticRegression`)
- `ml/models/recovery_model_meta.json` — this same metadata, consumed by `backend/app/services/recovery_predictor.py` and stamped onto every stored prediction (`model_name`, `model_version`, `feature_version`, `training_timestamp`)

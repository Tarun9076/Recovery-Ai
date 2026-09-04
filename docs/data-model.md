# RecoverAI — Data Model & Synthetic Data (Phase 1)

## Entity-relationship overview

```text
Merchant (1) ──── (M) Customer
   │                    │
   │                    ├──── (M) Order ──── (M) Payment ──── (0..1) PaymentFailure
   │                    └──── (M) Payment
   │
   └──── (1) MerchantPolicy
```

- A `Customer`, `Order`, and `Payment` all carry `merchant_id` directly
  (denormalized) so merchant-scoped queries never need a join through
  `Customer`/`Order`.
- An `Order` can have multiple `Payment` rows (retry attempts,
  `attempt_number` 1..N) but each `Payment` belongs to exactly one `Order`.
- A `Payment` gets a `PaymentFailure` row **only if it failed** — the
  relationship is 0-or-1, enforced by a unique constraint on
  `payment_failures.payment_id`.
- `MerchantPolicy` is 1:1 with `Merchant`.

## Tables

### merchants
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| name | text | |
| email | text | unique, indexed |
| business_name | text | |
| currency | text | default `INR` |
| created_at | timestamptz | |

### customers
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| merchant_id | UUID FK → merchants.id | indexed |
| name, email, phone | text | |
| customer_since | timestamptz | |
| lifetime_value | float | sum of that customer's successful payment amounts |
| order_count | int | count of that customer's orders |
| successful_payment_count | int | |
| failed_payment_count | int | |
| created_at | timestamptz | |

`lifetime_value`, `order_count`, `successful_payment_count`, and
`failed_payment_count` are **not** sampled independently — the generator
accumulates them from the actual orders/payments it creates for that
customer (see [Internal consistency](#internal-consistency) below), and
`test_customer_aggregates_match_transactions`
(`backend/tests/test_data_generation.py`) asserts they match on every run.

### orders
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| merchant_id | UUID FK | indexed |
| customer_id | UUID FK | indexed |
| amount | float | |
| currency | text | |
| status | enum: `created`, `paid`, `failed`, `cancelled` | indexed |
| created_at | timestamptz | indexed |

### payments
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| merchant_id, order_id, customer_id | UUID FK | all indexed |
| razorpay_payment_id | text | unique, indexed; synthetic `pay_...` format |
| amount, currency | | same as the parent order |
| status | enum: `success`, `failed`, `authorized`, `captured`, `refunded` | indexed |
| method | enum: `upi`, `card`, `netbanking`, `wallet` | |
| bank, wallet, vpa | text, nullable | populated per `method` |
| email, contact | text | copied from the customer at attempt time |
| device_type, platform, location | | mobile/desktop/tablet, android/ios/web, city |
| attempt_number | int | 1-based, per order |
| failure_code, failure_reason, failure_source, failure_step | nullable | set only when `status = failed` |
| created_at, updated_at | timestamptz | indexed on `created_at` |

### payment_failures
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| payment_id | UUID FK → payments.id | unique, indexed |
| failure_category | enum (10 values, see below) | indexed |
| failure_severity | enum: `LOW`, `MEDIUM`, `HIGH` | |
| recoverability | enum: `LOW`, `MEDIUM`, `HIGH` | a **heuristic** label, see below |
| raw_failure_code, raw_failure_reason | text | Razorpay-style raw error |
| eventually_recovered | bool | **ground truth only**, see below |
| created_at | timestamptz | indexed |

Failure categories: `INSUFFICIENT_FUNDS`, `BANK_DECLINED`, `NETWORK_ERROR`,
`TIMEOUT`, `UPI_FAILURE`, `CARD_DECLINED`, `CARD_LIMIT`,
`AUTHENTICATION_FAILURE`, `INVALID_DETAILS`, `TECHNICAL_ERROR`, `UNKNOWN`.

### merchant_policies
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID PK | |
| merchant_id | UUID FK, unique | |
| minimum_recovery_probability | float | default `0.65` |
| max_customer_contacts | int | default `1` |
| max_campaign_amount | float, nullable | default `NULL` (no cap) |
| approval_required | bool | default `true` |
| allowed_actions | JSON list of strings | default `["email", "sms", "whatsapp"]` |
| created_at, updated_at | timestamptz | |

### Indexes

Beyond primary keys and the FK indexes above: `orders.status`,
`orders.created_at`, `payments.status`, `payments.created_at`,
`payment_failures.failure_category`, `payment_failures.created_at` — covering
every field section 4 of the spec calls out (`merchant_id`, `customer_id`,
`status`, `created_at`, `failure_category`).

## Ground truth vs. features

Two fields on `payment_failures` look similar but serve opposite purposes:

- **`recoverability`** (LOW/MEDIUM/HIGH) is a cheap heuristic computed *only*
  from information available the instant the payment fails: `failure_category`
  and `attempt_number`, plus noise. It's meant to represent "what a simple
  rule would say right now."
- **`eventually_recovered`** (bool) is the **ground truth** label for
  training/evaluating a future recovery-probability model. It's computed
  from a richer, independent signal set — the customer's historical success
  rate, lifetime value, segment, failure category, and attempt number — run
  through a logistic function with Gaussian noise (see below). It is
  **never returned by any API response** (`PaymentFailureRead` in
  `backend/app/schemas/payment.py` omits it deliberately) and is not used as
  an input anywhere else in the app.

Because the two are computed independently, they disagree a meaningful
fraction of the time (`test_recoverability_label_and_ground_truth_are_not_identical`) —
that gap is exactly the room a real model has to add value over the naive
heuristic. Neither field is a trivial function of `failure_category` alone
(`test_eventually_recovered_is_not_a_trivial_rule_on_category`).

## Synthetic data generation

`scripts/generate_data.py` (pure functions, no DB dependency) builds:

- **1 merchant** ("Bloomtrail Retail", fictional).
- **5,500 customers**, each assigned a segment at creation time (not stored
  as a column — it only drives generation):
  | Segment | Share | Success rate (mean) | Orders | Order size |
  | --- | --- | --- | --- | --- |
  | HIGH_VALUE_LOYAL | 8% | ~97% | 8–26 | ₹2,500–16,000 |
  | NORMAL | 55% | ~92% | 2–9 | ₹400–5,500 |
  | LOW_INTENT | 27% | ~78% | 1–4 | ₹200–2,200 |
  | NEW | 10% | ~88%, high variance | 0–2 | ₹300–3,500 |
- **≥22,000 orders**, each simulated as a chain of payment attempts: pick a
  method (UPI 55% / card 25% / netbanking 12% / wallet 8%), compute a
  failure probability from the method's base rate × the customer's segment
  multiplier (and the incident boost — see below), and on failure pick a
  failure category from a method-specific weighted distribution (e.g. UPI
  attempts fail into `UPI_FAILURE` most often, card attempts into
  `CARD_DECLINED`/`INSUFFICIENT_FUNDS`/`CARD_LIMIT`). Whether the customer
  retries depends on segment, category (transient categories retry more,
  `INSUFFICIENT_FUNDS` retries less), and attempt number, up to a
  segment-specific cap.
- **≥50,000 (targets 100,000) payments** — the generator keeps adding orders
  (weighted toward customers who already transact) past the 22,000-order
  floor until the payment-attempt target is hit.
- Timestamps span an 8-week window with hour-of-day weighting (low
  overnight, peak evening), a weekend volume bump, a 3-day "busy period",
  and the incident window below — so normal, busy, weekend, and incident
  periods are all represented for temporal analysis.

At full scale (5,500 customers / 100,000 payments) generation takes
~15–20 seconds.

### The injected incident

A 4-day window is chosen inside the 8-week timeline. One of ten fictional
banks ("Zenith Bank") is designated the incident bank. During that window,
UPI attempts where the customer's linked bank is Zenith Bank fail at a
**60% rate** (vs. the customer's normal rate), with failures forced toward
`UPI_FAILURE`/`BANK_DECLINED`/`TIMEOUT`; other banks get a smaller bump. The
net effect, verified against a generated run:

- UPI failure rate outside the window: ~5%
- UPI failure rate inside the window: ~11–13%
- Of UPI payments that failed inside the window, roughly **60%+ trace back
  to the single incident bank**, which normally accounts for only ~10% of
  customers.

Both numbers come from the generator's own random process each run (see the
`incident_window` / `incident_bank` fields on `GeneratedDataset`) — nothing
about the incident is hardcoded into the frontend or a fixed constant table.
`test_incident_window_shows_upi_failure_spike_concentrated_on_one_bank`
(`backend/tests/test_data_generation.py`) checks both properties hold on a
freshly generated dataset.

### Internal consistency

Each customer's `order_count` / `successful_payment_count` /
`failed_payment_count` / `lifetime_value` are accumulated in a running
per-customer state dict *as* that customer's orders/payments are generated
(including "top-up" orders added later to hit the payment-count target), then
written onto the final customer record — so they are guaranteed to match the
actual generated transactions rather than being sampled separately.

## Seeding

`scripts/seed_database.py`:

1. Creates the schema if missing (`SQLModel.metadata.create_all`).
2. Calls `generate_dataset(...)`.
3. If a merchant with the same email already exists, deletes its
   `payment_failures` → `payments` → `orders` → `customers` →
   `merchant_policies` → itself, then re-inserts fresh — so re-running the
   script is idempotent rather than accumulating duplicates.
4. Bulk-inserts merchant → customers → orders → payments →
   payment_failures → merchant_policy, in batches of 1,000 rows (Postgres
   caps bound parameters per query at 65,535; payments alone have ~24
   columns, so larger batches overflow that limit).

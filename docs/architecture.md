# RecoverAI — Architecture

RecoverAI is an AI Revenue Recovery Orchestrator for Razorpay merchants. This
document is the technical companion to the [README](../README.md) — read
that first for the product framing (problem/solution/safety); this covers
how the system is actually built, request by request.

## System overview

```text
Merchant
   │  HTTP (JSON)
   ▼
frontend (Next.js 16, App Router)
   │  fetch, server-side and client-side
   ▼
backend (FastAPI + SQLModel)  ───────────────▶  postgres 16 (6+ tables)
   │
   ├──▶ ML Recovery Engine        app/services/recovery_predictor.py,
   │                              ml/models/*.joblib
   │
   ├──▶ AI Investigation Agent    app/agents/ — deterministic pipeline,
   │                              one LLM call for prose only
   │
   └──▶ Policy Engine             app/services/policy_engine.py
             │
             ▼
       Campaign Lifecycle (campaign_service.py)
       create ──▶ merchant approval ──▶ execute
             │
             ▼
       Razorpay (Payment Links API)
             │
             ▼
       Customer pays (or doesn't)
             │
             ▼
       Webhook: X-Razorpay-Signature
             │
             ▼
       Signature verified?  ──No──▶  recorded, rejected, nothing mutated
             │
            Yes
             │
             ▼
       Verified Recovery (revenue_recovered,
       recovery_rate — computed fresh on every read)
```

- **frontend** (`frontend/`): Next.js App Router, TypeScript, Tailwind.
  Server Components fetch directly from the FastAPI backend
  (`cache: "no-store"` — nothing is cached client-side either); one Client
  Component (`DemoControlPanel`) drives the interactive demo flow via
  direct browser fetches to `NEXT_PUBLIC_API_URL`.
- **backend** (`backend/`): FastAPI + SQLModel (SQLAlchemy 2.0 + Pydantic).
  Layering: `app/api` (routes — request/response shape only, no business
  logic) → `app/services` (campaign lifecycle, policy engine, webhook
  processing, metrics, demo controls) → `app/agents` (the investigation
  agent, intentionally isolated — nothing under `app/services/` imports it)
  → `app/models` (SQLModel tables) → `app/db` (engine/session).
  `app/schemas` holds the Pydantic response models, kept separate from DB
  models specifically so an internal-only field (ground truth, a secret)
  can never leak through a serializer by accident.
- **postgres**: one database. Core dataset (`merchants`, `customers`,
  `orders`, `payments`, `payment_failures`, `merchant_policies` — see
  [data-model.md](data-model.md)) plus the workflow tables added in later
  phases (`recovery_predictions`, `recovery_opportunities`,
  `recovery_campaigns`, `recovery_actions`, `webhook_events`, `audit_logs`,
  `ai_investigations`). `POST /api/demo/reset` clears only the workflow
  tables — the core dataset is never touched, which is what makes Demo Mode
  deterministic across resets.
- **ml/**: `training/` (feature engineering + model comparison/selection),
  `evaluation/` (pure metric functions shared by training and the eval
  report), `models/` (the fitted pipeline + metadata JSON the backend loads
  at serving time — not baked into the Docker image, see
  [Local & Docker environments](#local--docker-environments)).
- **scripts/**: `generate_data.py` (pure, DB-free synthetic generator —
  returns plain dicts, backs both the seeded Postgres database and the
  fast in-memory fixtures the test suite uses) and `seed_database.py`
  (generates + bulk-inserts, idempotently).

## Request flow: investigation

1. Merchant asks a question via `POST /api/ai/investigate` (or the Demo
   Control Panel's "Run Investigation").
2. `RevenueRecoveryAgent.investigate()` runs a **fixed Python pipeline** —
   `DataCollector` (failure stats + spike-vs-baseline analysis, pure SQL
   aggregates) → `FailureAnalyzer` (ranks anomalies by severity) →
   `RootCauseAnalyzer` (turns ranked anomalies into `Finding` objects,
   `evidence` strings formatted directly from real numbers) →
   `OpportunityRanker` (Phase 2 ML model) → `InterventionPlanner`
   (merchant-policy-gated recommendation, no LLM involvement).
3. The LLM is called **exactly once**, handed everything the pipeline
   already computed as JSON, and asked only for prose (`LLMNarrative`: a
   summary and per-finding/per-recommendation explanation strings). See the
   README's [Safety](../README.md#safety) section for why this can only
   ever affect two `str` fields on the final response.
4. The response is persisted to `ai_investigations` for later listing
   (`GET /api/ai/investigations`) and returned.

## Request flow: campaign lifecycle

```text
create ──▶ PENDING_APPROVAL ──approve──▶ APPROVED ──execute──▶ RUNNING ──▶ COMPLETED / FAILED
                                                                                  │
                                                                          (per-action; a webhook
                                                                           later flips an
                                                                           EXECUTED action to
                                                                           RECOVERED)
```

1. `POST /api/recovery/campaigns` — for each `payment_id`, recomputes the
   ML prediction **fresh** (never trusts a value the frontend sent) and
   runs every policy check (`PolicyEngine`); only qualifying payments are
   included, everything else is reported back as `excluded` with a reason.
   Creates one `RecoveryAction` per included payment, status `PENDING`.
2. `POST .../approve` — re-validates the campaign against current policy
   (it may have changed since creation), records `approved_by`. Does
   **not** execute — approval and execution are deliberately separate
   steps (see below), each independently idempotent (a second call on an
   already-approved/executed campaign is rejected with `409`, not
   silently re-run).
3. `POST .../execute` — only valid on an `APPROVED` campaign. For each
   `PENDING` action: calls `PaymentProvider.create_recovery_link()` (mock
   or real Razorpay test-mode, per `RAZORPAY_MODE`), records the raw
   response, and marks the action `EXECUTED` (success) or `FAILED`
   (provider error — caught and recorded, never crashes the campaign).
   **Creating a link is never itself counted as recovered revenue.**
4. A verified webhook (see below) is the only thing that can later move an
   `EXECUTED` action to `RECOVERED`.

Approve and execute were split into two real API steps in Phase 8
specifically so a demo (and a real merchant workflow) can show
"authorized" and "money actually sent" as genuinely distinct moments — the
underlying `campaign_service.approve_campaign(..., auto_execute=True)`
still exists as a single-call convenience for any caller that wants the old
atomic behavior (every pre-Phase-8 service-layer test still passes
unmodified because of this default).

## Request flow: verified recovery

1. Razorpay (or the mock simulator, see below) POSTs to
   `/api/webhooks/razorpay` with `X-Razorpay-Signature`.
2. The raw request body is recorded to `webhook_events` — keyed by
   `(provider, event_id)` under a database **unique constraint** —
   *before* signature verification runs, so even a request that fails
   verification is auditable, and two near-simultaneous redeliveries can't
   both pass a naive check-then-insert race (an `IntegrityError` on the
   duplicate insert is caught and treated as "already recorded").
3. Signature verified (constant-time HMAC-SHA256, the SDK's own
   `Utility.verify_webhook_signature`)? If not, the event stays recorded as
   unverified and the request is rejected — nothing downstream ever runs.
4. If verified and the event is `payment_link.paid`: find the matching
   `RecoveryAction` by `payment_link_id` (a real indexed column — see
   [Performance notes](#performance-notes)), mark it `RECOVERED` with the
   webhook's own `amount_paid` (**never** `expected_recovery`), update the
   linked opportunity, write an audit log entry. An action already
   `RECOVERED` short-circuits to `"already_recorded"` — a redelivered
   webhook can never double-count.
5. `RecoveryCampaign` itself is never written to here — its
   `revenue_recovered`/`recovery_rate` are computed fresh from its actions'
   `recovered_amount` on every read (`metrics_service.py`), so there is no
   cached campaign total that could ever drift from what actions actually
   confirmed.

**Mock simulation** (`POST /api/mock/simulate-payment`, `RAZORPAY_MODE=mock`
only): builds a `payment_link.paid` payload shaped exactly like a real one,
self-signs it with a fixed mock secret, and feeds it through the **exact
same** `process_razorpay_webhook()` a genuine Razorpay delivery goes
through — signature verification included. Every response is stamped
`"simulated": true` so it can never be confused with a real confirmation.
`POST /api/demo/simulate-provider-failure` uses the same real
create→approve→execute pipeline but swaps in a `FailingPaymentProvider`
that always raises, so the demo can show the genuine failure path (a
`FAILED` action, a real audit entry, ₹0 recovered, the payment still
eligible for a retry) without needing an actual unreliable network call.

## Why the ground truth field is fenced off

`payment_failures.eventually_recovered` is the label the Phase 2 ML model
is trained to predict — whether a payment recovered *organically* in the
synthetic data, independent of any RecoverAI action. It is deliberately:

- **excluded from every API schema** (`PaymentFailureRead`, every
  prediction/opportunity/investigation response) — enforced by tests that
  assert the string `eventually_recovered` never appears in a response
  body, not just by omitting the field from a schema and hoping;
- **never used as a live prediction feature** anywhere in
  `ml/training/features.py`'s `LEAKY_COLUMNS` exclusion list;
- used in exactly one place outside training/evaluation: the aggregate (never
  per-payment) baseline-vs-RecoverAI comparison at
  `/api/evaluation/baseline-comparison`, which sums it server-side into a
  single number and never returns a row-level value.

See [data-model.md](data-model.md#ground-truth-vs-features) for the full
reasoning and the synthetic-data generation model.

## API surface

| Area | Endpoints |
| --- | --- |
| Health | `GET /health` |
| Dashboard | `GET /api/dashboard/summary` |
| Payments / customers | `GET /api/payments[/failed][/{id}]`, `GET /api/customers[/{id}]` |
| ML predictions | `POST /api/recovery/analyze`, `GET /api/recovery/metrics`, `GET /api/recovery/opportunities[/{payment_id}]` |
| Campaigns | `POST/GET /api/recovery/campaigns`, `GET /.../{id}`, `POST /.../{id}/approve\|execute\|reject` |
| Investigation agent | `POST /api/ai/investigate`, `GET /api/ai/investigations` |
| Razorpay webhook | `POST /api/webhooks/razorpay` |
| Mock provider | `POST /api/mock/simulate-payment` |
| Evaluation | `GET /api/evaluation/model\|business\|baseline-comparison` |
| Demo controls | `POST /api/demo/reset`, `POST /api/demo/simulate-provider-failure` |

All list endpoints return `{total, limit, offset, items}`. Nothing is
hardcoded — every number in every response is computed from live tables (or,
for `/api/evaluation/model`, read fresh from the last real training run's
metadata file) at request time.

## Performance notes

Two real anti-patterns were found and fixed during Phase 8's hardening
pass, both against the real ~100k-row dev database, not a guess:

- `app/agents/tools.py`'s `get_failure_statistics`/`get_recovery_metrics`
  originally loaded the entire `payments`/`recovery_predictions` tables as
  ORM objects to count/sum in a Python loop. Rewritten to pure SQL
  aggregation (`COUNT`/`SUM`/`AVG`/`GROUP BY`) — no row is ever fetched
  into Python just to be counted.
- `recovery_predictor._upsert_prediction` ran one `SELECT` per payment
  inside `POST /api/recovery/analyze`'s loop — an N+1 pattern that measured
  **~39 seconds** for 6,673 failed payments. Fixed by batch-fetching
  existing predictions once via a single `WHERE payment_id IN (...)`
  before the loop; the same call now takes **~6.9 seconds**.
- `webhook_service._find_action_by_payment_link_id` loaded every
  `EXECUTED`/`RECOVERED` `RecoveryAction` into Python to filter a JSON
  field in memory. Fixed by adding a real indexed
  `RecoveryAction.payment_link_id` column, queried directly.

Every other list/aggregate query in the codebase was spot-checked and is
correctly bounded — by pagination (`limit`/`offset` with an enforced cap),
by a foreign-key scope (one campaign's actions, one customer's contacts),
or by SQL-side `GROUP BY` (bounded by category/bank/day cardinality, not
row count).

## Local & Docker environments

- **Docker Compose** (`docker-compose.yml`): `postgres:16`, `backend`
  (built from `backend/Dockerfile`, context = repo root so it can also
  carry `scripts/`), `frontend` (`next dev` in a container). `ml/` is a
  **bind mount**, not baked into the backend image — training a new model
  on the host is picked up immediately without a rebuild. `docker compose
  up --build` brings up all three; seed with
  `docker compose exec backend python /app/scripts/seed_database.py`, train
  with `docker compose exec backend python /app/ml/training/train.py`.
- **Before Docker was available in this sandboxed dev environment**, Phase
  1 was first verified without it, using a portable PostgreSQL 18 binary
  (no installer, no admin rights, downloaded from a GitHub release) run
  out of a scratch directory, with the exact same `DATABASE_URL`-driven
  code path Docker Compose uses. Once Docker Desktop was installed, the
  same code was re-verified through the real `docker compose up` path.
- **Local dev servers during Phase 8's frontend work**: iterating against
  Docker's `backend`/`frontend` containers means a full image rebuild per
  change, so that work used `uvicorn --reload`/`next dev` directly against
  the same Postgres instance instead (see `.claude/launch.json` if present)
  — functionally identical to the Docker path, just faster to iterate on.
  The Docker Compose path remains the intended way to run RecoverAI.

## Non-goals

No authentication (see the README's [Safety](../README.md#safety) section —
this is a deliberate, documented gap for a single-merchant demo, not an
oversight). No live Razorpay execution — `RAZORPAY_MODE=test` only reaches
`https://api.razorpay.com` with test-mode credentials, and the client
factory refuses to build a client for a key that doesn't start with
`rzp_test_`. No background task queue — campaign execution and bulk ML
re-analysis run synchronously inside the request; acceptable at this
dataset's scale (single-digit seconds, see
[Performance notes](#performance-notes)) but not how a production version
would be built.

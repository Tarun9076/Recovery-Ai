# RecoverAI — AI Revenue Recovery Orchestrator

RecoverAI turns a merchant's failed Razorpay payments into a governed,
auditable recovery pipeline: an ML model ranks which failures are worth
chasing, an AI agent explains why in plain language, a policy engine decides
what's allowed, the merchant approves, RecoverAI executes through Razorpay,
and revenue is only ever counted as recovered once a cryptographically
verified webhook confirms it. Built for the Razorpay Buildathon.

## Table of contents

- [The problem](#the-problem)
- [The solution](#the-solution)
- [Why AI, and where it's kept on a leash](#why-ai-and-where-its-kept-on-a-leash)
- [Architecture](#architecture)
- [ML approach](#ml-approach)
- [Agent architecture](#agent-architecture)
- [Razorpay integration](#razorpay-integration)
- [Safety](#safety)
- [Metrics](#metrics)
- [Demo](#demo)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Testing](#testing)
- [Future roadmap](#future-roadmap)

## The problem

Payments fail constantly — insufficient funds, a bank timeout, an expired
card, a flaky UPI rail — and most of that failed revenue is never chased.
Merchants either ignore it, or blast every failure with the same generic
retry email regardless of whether that specific customer/payment is likely
to ever pay. Both are wrong: ignoring it leaves real, recoverable revenue on
the table; blindly retrying everything burns customer goodwill and outreach
budget on payments that were never coming back.

## The solution

RecoverAI treats recovery as a ranking and governance problem, not a
blast-everyone problem:

1. **Predict** which failed payments are actually worth recovering, and by
   how much (a trained ML model, not a hand-tuned rule).
2. **Explain** why, in language a merchant can act on (an AI agent that
   narrates real numbers — see [Safety](#safety) for why it can't invent
   them).
3. **Gate** every recommendation through the merchant's own policy
   (probability threshold, contact limits, allowed channels, campaign
   size caps) before it's ever shown as actionable.
4. **Execute only what's approved** — a real Razorpay payment link, created
   through an explicit merchant approval step, never automatically.
5. **Count only verified revenue** — a payment is "recovered" only after a
   signature-verified Razorpay webhook confirms it; everything before that
   is a prediction or an attempt, and the system is careful never to
   conflate the two.

## Why AI, and where it's kept on a leash

Two different AI systems do two different jobs here, and neither is trusted
with money:

- A **trained ML model** (Phase 2) scores *this specific payment's*
  probability of organic recovery, using features about the customer, the
  failure, and the transaction — this is what actually decides ranking and
  expected value.
- An **LLM investigation agent** (Phase 3) answers open-ended merchant
  questions ("why did failures spike this week?") by narrating numbers a
  deterministic Python pipeline already computed. It never runs its own
  queries and never invents a figure — see [Agent architecture](#agent-architecture).

Both are structurally prevented from touching money directly. See
[Safety](#safety) for exactly how.

## Architecture

```text
Merchant
   │  asks a question, or reviews a campaign for approval
   ▼
Payment Data (Postgres: payments, orders, customers, failures)
   │
   ├──▶ ML Recovery Engine ─────────┐   probability, expected_recovery, SHAP
   │                                 │
   └──▶ AI Investigation Agent ─────┤   deterministic pipeline; one LLM call,
                                     │   prose only (see Safety)
                                     ▼
                              Policy Engine
            probability threshold · contact limits · allowed
                 channels · campaign size cap
                                     │
                                     ▼
                          Merchant Approval  (explicit, per campaign)
                                     │
                                     ▼
                                Execute
                                     │
                                     ▼
                    Razorpay (Payment Links API)
                                     │
                                     ▼
                     Customer pays the link, or doesn't
                                     │
                                     ▼
                  Webhook  (X-Razorpay-Signature, verified
                             constant-time before anything mutates)
                                     │
                                     ▼
                   Verified Recovery (revenue_recovered,
                    recovery_rate — computed fresh on every read)
```

**Stack**: Next.js 16 (App Router, TypeScript, Tailwind) frontend; FastAPI +
SQLModel (SQLAlchemy 2.0 + Pydantic) backend; PostgreSQL; scikit-learn/XGBoost
+ SHAP for the ML engine; Google Gemini for the agent's narrative layer
(with a deterministic offline fallback); the official `razorpay` Python SDK
for Payment Links.

**Layering** (backend): `app/api` (routes, request/response only) →
`app/services` (business logic — campaign lifecycle, policy checks, webhook
processing, metrics) → `app/agents` (the investigation agent, isolated from
every other service) → `app/models` (SQLModel tables) → `app/db`
(engine/session). `app/schemas` holds the Pydantic response models exposed
over HTTP, kept separate from DB models so internal-only fields (ground
truth, secrets) can never leak through a serializer by accident.

See [docs/architecture.md](docs/architecture.md) for the full request-flow
walkthrough and [docs/data-model.md](docs/data-model.md) for the schema.

## ML approach

A `LogisticRegression`/`RandomForestClassifier`/`XGBClassifier` comparison
(`ml/training/train.py`), model-selected on validation PR-AUC (more sensitive
than ROC-AUC to the positive-class ranking quality the business decision
actually depends on), trained on point-in-time features — every
customer-history feature (lifetime value, prior success rate, prior failed
attempts) is computed from *only that customer's transactions before the
payment being scored*, never their full history, so the model can't peek at
information it wouldn't have at prediction time in production. Split
temporally (70/15/15 by `created_at`, not randomly), so validation and test
always evaluate on data chronologically after what the model trained on.

SHAP (`LinearExplainer`/`TreeExplainer`, matching whichever model was
selected) explains every individual prediction, summed back from one-hot
sub-columns to the original raw feature so `top_factors` can only ever name
a real input, never an invented one.

The ground-truth label `payment_failures.eventually_recovered` — whether a
payment organically recovered in the synthetic data, independent of any
RecoverAI action — is used *only* for training/evaluation. It is
structurally excluded from every schema exposed over the API (`PaymentFailureRead`
never includes it) and never used as a live prediction feature; see
[docs/data-model.md](docs/data-model.md#ground-truth-vs-features).

Full metrics, the model-selection table, and the calibration report:
[docs/ml-evaluation.md](docs/ml-evaluation.md) (generated from an actual
training run — nothing hand-typed) and live at `/evaluation` in the running
app (re-read from `ml/models/recovery_model_meta.json` on every request, so
retraining updates it immediately).

## Agent architecture

The investigation agent (`app/agents/`) is a **fixed, deterministic Python
pipeline**, not an LLM tool-calling loop:

```text
DataCollector → FailureAnalyzer → RootCauseAnalyzer → RecoveryPredictor
   → OpportunityRanker → InterventionPlanner → (one LLM call) → response
```

Every number in the final response — `revenue_at_risk`,
`recoverable_revenue`, `expected_recovery`, `confidence`,
`recommended_action` — is computed by that pipeline from real database
queries and the Phase 2 ML model, *before* the LLM is ever called. The LLM
(Google Gemini, `google-genai`) is invoked exactly once per investigation,
and only to write prose explaining data it's hands: two `str` fields,
`summary` and lists of `root_cause_narratives`/`recommendation_reasons`. See
[Safety](#safety) for the mechanism that makes this a structural guarantee,
not a convention. If Gemini is unavailable or returns malformed JSON twice
in a row, a deterministic template-based narrator (`MockLLMClient`) takes
over automatically — the endpoint never fails or blocks on the LLM.

## Razorpay integration

`app/integrations/razorpay/` wraps the official `razorpay==2.0.1` Python
SDK — every claim in its docstrings (exception-mapping behavior, endpoint
paths, signature-verification algorithm) is cited against the actual
installed SDK source, not guessed from docs alone. The integration surface
is deliberately narrow: **create/fetch/cancel a Payment Link, fetch a
payment's status, verify a webhook signature** — nothing that moves money
any other way (no refunds, payouts, or transfers exist anywhere in this
codebase).

A `PaymentProvider` abstraction (`app/services/payment_provider.py`) has two
implementations behind one interface — `MockPaymentProvider` (default;
generates a fake link, no network call) and `RazorpayPaymentProvider` (real
test-mode API calls) — selected by `RAZORPAY_MODE`. Webhook signature
verification uses the SDK's own constant-time HMAC-SHA256 comparison
(`hmac.compare_digest` under the hood); every inbound request is recorded to
`webhook_events` under a `(provider, event_id)` unique constraint *before*
anything else happens, so redelivery can never double-process (see
[Metrics](#metrics) for what that guarantees downstream). Live execution is
explicitly out of scope for this whole project — `get_razorpay_client()`
refuses to build a client unless `RAZORPAY_KEY_ID` has the `rzp_test_`
prefix Razorpay itself uses for test-mode keys, so a misconfigured live key
fails loudly instead of silently being able to move real money.

## Safety

**A recovery action is not successful until a verified webhook says so.**
Creating a payment link is a delivery event, not a financial one — the
*only* code path in this entire codebase that may ever set
`RecoveryAction.status = RECOVERED` or populate `recovered_amount` is
`app/services/webhook_service.py`, after cryptographic signature
verification, using the webhook's own `amount_paid` (never
`expected_recovery`, a prediction). Every other write path — campaign
execution, mock simulation — can only reach `EXECUTED` or `FAILED`.

**No campaign executes without merchant approval**, and approval and
execution are separate steps (`campaign_service.approve_campaign` /
`execute_campaign`), each independently policy-checked, each idempotent (a
second approve/execute on the same campaign is rejected, not silently
re-run).

**The AI agent cannot execute financial actions, bypass policy, mark a
payment successful, fabricate recovered revenue, or alter a transaction
amount** — verified structurally, not just by convention:

- The LLM client (`app/agents/llm_client.py`) never imports a database
  session and the Gemini call is configured with no tool/function-calling
  capability — there is no code path for it to write anything, anywhere.
- `revenue_recovery_agent.py`'s merge step
  (`decision.model_copy(update={"root_cause": ..., "reason": ...})`) only
  ever overwrites two `str` fields on an already-computed
  `StructuredDecision`. Every numeric/action field —
  `recommended_action`, `expected_recovery`, `confidence`,
  `revenue_at_risk` — is decided by `InterventionPlanner` (pure Python,
  merchant-policy-driven) before the LLM is even called, and the LLM's own
  response schema (`LLMNarrative`) has no field for a number or an action to
  travel through even if it tried.
- The system prompt additionally instructs the model never to invent,
  estimate, or adjust a number — defense in depth on top of the structural
  guarantee above, not a substitute for it.
- Zero files under `app/services/` (campaign lifecycle, policy engine,
  webhook processing, payment provider) import anything from `app/agents/`
  — the two systems that decide/execute money and the one that narrates are
  completely decoupled.

**Known limitation, called out deliberately rather than silently shipped**:
no endpoint in this API has any authentication. That's an accepted gap for
a single-merchant buildathon demo — no phase of this project ever asked for
multi-tenant auth — but it means every endpoint, including
`POST /api/demo/reset` (destructive) and campaign approve/execute
(financial, in test mode), is reachable by anyone who can reach the
backend's network address. **Do not deploy this publicly without adding
authentication first.**

**Input validation & injection**: every endpoint is typed (UUID path
params, Pydantic-validated bodies with explicit length/range bounds) — no
raw dict body is ever accepted. Every database query goes through
SQLModel/SQLAlchemy's parameterized query builder; the only raw SQL in the
codebase is a hardcoded `SELECT 1` healthcheck and the ML feature-engineering
queries, which interpolate only a fixed `WHERE` clause string chosen from a
hardcoded pair of options — actual values always travel through bound
`:params`, never string-formatted into the query.

## Metrics

Computed fresh from the database on every read — nothing is cached or
precomputed, and every number traces to a real row:

- **Revenue at risk** — Σ amount of all currently-failed payments.
- **Recoverable revenue** — Σ `expected_recovery` (amount × ML probability)
  across open opportunities.
- **Revenue recovered** — Σ `recovered_amount` across actions the webhook
  pipeline has actually confirmed. Never derived from `expected_recovery`.
- **Recovery rate** — recovered ÷ recoverable.
- **Baseline vs. RecoverAI** (`/api/evaluation/baseline-comparison`) —
  what the same set of *targeted* payments would have recovered organically
  (the synthetic dataset's own `eventually_recovered` ground truth,
  aggregated, never exposed per-payment) versus what RecoverAI's verified
  webhooks actually confirmed for them. Deliberately scoped to only the
  payments RecoverAI targeted, not the whole portfolio — comparing against
  untouched payments would make RecoverAI look like it lost money simply
  because most of a 100k-row dataset is never touched in one demo run.

Model evaluation metrics (precision/recall/F1/ROC-AUC/PR-AUC/Brier score,
confusion-matrix revenue cost, calibration) are documented in
[docs/ml-evaluation.md](docs/ml-evaluation.md) and served live at
`GET /api/evaluation/model`.

## Demo

Three pages, once both servers are running:

- **`/`** — the payment-health dashboard (Phase 1): totals, failure rate,
  daily trend, category breakdown.
- **`/evaluation`** — real ML metrics, live business metrics, and the
  baseline-vs-RecoverAI comparison.
- **`/demo`** — the Demo Control Panel. Every button calls the real
  backend; nothing here is fabricated in the browser:
  - **Run Investigation** — asks the AI agent a question, shows its
    findings and recommendations.
  - **Generate / Approve / Execute Campaign** — walks one real failed
    payment through the full pipeline; the target-payment picker only
    lists payments the ML model already scores above the merchant's policy
    threshold, so the demo doesn't stall on a payment that was never going
    to qualify.
  - **Simulate Customer Payment** — feeds a self-signed
    `payment_link.paid` payload through the *exact same* webhook
    verification pipeline a real Razorpay delivery uses; the response is
    always stamped `"simulated": true`.
  - **Simulate Provider Failure** — runs the same real pipeline but forces
    the execute step to fail like a gateway timeout, demonstrating the
    failure path: a `FAILED` action, a real audit-log entry, ₹0 ever
    recorded as recovered, and the payment still eligible for a fresh
    retry campaign.
  - **Reset Demo** — clears every campaign/action/opportunity/prediction/
    webhook-event/audit-log row via SQL `DELETE`, leaving the underlying
    synthetic payment dataset untouched — reset as many times as you like,
    the same known incident is still there.
  - Every campaign card renders its own **audit trail** — the raw
    `audit_logs` timeline for that campaign, chronological, so "what AI
    concluded → what the merchant approved → what the system executed →
    what actually happened" is a single readable list. Also reachable
    directly at `/campaigns/{id}`.

## Setup

### Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend python /app/scripts/seed_database.py
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000 (interactive docs at `/docs`)
- Postgres: `localhost:5432` (`recoverai` / `recoverai_pw` / db `recoverai`)

The trained model isn't baked into the backend image (`ml/` is a bind mount,
so retraining on the host is picked up without a rebuild) — train it once
before the ML/evaluation endpoints will work:

```bash
docker compose exec backend python /app/ml/training/train.py
```

### Without Docker

Requires Python 3.11+, Node 20+, and a running PostgreSQL instance.

```bash
# 1. backend/.env with DATABASE_URL pointing at your Postgres instance
cd backend && pip install -r requirements.txt && cd ..

# 2. Generate schema + seed synthetic data (~5,500 customers, ~100k payments)
python scripts/seed_database.py

# 3. Train the recovery model (writes ml/models/*)
python ml/training/train.py

# 4. Backend
cd backend && uvicorn app.main:app --reload

# 5. Frontend, in another terminal
cd frontend && npm install && npm run dev
```

### Reseeding / regenerating data

```bash
python scripts/generate_data.py --customers 5500 --min-orders 22000 --payments 100000
python scripts/seed_database.py --customers 5500 --min-orders 22000 --payments 100000
```

`seed_database.py` is idempotent — re-running it wipes and re-inserts the
same merchant's rows (matched by email) rather than duplicating them.
Re-run `ml/training/train.py` after reseeding so the model reflects the new
data.

## Environment variables

See [.env.example](.env.example) for the full, commented list. Summary:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | Postgres connection string | `postgresql+psycopg://recoverai:recoverai_pw@localhost:5432/recoverai` |
| `RAZORPAY_MODE` | `mock` (no network calls) or `test` (real Razorpay test-mode API) | `mock` |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Test-mode credentials from the Razorpay Dashboard; must start with `rzp_test_` | unset |
| `RAZORPAY_WEBHOOK_SECRET` | From Dashboard → Settings → Webhooks | unset |
| `LLM_API_KEY` | Google Gemini key (aistudio.google.com, free tier); unset falls back to a deterministic mock narrator | unset |
| `LLM_MODEL` | Gemini model name | `gemini-3.6-flash` |
| `API_URL` | Server-side backend URL for the frontend's Server Components | `http://localhost:8000` |
| `NEXT_PUBLIC_API_URL` | Browser-facing backend URL, baked into the client bundle | `http://localhost:8000` |

## Testing

```bash
cd backend
pytest -v
```

200 tests, run against a real PostgreSQL database (`recoverai_test`,
dropped and recreated fresh every test session — schema changes never need
a manual migration there) with a small fixed-seed dataset. Coverage spans
every phase: the synthetic data generator's statistical properties, ML
feature-engineering leakage avoidance, model training/evaluation metrics,
the investigation agent's deterministic-pipeline guarantees (including that
`eventually_recovered` never reaches an API response), the campaign
lifecycle and policy engine, Razorpay integration (signature verification,
error-code translation) against the real installed SDK, webhook idempotency
(duplicate delivery, duplicate event, duplicate approve/execute), and the
Phase 8 evaluation/demo endpoints.

Frontend: `npm run lint` and `npx tsc --noEmit` inside `frontend/`. There is
no frontend test suite yet — the demo pages were verified by driving them
live against the real backend/ML model/Gemini LLM through a browser, not
just by compiling (see [docs/architecture.md](docs/architecture.md)).

## Future roadmap

Explicitly out of scope for this buildathon build, in rough priority order
for a real product:

- **Authentication & multi-tenancy** — the single biggest gap (see
  [Safety](#safety)); every endpoint is currently open.
- **Live Razorpay execution** — deliberately never enabled; would need a
  real compliance/risk review before ever leaving test mode.
- **Outreach channels beyond a payment link** — SMS/email/WhatsApp
  reminders, retry-in-app prompts.
- **Multi-merchant policy management UI** — policies are currently a
  single DB row per deployment, not merchant-self-serve.
- **Async/background execution** — campaign execution and bulk ML
  re-analysis currently run synchronously inside the request; fine at this
  dataset's scale (single-digit seconds — see the performance notes in
  [docs/architecture.md](docs/architecture.md)) but a real product would
  move both to a task queue.
- **A richer agent** — still deliberately non-tool-calling for the
  guarantees in [Safety](#safety), but could investigate a wider range of
  questions (cohort-level, customer-level) than the current spike/anomaly
  focus.

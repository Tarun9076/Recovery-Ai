# RecoverAI

**AI Revenue Recovery Orchestrator** — an ML-ranked, policy-gated, webhook-verified pipeline for recovering failed Razorpay payments.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![Tests](https://img.shields.io/badge/tests-230%20passing-brightgreen)

When a payment fails, most systems either ignore it or send the same generic retry to every customer. RecoverAI separates that into three distinct, testable decisions: an ML model scores *whether* a payment is worth recovering, a policy engine decides *what action* fits the failure, and a merchant approves *before* anything reaches a customer. Revenue is only ever booked as recovered after a signature-verified webhook confirms it.

## Table of contents

- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Recovery pipeline](#recovery-pipeline)
- [Quick start](#quick-start)
- [Key concepts](#key-concepts)
- [Security](#security)
- [Observability & audit trail](#observability--audit-trail)
- [Tech stack](#tech-stack)
- [API reference](#api-reference)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## Architecture

RecoverAI keeps prediction, decision, and execution in separate layers so no single component can decide *and* act on its own.

```
┌──────────────────────────────────────────────────────────────┐
│                    Presentation Layer                        │
│   Next.js pages · FastAPI routes · request/response schemas  │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     Decision Layer                            │
│   ML model (recovery probability) · Action Selector (policy) │
│   · Policy Engine (merchant guardrails) · AI Agent (prose)    │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                   Execution & Verification Layer               │
│   Campaign lifecycle · Payment Provider (Razorpay) ·           │
│   Webhook verification · Audit log                             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     Persistence Layer                         │
│                     PostgreSQL (SQLModel)                     │
└──────────────────────────────────────────────────────────────┘
```

**Key principles**

- **Separation of prediction and decision** — the ML model only ever answers "how likely is this to recover"; a separate `RecoveryActionSelector` decides what to actually do about it. Neither can substitute for the other.
- **Policy before execution** — every recommended action passes through `PolicyEngine` (probability threshold, contact limits, allowed channels, campaign size caps) before it's shown as approvable, and again immediately before execution.
- **Execution ≠ revenue** — creating a payment link is a delivery event, not a financial one. Only a cryptographically verified Razorpay webhook may mark revenue as recovered.
- **Narration, not decision** — the AI agent (Gemini) explains numbers that were already computed; it has no database access and no path to alter a figure or trigger an action.
- **Fail closed** — an unrecognized failure category, a low-confidence prediction, or a policy violation always resolves to `MANUAL_REVIEW` / `NO_ACTION`, never to a default financial action.

## Project structure

```
recover-ai/
├── backend/
│   └── app/
│       ├── api/                 # FastAPI routes — request/response only, no business logic
│       │   ├── recovery.py          opportunities, analyze, metrics
│       │   ├── campaigns.py         create / approve / execute / reject
│       │   ├── ai.py                investigation agent
│       │   ├── webhooks.py          Razorpay webhook receiver
│       │   └── evaluation.py        ML + business metrics
│       ├── services/            # Business logic
│       │   ├── action_selector.py    recommends WHAT to do, given failure context
│       │   ├── policy_engine.py      merchant guardrail checks (single source of truth)
│       │   ├── campaign_service.py   create → approve → execute lifecycle
│       │   ├── webhook_service.py    signature verification + idempotent recovery
│       │   ├── payment_provider.py   Razorpay/mock provider abstraction
│       │   └── recovery_predictor.py ML prediction serving
│       ├── agents/               # AI investigation agent (isolated — no other service imports it)
│       ├── models/                # SQLModel tables + enums
│       └── schemas/               # Pydantic response models (kept separate from DB models)
├── frontend/
│   └── src/
│       ├── app/                   # Next.js routes: /, /opportunities, /evaluation, /demo
│       ├── components/            # DemoControlPanel, CampaignDetailView, etc.
│       └── lib/                   # API client, formatters
├── ml/
│   ├── training/                  # feature engineering + model comparison/selection
│   ├── evaluation/                 # metric functions shared by training and the eval report
│   └── models/                     # trained model artifact + metadata (loaded at serving time)
├── scripts/                        # synthetic data generator + DB seeder
└── docs/                           # architecture.md, data-model.md, ml-evaluation.md
```

## Recovery pipeline

```
Failed payment
      │
      ▼
ML model ─────────────────────► recovery_probability
      │
      ▼
RecoveryActionSelector ───────► recommended action
      │   (payment link / alternative method / manual review / defer / retry / …,
      │    based on failure category + customer history + spike detection + policy)
      ▼
PolicyEngine ─────────────────► pass / fail against merchant guardrails
      │
      ▼
Merchant approval ────────────► explicit, per campaign
      │
      ▼
Razorpay execution ───────────► payment link created (not yet "recovered")
      │
      ▼
Customer pays, or doesn't
      │
      ▼
Signed webhook from Razorpay ─► signature verified
      │
      ▼
Recovered revenue ────────────► the only place this number is ever written
```

## Quick start

### Prerequisites

- Docker + Docker Compose, **or** Python 3.11+/Node 20+/PostgreSQL 16 for a local setup
- (Optional) A free [Google AI Studio](https://aistudio.google.com) key for the LLM narrator — the app works without one

### Installation (Docker)

```bash
git clone <repo-url> && cd recover-ai
cp .env.example .env

docker compose up --build
docker compose exec backend python /app/scripts/seed_database.py   # synthetic dataset
docker compose exec backend python /app/ml/training/train.py       # train the recovery model
```

### Configuration

`.env` (see `.env.example` for the full, commented version):

```bash
# Database
DATABASE_URL=postgresql+psycopg://recoverai:recoverai_pw@localhost:5432/recoverai

# Razorpay — mock mode makes real network calls unnecessary
RAZORPAY_MODE=mock
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

# AI agent — optional, falls back to a deterministic narrator if unset
LLM_API_KEY=
LLM_MODEL=gemini-3.6-flash

# Frontend
API_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Running

| | Command |
| --- | --- |
| Docker | `docker compose up --build` |
| Backend only | `cd backend && uvicorn app.main:app --reload` |
| Frontend only | `cd frontend && npm run dev` |

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Backend + interactive docs | http://localhost:8000/docs |

### Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

## Key concepts

**Action selection is a dedicated policy layer, not a side effect of the ML score.**

```python
@dataclass
class ActionDecision:
    action: RecommendedAction
    eligible: bool
    reason: str
    confidence: float
    expected_recovery: float
    policy_checks: list[PolicyCheckResult]

    @property
    def executable(self) -> bool:
        # Only PAYMENT_LINK maps to something the current provider can
        # actually deliver — everything else is a recommendation.
        return self.eligible and self.action in EXECUTABLE_ACTIONS
```

**A provider abstraction keeps the campaign workflow independent of Razorpay.**

```python
class PaymentProvider(ABC):
    @abstractmethod
    def create_recovery_link(self, *, payment_id, amount, currency, ...) -> dict:
        """Mock or real Razorpay test-mode — the caller never knows which."""
```

**Every merchant guardrail lives in one place.**

```python
class PolicyEngine:
    def check_recovery_probability(self, probability, policy) -> PolicyCheckResult: ...
    def check_customer_contact_limit(self, customer_id, policy) -> PolicyCheckResult: ...
    def check_allowed_action(self, policy) -> PolicyCheckResult: ...
    def check_approval(self, campaign) -> PolicyCheckResult: ...
```

`campaign_service.py` never re-implements a threshold check — it always calls into `PolicyEngine`, and `RecoveryActionSelector` reuses the same engine rather than duplicating it.

## Security

- **No financial action without a verified webhook.** `RecoveryAction.status = RECOVERED` is set in exactly one place in the codebase — `webhook_service.py`, after HMAC signature verification.
- **The AI agent cannot execute, approve, or alter anything.** It has no database session and no tool-calling capability; it can only overwrite two `str` fields on an already-computed decision.
- **Unsafe defaults are not allowed to exist.** An unknown failure category, a low-confidence prediction, or a policy violation always resolves to `MANUAL_REVIEW` / `NO_ACTION` — never silently to a payment link.
- **Idempotent by construction.** Duplicate webhook delivery, duplicate approval, and duplicate execution are all rejected, not silently re-run.
- **Input validation** — every endpoint is typed (UUID path params, length/range-bounded Pydantic bodies); every query goes through SQLAlchemy's parameterized builder.

## Observability & audit trail

Every campaign carries a full, queryable timeline: what the AI predicted → what was recommended → what policy checks ran → who approved it → what the provider returned → what the webhook confirmed. Nothing is summarized away — the raw `audit_logs` and `webhook_events` rows are the source of truth, viewable per-campaign at `/campaigns/{id}`.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLModel, PostgreSQL |
| ML | scikit-learn, XGBoost, SHAP |
| AI agent | Google Gemini, with a deterministic rule-based fallback |
| Payments | Official `razorpay` Python SDK, Payment Links API (test mode) |
| Infra | Docker Compose |

## API reference

| Area | Endpoints |
| --- | --- |
| Payments | `GET /api/payments`, `GET /api/payments/failed` |
| ML predictions | `POST /api/recovery/analyze`, `GET /api/recovery/opportunities` |
| Campaigns | `POST /api/recovery/campaigns`, `POST .../approve`, `POST .../execute`, `POST .../reject` |
| AI agent | `POST /api/ai/investigate`, `GET /api/ai/investigations` |
| Webhooks | `POST /api/webhooks/razorpay` |
| Evaluation | `GET /api/evaluation/model`, `GET /api/evaluation/business`, `GET /api/evaluation/baseline-comparison` |
| Demo controls | `POST /api/demo/reset`, `POST /api/demo/simulate-provider-failure`, `POST /api/mock/simulate-payment` |

Full interactive docs (Swagger) at `/docs` once the backend is running.

## Testing

```bash
cd backend
pytest -v
```

~230 tests: synthetic data generation, ML feature engineering and leakage avoidance, the action-selector's policy matrix (every failure category + the regression test proving no category silently defaults to a payment link), campaign lifecycle, Razorpay integration against the real installed SDK, and webhook idempotency.

```bash
cd frontend
npm run lint
npx tsc --noEmit
```

## Roadmap

- Authentication & multi-tenancy
- Additional outreach channels (SMS/WhatsApp), beyond a payment link
- Background task queue for campaign execution

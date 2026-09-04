# RecoverAI

**AI Revenue Recovery Orchestrator** — built for the Razorpay Buildathon.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![Tests](https://img.shields.io/badge/tests-230%20passing-brightgreen)

When a payment fails, most businesses either ignore it or blast every customer with the same generic retry email. RecoverAI does it smarter — an ML model predicts which failed payments are worth chasing, an AI agent explains why, and a policy engine decides the right action, all before anything reaches a customer.

## Table of contents

- [Overview](#overview)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Recovery pipeline](#recovery-pipeline)
- [Setup](#setup)
- [Pages](#pages)
- [API reference](#api-reference)
- [Environment variables](#environment-variables)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## Overview

| Step | What happens |
| --- | --- |
| 1. Predict | ML model scores each failed payment's recovery probability |
| 2. Recommend | A separate policy layer picks the right action based on *why* it failed |
| 3. Explain | An LLM narrates the reasoning in plain language — it never decides anything |
| 4. Approve | Merchant reviews and approves the campaign — nothing is automatic |
| 5. Execute | RecoverAI creates a real Razorpay payment link |
| 6. Verify | Revenue counts as "recovered" only after a signed webhook confirms payment |

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLModel, PostgreSQL |
| ML | scikit-learn, XGBoost, SHAP |
| AI agent | Google Gemini (with a rule-based fallback narrator) |
| Payments | Razorpay Payment Links API (test mode) |

## Project structure

```
recover-ai/
├── backend/       FastAPI app
│   └── app/
│       ├── api/        routes
│       ├── services/   business logic (campaigns, policy, webhooks)
│       ├── agents/      the AI investigation agent
│       └── models/      database tables
├── frontend/      Next.js app
├── ml/            training/, evaluation/, models/
├── scripts/       synthetic data generator + DB seeder
└── docs/          architecture.md, data-model.md, ml-evaluation.md
```

## Recovery pipeline

```
Failed payment
      │
      ▼
ML model → recovery probability
      │
      ▼
Action selector → recommendation
      (payment link / alternative method / manual review / defer / retry)
      │
      ▼
Merchant approval
      │
      ▼
Razorpay execution → payment link created
      │
      ▼
Customer pays, or doesn't
      │
      ▼
Signed webhook from Razorpay
      │
      ▼
Recovered revenue (only counted here)
```

The ML model and the action-recommendation logic are kept separate on purpose: the model answers "how likely is this to recover", a different piece of code answers "what should we actually do about it".

## Setup

### Docker (easiest)

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend python /app/scripts/seed_database.py
docker compose exec backend python /app/ml/training/train.py
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Backend docs | http://localhost:8000/docs |

### Without Docker

```bash
cd backend && pip install -r requirements.txt && cd ..
python scripts/seed_database.py
python ml/training/train.py
cd backend && uvicorn app.main:app --reload
```

```bash
# in another terminal
cd frontend && npm install && npm run dev
```

## Pages

| Route | Purpose |
| --- | --- |
| `/` | Dashboard — payment health stats |
| `/opportunities` | Table of failed payments with recovery probability + recommended action |
| `/evaluation` | Real ML metrics (precision/recall/ROC-AUC) + business metrics |
| `/demo` | Step-by-step control panel: investigate → campaign → approve → execute → simulate → recovered |

## API reference

| Area | Endpoints |
| --- | --- |
| Payments | `GET /api/payments`, `GET /api/payments/failed` |
| ML predictions | `POST /api/recovery/analyze`, `GET /api/recovery/opportunities` |
| Campaigns | `POST /api/recovery/campaigns`, `POST .../approve`, `POST .../execute` |
| AI agent | `POST /api/ai/investigate` |
| Webhooks | `POST /api/webhooks/razorpay` |
| Evaluation | `GET /api/evaluation/model`, `GET /api/evaluation/business` |
| Demo | `POST /api/demo/reset`, `POST /api/demo/simulate-provider-failure` |

Full interactive docs at `/docs` once the backend is running.

## Environment variables

See `.env.example` for the full list.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `RAZORPAY_MODE` | `mock` (default) or `test` (real Razorpay test mode) |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Only needed for `test` mode |
| `LLM_API_KEY` | Google Gemini key (aistudio.google.com, free tier) — optional |

## Testing

```bash
cd backend
pytest -v
```

~230 backend tests: data generator, ML pipeline, campaign workflow, Razorpay integration, webhook verification, and the action-recommendation logic.

Frontend: `npm run lint` and `npx tsc --noEmit`.

## Known limitations

- No authentication — every API endpoint is open (fine for a demo, not for production).
- Live Razorpay payments are intentionally disabled — only test mode works.
- No background job queue — everything runs synchronously in the request.

## Roadmap

- Authentication
- More outreach channels (SMS/WhatsApp, not just a payment link)
- Background worker for campaign execution

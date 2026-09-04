from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai, campaigns, customers, dashboard, demo, evaluation, health, mock, payments, recovery, webhooks
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="RecoverAI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(dashboard.router)
app.include_router(payments.router)
app.include_router(customers.router)
app.include_router(recovery.router)
app.include_router(campaigns.router)
app.include_router(ai.router)
app.include_router(webhooks.router)
app.include_router(mock.router)
app.include_router(evaluation.router)
app.include_router(demo.router)

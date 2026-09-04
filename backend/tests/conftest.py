"""Shared pytest fixtures.

Tests run against a real PostgreSQL database (`recoverai_test`, created
alongside the main `recoverai` database on the same server) rather than
SQLite, so the test suite exercises the exact dialect used in dev/Docker.
A small, fixed-seed dataset is generated once per test session and inserted;
API tests then read against that known dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BACKEND_DIR.parent / "scripts"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, delete, insert, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.api.deps import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app import models as _app_models  # noqa: E402,F401  ensures every table is registered
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.merchant import Merchant  # noqa: E402
from app.models.merchant_policy import MerchantPolicy  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.payment import Payment  # noqa: E402
from app.models.payment_failure import PaymentFailure  # noqa: E402
from app.models.recovery_action import RecoveryAction  # noqa: E402
from app.models.recovery_campaign import RecoveryCampaign  # noqa: E402
from app.models.recovery_opportunity import RecoveryOpportunity  # noqa: E402

from generate_data import GeneratorConfig, generate_dataset  # noqa: E402

TEST_DB_NAME = "recoverai_test"
TEST_DATASET_CONFIG = GeneratorConfig(
    num_customers=200, min_orders=600, target_payments=2500, weeks=8, seed=99
)


def _ensure_test_database(base_url) -> None:
    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def test_engine():
    settings = get_settings()
    base_url = make_url(settings.database_url)
    _ensure_test_database(base_url)

    engine = create_engine(base_url.set(database=TEST_DB_NAME))
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def dataset():
    return generate_dataset(TEST_DATASET_CONFIG)


@pytest.fixture(scope="session", autouse=True)
def seeded_database(test_engine, dataset):
    with Session(test_engine) as session:
        session.exec(insert(Merchant).values(dataset.merchant))
        session.commit()
        for chunk_start in range(0, len(dataset.customers), 1000):
            chunk = dataset.customers[chunk_start : chunk_start + 1000]
            session.exec(insert(Customer).values(chunk))
        for chunk_start in range(0, len(dataset.orders), 1000):
            chunk = dataset.orders[chunk_start : chunk_start + 1000]
            session.exec(insert(Order).values(chunk))
        for chunk_start in range(0, len(dataset.payments), 1000):
            chunk = dataset.payments[chunk_start : chunk_start + 1000]
            session.exec(insert(Payment).values(chunk))
        for chunk_start in range(0, len(dataset.payment_failures), 1000):
            chunk = dataset.payment_failures[chunk_start : chunk_start + 1000]
            session.exec(insert(PaymentFailure).values(chunk))
        session.exec(insert(MerchantPolicy).values(dataset.merchant_policy))
        session.commit()
    yield


@pytest.fixture()
def db_session(test_engine):
    with Session(test_engine) as session:
        yield session


@pytest.fixture()
def clean_campaign_state(test_engine):
    """Phase 4 tests: reset the campaign-workflow tables before the test
    runs. These tables are mutated (campaigns/actions/opportunities carry
    a status lifecycle, and check_customer_contact_limit reads accumulated
    history), so without this, test order could leak state between tests
    -- e.g. a customer "contacted" by an earlier test would wrongly affect
    a later test's contact-limit check. Payments/customers/orders are
    read-only for these tests and stay shared."""
    with Session(test_engine) as session:
        session.exec(delete(RecoveryAction))
        session.exec(delete(RecoveryCampaign))
        session.exec(delete(RecoveryOpportunity))
        session.exec(delete(AuditLog))
        session.commit()
    yield


@pytest.fixture()
def client(test_engine):
    def _override_get_session():
        with Session(test_engine) as session:
            yield session

    # The mock LLM client is deterministic and network-free -- keeps the
    # suite fast/reliable regardless of API key or network availability.
    # Live-LLM behavior is verified separately (see test_agent_llm_client.py
    # for the retry/fallback logic itself, exercised without a real call).
    from app.agents.llm_client import MockLLMClient, get_llm_client

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

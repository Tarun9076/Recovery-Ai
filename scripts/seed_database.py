"""Seed the RecoverAI database with a freshly generated synthetic dataset.

Pipeline: generate dataset -> create schema -> insert merchant -> insert
customers -> insert orders -> insert payments -> insert payment_failures ->
insert merchant policy.

Idempotent: if the target merchant (matched by email) already has data, the
script wipes just that merchant's rows before re-inserting, rather than
appending duplicates on repeated runs.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import delete, insert  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.init_db import create_all  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.merchant import Merchant  # noqa: E402
from app.models.merchant_policy import MerchantPolicy  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.payment import Payment  # noqa: E402
from app.models.payment_failure import PaymentFailure  # noqa: E402

from generate_data import GeneratorConfig, generate_dataset  # noqa: E402

BATCH_SIZE = 1000  # keeps (rows * columns) comfortably under Postgres's 65535 bind-parameter limit


def _wipe_existing_merchant(session: Session, email: str) -> None:
    existing = session.exec(select(Merchant).where(Merchant.email == email)).first()
    if existing is None:
        return
    merchant_id = existing.id
    print(f"Existing merchant found ({email}); clearing previous data before reseed...")
    session.exec(
        delete(PaymentFailure).where(
            PaymentFailure.payment_id.in_(
                select(Payment.id).where(Payment.merchant_id == merchant_id)
            )
        )
    )
    session.exec(delete(Payment).where(Payment.merchant_id == merchant_id))
    session.exec(delete(Order).where(Order.merchant_id == merchant_id))
    session.exec(delete(Customer).where(Customer.merchant_id == merchant_id))
    session.exec(delete(MerchantPolicy).where(MerchantPolicy.merchant_id == merchant_id))
    session.exec(delete(Merchant).where(Merchant.id == merchant_id))
    session.commit()


def _bulk_insert(session: Session, table, rows: list[dict]) -> None:
    for i in range(0, len(rows), BATCH_SIZE):
        session.exec(insert(table).values(rows[i : i + BATCH_SIZE]))
    session.commit()


def seed(config: GeneratorConfig) -> None:
    print("Creating schema (if not present)...")
    create_all()

    print("Generating synthetic dataset...")
    t0 = time.time()
    dataset = generate_dataset(config)
    print(f"Generated in {time.time() - t0:.1f}s: "
          f"{len(dataset.customers)} customers, {len(dataset.orders)} orders, "
          f"{len(dataset.payments)} payments, {len(dataset.payment_failures)} failures")

    with Session(engine) as session:
        _wipe_existing_merchant(session, dataset.merchant["email"])

        print("Inserting merchant...")
        session.exec(insert(Merchant).values(dataset.merchant))
        session.commit()

        print(f"Inserting {len(dataset.customers)} customers...")
        _bulk_insert(session, Customer, dataset.customers)

        print(f"Inserting {len(dataset.orders)} orders...")
        _bulk_insert(session, Order, dataset.orders)

        print(f"Inserting {len(dataset.payments)} payments...")
        _bulk_insert(session, Payment, dataset.payments)

        print(f"Inserting {len(dataset.payment_failures)} payment failures...")
        _bulk_insert(session, PaymentFailure, dataset.payment_failures)

        print("Inserting merchant policy...")
        session.exec(insert(MerchantPolicy).values(dataset.merchant_policy))
        session.commit()

    print("Seeding complete.")
    print(f"Incident window: {dataset.incident_window[0]} -> {dataset.incident_window[1]}")
    print(f"Incident bank:   {dataset.incident_bank}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RecoverAI database with synthetic data")
    parser.add_argument("--customers", type=int, default=5500)
    parser.add_argument("--min-orders", type=int, default=22000)
    parser.add_argument("--payments", type=int, default=100000)
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = GeneratorConfig(
        num_customers=args.customers,
        min_orders=args.min_orders,
        target_payments=args.payments,
        weeks=args.weeks,
        seed=args.seed,
    )
    seed(config)


if __name__ == "__main__":
    main()

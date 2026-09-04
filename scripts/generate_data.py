"""Synthetic dataset generator for RecoverAI.

Produces a realistic (not uniformly random) merchant + customers + orders +
payments + payment_failures dataset with:

  * segment-driven customer behaviour (high-value loyal / normal / low-intent / new)
  * method-and-segment-driven payment failure rates (~90-96% overall success)
  * a deliberately injected "incident window" where UPI failures concentrated
    on one fictional bank spike from ~4-5% to ~10-12%
  * a noisy, multi-factor ground-truth `eventually_recovered` label per failed
    payment, meant for future ML training/evaluation only (never a feature)
  * internally consistent customer aggregates (order_count, lifetime_value, ...)
    computed from the actual generated transactions, not sampled independently

This module has no database/ORM dependency -- it returns plain dicts so it can
be reused by scripts/seed_database.py (for inserts) or run standalone to dump
CSV snapshots into ml/data/ for inspection.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

# ---------------------------------------------------------------------------
# Domain constants (all fictional -- no real bank/wallet names are used)
# ---------------------------------------------------------------------------

FICTIONAL_BANKS = [
    "Zenith Bank",
    "Meridian Bank",
    "Orbit Bank",
    "Anchor Bank",
    "Summit Bank",
    "Coastal Bank",
    "Horizon Bank",
    "Vertex Bank",
    "Nimbus Bank",
    "Falcon Bank",
]
INCIDENT_BANK = "Zenith Bank"

WALLET_PROVIDERS = ["PayEase", "QuickPay", "MoneyBird", "PocketPay"]
VPA_HANDLES = ["zenithbank", "meridianpay", "orbitupi", "summitpay", "apexupi", "nimbuspay"]

CITIES = [
    ("Mumbai", 14), ("Delhi", 13), ("Bengaluru", 12), ("Hyderabad", 9),
    ("Chennai", 8), ("Pune", 8), ("Kolkata", 7), ("Ahmedabad", 6),
    ("Jaipur", 5), ("Lucknow", 4), ("Surat", 4), ("Kochi", 4),
    ("Chandigarh", 3), ("Indore", 3),
]

METHOD_DISTRIBUTION = {"upi": 0.55, "card": 0.25, "netbanking": 0.12, "wallet": 0.08}

# Baseline (non-incident) per-attempt failure rate by method.
METHOD_BASE_FAIL_RATE = {"upi": 0.045, "card": 0.065, "netbanking": 0.055, "wallet": 0.07}

SEGMENT_WEIGHTS = {
    "HIGH_VALUE_LOYAL": 0.08,
    "NORMAL": 0.55,
    "LOW_INTENT": 0.27,
    "NEW": 0.10,
}
SEGMENT_FAIL_MULTIPLIER = {
    "HIGH_VALUE_LOYAL": 0.45,
    "NORMAL": 1.0,
    "LOW_INTENT": 2.1,
    "NEW": 1.25,
}
SEGMENT_MAX_ATTEMPTS = {"HIGH_VALUE_LOYAL": 2, "NORMAL": 3, "LOW_INTENT": 4, "NEW": 3}
SEGMENT_RETRY_PROB = {"HIGH_VALUE_LOYAL": 0.85, "NORMAL": 0.65, "LOW_INTENT": 0.35, "NEW": 0.55}
SEGMENT_ORDER_RANGE = {
    "HIGH_VALUE_LOYAL": (8, 26),
    "NORMAL": (2, 9),
    "LOW_INTENT": (1, 4),
    "NEW": (0, 2),
}
SEGMENT_AMOUNT_RANGE = {
    "HIGH_VALUE_LOYAL": (2500, 16000),
    "NORMAL": (400, 5500),
    "LOW_INTENT": (200, 2200),
    "NEW": (300, 3500),
}

TRANSIENT_CATEGORIES = {"NETWORK_ERROR", "TIMEOUT", "TECHNICAL_ERROR"}
SEMI_TRANSIENT_CATEGORIES = {"UPI_FAILURE", "AUTHENTICATION_FAILURE"}

METHOD_CATEGORY_WEIGHTS = {
    "upi": {
        "UPI_FAILURE": 0.50, "NETWORK_ERROR": 0.20, "TIMEOUT": 0.10,
        "TECHNICAL_ERROR": 0.06, "BANK_DECLINED": 0.09, "AUTHENTICATION_FAILURE": 0.05,
    },
    "card": {
        "CARD_DECLINED": 0.35, "INSUFFICIENT_FUNDS": 0.20, "CARD_LIMIT": 0.15,
        "AUTHENTICATION_FAILURE": 0.15, "BANK_DECLINED": 0.10, "TECHNICAL_ERROR": 0.05,
    },
    "netbanking": {
        "BANK_DECLINED": 0.38, "TIMEOUT": 0.20, "NETWORK_ERROR": 0.15,
        "TECHNICAL_ERROR": 0.10, "INSUFFICIENT_FUNDS": 0.12, "INVALID_DETAILS": 0.05,
    },
    "wallet": {
        "INSUFFICIENT_FUNDS": 0.30, "TECHNICAL_ERROR": 0.25, "NETWORK_ERROR": 0.20,
        "INVALID_DETAILS": 0.15, "TIMEOUT": 0.10,
    },
}
# Category mix forced during the incident window for UPI attempts on the incident bank.
INCIDENT_CATEGORY_WEIGHTS = {"UPI_FAILURE": 0.70, "BANK_DECLINED": 0.20, "TIMEOUT": 0.10}

CATEGORY_RAW = {
    "INSUFFICIENT_FUNDS": [
        ("BAD_REQUEST_ERROR", "Insufficient balance in the account"),
        ("BAD_REQUEST_ERROR", "Insufficient funds to complete the transaction"),
    ],
    "BANK_DECLINED": [
        ("GATEWAY_ERROR", "Payment declined by the bank"),
        ("BAD_REQUEST_ERROR", "Transaction declined by issuing bank"),
    ],
    "NETWORK_ERROR": [
        ("GATEWAY_ERROR", "Network error, please try again"),
        ("SERVER_ERROR", "Gateway connection error"),
    ],
    "TIMEOUT": [
        ("GATEWAY_ERROR", "Payment timed out"),
        ("SERVER_ERROR", "Bank server did not respond in time"),
    ],
    "UPI_FAILURE": [
        ("BAD_REQUEST_ERROR", "UPI payment failed"),
        ("GATEWAY_ERROR", "UPI collect request declined"),
        ("BAD_REQUEST_ERROR", "Incorrect UPI PIN entered"),
    ],
    "CARD_DECLINED": [
        ("BAD_REQUEST_ERROR", "Card declined"),
        ("GATEWAY_ERROR", "Issuing bank declined the transaction"),
    ],
    "CARD_LIMIT": [
        ("BAD_REQUEST_ERROR", "Transaction limit exceeded"),
        ("BAD_REQUEST_ERROR", "Daily card limit exceeded"),
    ],
    "AUTHENTICATION_FAILURE": [
        ("GATEWAY_ERROR", "OTP verification failed"),
        ("BAD_REQUEST_ERROR", "3D secure authentication failed"),
    ],
    "INVALID_DETAILS": [
        ("BAD_REQUEST_ERROR", "Invalid card details"),
        ("BAD_REQUEST_ERROR", "Invalid VPA"),
    ],
    "TECHNICAL_ERROR": [
        ("SERVER_ERROR", "Internal server error"),
        ("GATEWAY_ERROR", "Something went wrong, please try again"),
    ],
    "UNKNOWN": [("GATEWAY_ERROR", "Payment could not be processed")],
}

SOURCE_MAP = {
    "INSUFFICIENT_FUNDS": "BANK", "BANK_DECLINED": "BANK", "CARD_DECLINED": "BANK", "CARD_LIMIT": "BANK",
    "NETWORK_ERROR": "NETWORK", "TIMEOUT": "NETWORK",
    "UPI_FAILURE": "GATEWAY", "TECHNICAL_ERROR": "GATEWAY",
    "AUTHENTICATION_FAILURE": "CUSTOMER", "INVALID_DETAILS": "CUSTOMER",
    "UNKNOWN": "UNKNOWN",
}
STEP_MAP = {
    "INSUFFICIENT_FUNDS": "AUTHORIZATION", "BANK_DECLINED": "AUTHORIZATION",
    "CARD_DECLINED": "AUTHORIZATION", "CARD_LIMIT": "AUTHORIZATION",
    "NETWORK_ERROR": "PRE_PROCESSING", "TIMEOUT": "CAPTURE",
    "UPI_FAILURE": "AUTHORIZATION", "TECHNICAL_ERROR": "CAPTURE",
    "AUTHENTICATION_FAILURE": "OTP_VERIFICATION", "INVALID_DETAILS": "PRE_PROCESSING",
    "UNKNOWN": "CAPTURE",
}
SEVERITY_WEIGHTS = {
    "INSUFFICIENT_FUNDS": {"LOW": 0.1, "MEDIUM": 0.4, "HIGH": 0.5},
    "BANK_DECLINED": {"LOW": 0.1, "MEDIUM": 0.5, "HIGH": 0.4},
    "NETWORK_ERROR": {"LOW": 0.5, "MEDIUM": 0.4, "HIGH": 0.1},
    "TIMEOUT": {"LOW": 0.45, "MEDIUM": 0.45, "HIGH": 0.1},
    "UPI_FAILURE": {"LOW": 0.2, "MEDIUM": 0.55, "HIGH": 0.25},
    "CARD_DECLINED": {"LOW": 0.15, "MEDIUM": 0.45, "HIGH": 0.4},
    "CARD_LIMIT": {"LOW": 0.2, "MEDIUM": 0.6, "HIGH": 0.2},
    "AUTHENTICATION_FAILURE": {"LOW": 0.15, "MEDIUM": 0.45, "HIGH": 0.4},
    "INVALID_DETAILS": {"LOW": 0.7, "MEDIUM": 0.25, "HIGH": 0.05},
    "TECHNICAL_ERROR": {"LOW": 0.35, "MEDIUM": 0.45, "HIGH": 0.2},
    "UNKNOWN": {"LOW": 0.1, "MEDIUM": 0.3, "HIGH": 0.6},
}

HOUR_WEIGHTS = [
    1, 1, 1, 1, 1, 2, 3, 5, 6, 7, 8, 8,
    9, 9, 8, 8, 9, 10, 12, 14, 15, 13, 10, 5,
]

SUCCESS_STATUS_WEIGHTS = {"captured": 0.82, "success": 0.11, "authorized": 0.05, "refunded": 0.02}
DEVICE_PLATFORM_CHOICES = [
    (("mobile", "android"), 0.45),
    (("mobile", "ios"), 0.20),
    (("desktop", "web"), 0.28),
    (("tablet", "web"), 0.05),
    (("tablet", "ios"), 0.02),
]


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class GeneratorConfig:
    num_customers: int = 5500
    min_orders: int = 22000
    target_payments: int = 100000
    weeks: int = 8
    seed: int = 42
    timeline_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GeneratedDataset:
    merchant: dict
    customers: list[dict]
    orders: list[dict]
    payments: list[dict]
    payment_failures: list[dict]
    merchant_policy: dict
    incident_window: tuple[datetime, datetime]
    incident_bank: str
    busy_window: tuple[datetime, datetime]


def _build_day_weights(rng: random.Random, timeline_start: datetime, days: int,
                        busy_days: set[int]) -> list[float]:
    weights = []
    for d in range(days):
        day = timeline_start + timedelta(days=d)
        w = 1.0
        if day.weekday() >= 5:  # Sat/Sun
            w *= 1.15
        if d in busy_days:
            w *= 1.8
        weights.append(w)
    return weights


def _sample_timestamp(rng: random.Random, timeline_start: datetime, day_weights: list[float],
                       day_index: int | None = None) -> datetime:
    if day_index is None:
        day_index = rng.choices(range(len(day_weights)), weights=day_weights, k=1)[0]
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
    minute = rng.randrange(60)
    second = rng.randrange(60)
    day = timeline_start + timedelta(days=day_index)
    return day.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _new_customer_profile(rng: random.Random, faker: Faker, merchant_id: uuid.UUID,
                           timeline_start: datetime, timeline_end: datetime) -> dict:
    segment = _weighted_choice(rng, SEGMENT_WEIGHTS)
    home_bank = rng.choice(FICTIONAL_BANKS)

    if segment == "NEW":
        since = timeline_start + timedelta(
            seconds=rng.uniform(0, (timeline_end - timeline_start).total_seconds() * 0.6)
        )
    else:
        since = timeline_start - timedelta(days=rng.randint(30, 900))

    base_success = {
        "HIGH_VALUE_LOYAL": rng.gauss(0.97, 0.01),
        "NORMAL": rng.gauss(0.92, 0.03),
        "LOW_INTENT": rng.gauss(0.78, 0.06),
        "NEW": rng.gauss(0.88, 0.05),
    }[segment]
    base_success = min(0.995, max(0.5, base_success))

    low, high = SEGMENT_AMOUNT_RANGE[segment]
    order_low, order_high = SEGMENT_ORDER_RANGE[segment]

    name = faker.name()
    return {
        "id": uuid.uuid4(),
        "merchant_id": merchant_id,
        "name": name,
        "email": faker.unique.email(),
        "phone": f"+91{rng.randint(7000000000, 9999999999)}",
        "customer_since": since,
        "segment": segment,
        "home_bank": home_bank,
        "base_success_prob": base_success,
        "target_orders": rng.randint(order_low, order_high),
        "amount_low": low,
        "amount_high": high,
        "created_at": since,
    }


def _pick_method_and_bank(rng: random.Random, profile: dict) -> tuple[str, str | None, str | None, str | None]:
    method = _weighted_choice(rng, METHOD_DISTRIBUTION)
    bank = wallet = vpa = None
    if method in ("card", "netbanking"):
        bank = profile["home_bank"]
    elif method == "upi":
        bank = profile["home_bank"]
        handle = rng.choice(VPA_HANDLES)
        local = profile["email"].split("@")[0].replace(".", "")
        vpa = f"{local}@{handle}"
    elif method == "wallet":
        wallet = rng.choice(WALLET_PROVIDERS)
    return method, bank, wallet, vpa


def _failure_probability(rng: random.Random, profile: dict, method: str, ts: datetime,
                          incident_window: tuple[datetime, datetime], incident_bank: str) -> tuple[float, dict]:
    base_rate = METHOD_BASE_FAIL_RATE[method]
    multiplier = SEGMENT_FAIL_MULTIPLIER[profile["segment"]]
    rate = base_rate * multiplier
    category_weights = METHOD_CATEGORY_WEIGHTS[method]

    in_incident = incident_window[0] <= ts <= incident_window[1]
    if method == "upi" and in_incident:
        if profile["home_bank"] == incident_bank:
            rate = 0.60
            category_weights = INCIDENT_CATEGORY_WEIGHTS
        else:
            rate = max(rate, 0.05)

    return min(0.9, max(0.01, rate)), category_weights


def _retry_probability(segment: str, category: str, attempt_number: int) -> float:
    base = SEGMENT_RETRY_PROB[segment]
    if category == "INSUFFICIENT_FUNDS":
        base -= 0.15
    elif category in TRANSIENT_CATEGORIES:
        base += 0.10
    base -= 0.15 * (attempt_number - 1)
    return min(0.95, max(0.05, base))


def _recovery_probability(rng: random.Random, state: dict, category: str, attempt_number: int, segment: str) -> float:
    total = state["successful"] + state["failed"]
    hist_success_rate = (state["successful"] / total) if total else 0.7

    transient = 1.0 if category in TRANSIENT_CATEGORIES else (0.35 if category in SEMI_TRANSIENT_CATEGORIES else 0.0)
    insufficient = 1.0 if category == "INSUFFICIENT_FUNDS" else 0.0
    low_intent = 1.0 if segment == "LOW_INTENT" else 0.0
    ltv_component = min(state["lifetime_value"] / 20000.0, 1.0)

    score = (
        -0.3
        + 2.0 * (hist_success_rate - 0.5)
        + 0.8 * transient
        - 1.2 * insufficient
        - 0.5 * low_intent
        - 0.35 * (attempt_number - 1)
        + 0.6 * ltv_component
        + rng.gauss(0, 0.6)
    )
    return _sigmoid(score)


def _recoverability_label(rng: random.Random, category: str, attempt_number: int) -> str:
    transient = 1.0 if category in TRANSIENT_CATEGORIES else (0.35 if category in SEMI_TRANSIENT_CATEGORIES else 0.0)
    insufficient = 1.0 if category == "INSUFFICIENT_FUNDS" else 0.0
    score = 0.5 + 0.5 * transient - 0.6 * insufficient - 0.2 * (attempt_number - 1) + rng.gauss(0, 0.25)
    if score < 0.4:
        return "LOW"
    if score < 0.65:
        return "MEDIUM"
    return "HIGH"


def _device_platform(rng: random.Random) -> tuple[str, str]:
    choices = [c[0] for c in DEVICE_PLATFORM_CHOICES]
    weights = [c[1] for c in DEVICE_PLATFORM_CHOICES]
    idx = rng.choices(range(len(choices)), weights=weights, k=1)[0]
    return choices[idx]


def _generate_order_chain(
    rng: random.Random,
    merchant_id: uuid.UUID,
    profile: dict,
    state: dict,
    day_weights: list[float],
    timeline_start: datetime,
    incident_window: tuple[datetime, datetime],
    incident_bank: str,
) -> tuple[dict, list[dict], list[dict]]:
    order_id = uuid.uuid4()
    amount = round(rng.uniform(profile["amount_low"], profile["amount_high"]), 2)
    order_created_at = _sample_timestamp(rng, timeline_start, day_weights)

    payments: list[dict] = []
    failures: list[dict] = []

    method, bank, wallet, vpa = _pick_method_and_bank(rng, profile)
    current_ts = order_created_at
    attempt = 1
    max_attempts = SEGMENT_MAX_ATTEMPTS[profile["segment"]]
    order_status = "created"

    while True:
        if attempt > 1 and rng.random() < 0.25:
            method, bank, wallet, vpa = _pick_method_and_bank(rng, profile)

        fail_prob, category_weights = _failure_probability(
            rng, profile, method, current_ts, incident_window, incident_bank
        )
        device_type, platform = _device_platform(rng)
        city = rng.choices([c[0] for c in CITIES], weights=[c[1] for c in CITIES], k=1)[0]

        payment_id = uuid.uuid4()
        base_payment = {
            "id": payment_id,
            "merchant_id": merchant_id,
            "order_id": order_id,
            "customer_id": profile["id"],
            "razorpay_payment_id": f"pay_{uuid.uuid4().hex[:14]}",
            "amount": amount,
            "currency": "INR",
            "method": method,
            "bank": bank,
            "wallet": wallet,
            "vpa": vpa,
            "email": profile["email"],
            "contact": profile["phone"],
            "device_type": device_type,
            "platform": platform,
            "location": city,
            "attempt_number": attempt,
            "created_at": current_ts,
            "updated_at": current_ts,
        }

        if rng.random() >= fail_prob:
            status = _weighted_choice(rng, SUCCESS_STATUS_WEIGHTS)
            base_payment.update(status=status, failure_code=None, failure_reason=None,
                                 failure_source=None, failure_step=None)
            payments.append(base_payment)
            state["successful"] += 1
            state["lifetime_value"] += amount
            order_status = "paid"
            break

        category = _weighted_choice(rng, category_weights)
        raw_code, raw_reason = rng.choice(CATEGORY_RAW[category])
        source = SOURCE_MAP[category]
        step = STEP_MAP[category]

        base_payment.update(
            status="failed",
            failure_code=raw_code,
            failure_reason=raw_reason,
            failure_source=source,
            failure_step=step,
        )
        payments.append(base_payment)
        state["failed"] += 1

        severity = _weighted_choice(rng, SEVERITY_WEIGHTS[category])
        recoverability = _recoverability_label(rng, category, attempt)
        recovery_prob = _recovery_probability(rng, state, category, attempt, profile["segment"])
        eventually_recovered = rng.random() < recovery_prob

        failures.append({
            "id": uuid.uuid4(),
            "payment_id": payment_id,
            "failure_category": category,
            "failure_severity": severity,
            "recoverability": recoverability,
            "raw_failure_code": raw_code,
            "raw_failure_reason": raw_reason,
            "eventually_recovered": eventually_recovered,
            "created_at": current_ts,
        })

        retry_prob = _retry_probability(profile["segment"], category, attempt)
        if attempt >= max_attempts or rng.random() > retry_prob:
            order_status = "failed" if rng.random() < 0.85 else "cancelled"
            break

        attempt += 1
        current_ts = current_ts + timedelta(minutes=rng.randint(2, 240))

    order = {
        "id": order_id,
        "merchant_id": merchant_id,
        "customer_id": profile["id"],
        "amount": amount,
        "currency": "INR",
        "status": order_status,
        "created_at": order_created_at,
    }
    state["order_count"] += 1
    return order, payments, failures


def generate_dataset(config: GeneratorConfig | None = None) -> GeneratedDataset:
    config = config or GeneratorConfig()
    rng = random.Random(config.seed)
    faker = Faker()
    Faker.seed(config.seed)
    faker.unique.clear()

    timeline_end = config.timeline_end
    timeline_days = config.weeks * 7
    timeline_start = timeline_end - timedelta(days=timeline_days)

    busy_days = {10, 11, 12}
    day_weights = _build_day_weights(rng, timeline_start, timeline_days, busy_days)

    incident_start_day = min(timeline_days - 5, 35)
    incident_window = (
        timeline_start + timedelta(days=incident_start_day),
        timeline_start + timedelta(days=incident_start_day + 3, hours=23, minutes=59),
    )
    busy_window = (
        timeline_start + timedelta(days=10),
        timeline_start + timedelta(days=12, hours=23, minutes=59),
    )

    merchant_id = uuid.uuid4()
    merchant = {
        "id": merchant_id,
        "name": "Anaya Patel",
        "email": "founder@bloomtrail.example",
        "business_name": "Bloomtrail Retail",
        "currency": "INR",
        "created_at": timeline_start - timedelta(days=400),
    }

    profiles = [
        _new_customer_profile(rng, faker, merchant_id, timeline_start, timeline_end)
        for _ in range(config.num_customers)
    ]
    states = {p["id"]: {"successful": 0, "failed": 0, "lifetime_value": 0.0, "order_count": 0} for p in profiles}

    orders: list[dict] = []
    payments: list[dict] = []
    payment_failures: list[dict] = []

    def run_chain(profile: dict) -> None:
        order, pmts, fails = _generate_order_chain(
            rng, merchant_id, profile, states[profile["id"]], day_weights,
            timeline_start, incident_window, INCIDENT_BANK,
        )
        orders.append(order)
        payments.extend(pmts)
        payment_failures.extend(fails)

    for profile in profiles:
        for _ in range(profile["target_orders"]):
            run_chain(profile)

    topup_weights = [1.0 if p["target_orders"] > 0 else 0.3 for p in profiles]
    max_topup_iterations = config.target_payments * 5  # generous guard against runaway loops
    topup_iterations = 0
    while (len(orders) < config.min_orders or len(payments) < config.target_payments) \
            and topup_iterations < max_topup_iterations:
        profile = rng.choices(profiles, weights=topup_weights, k=1)[0]
        run_chain(profile)
        topup_iterations += 1

    customers = []
    for profile in profiles:
        st = states[profile["id"]]
        customers.append({
            "id": profile["id"],
            "merchant_id": merchant_id,
            "name": profile["name"],
            "email": profile["email"],
            "phone": profile["phone"],
            "customer_since": profile["customer_since"],
            "lifetime_value": round(st["lifetime_value"], 2),
            "order_count": st["order_count"],
            "successful_payment_count": st["successful"],
            "failed_payment_count": st["failed"],
            "created_at": profile["created_at"],
        })

    merchant_policy = {
        "id": uuid.uuid4(),
        "merchant_id": merchant_id,
        "minimum_recovery_probability": 0.65,
        "max_customer_contacts": 1,
        "max_campaign_amount": None,
        "approval_required": True,
        "allowed_actions": ["email", "sms", "whatsapp"],
        "created_at": timeline_start - timedelta(days=400),
        "updated_at": timeline_start - timedelta(days=400),
    }

    return GeneratedDataset(
        merchant=merchant,
        customers=customers,
        orders=orders,
        payments=payments,
        payment_failures=payment_failures,
        merchant_policy=merchant_policy,
        incident_window=incident_window,
        incident_bank=INCIDENT_BANK,
        busy_window=busy_window,
    )


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RecoverAI synthetic dataset")
    parser.add_argument("--customers", type=int, default=5500)
    parser.add_argument("--min-orders", type=int, default=22000)
    parser.add_argument("--payments", type=int, default=100000)
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default=None, help="If set, dump CSV snapshots here")
    args = parser.parse_args()

    config = GeneratorConfig(
        num_customers=args.customers,
        min_orders=args.min_orders,
        target_payments=args.payments,
        weeks=args.weeks,
        seed=args.seed,
    )
    dataset = generate_dataset(config)

    total = len(dataset.payments)
    failed = sum(1 for p in dataset.payments if p["status"] == "failed")
    print(f"Merchant:          {dataset.merchant['business_name']}")
    print(f"Customers:         {len(dataset.customers)}")
    print(f"Orders:            {len(dataset.orders)}")
    print(f"Payments:          {total}")
    print(f"Failed payments:   {failed} ({failed/total:.2%})")
    print(f"Successful:        {total-failed} ({(total-failed)/total:.2%})")
    print(f"Incident window:   {dataset.incident_window[0]} -> {dataset.incident_window[1]}")
    print(f"Incident bank:     {dataset.incident_bank}")

    if args.out_dir:
        out = Path(args.out_dir)
        _write_csv(out / "customers.csv", dataset.customers)
        _write_csv(out / "orders.csv", dataset.orders)
        _write_csv(out / "payments.csv", dataset.payments)
        _write_csv(out / "payment_failures.csv", dataset.payment_failures)
        print(f"CSV snapshots written to {out}")


if __name__ == "__main__":
    main()

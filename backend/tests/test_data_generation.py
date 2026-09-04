"""Validates the synthetic generator's statistical properties directly
(no DB/API involved) -- distribution ranges, internal consistency of
customer aggregates, and the injected incident's detectability."""

from collections import defaultdict

from generate_data import GeneratorConfig, generate_dataset

SMALL_CONFIG = GeneratorConfig(num_customers=800, min_orders=3000, target_payments=12000, weeks=8, seed=123)


def test_row_counts_meet_minimums():
    ds = generate_dataset(SMALL_CONFIG)
    assert len(ds.customers) == SMALL_CONFIG.num_customers
    assert len(ds.orders) >= SMALL_CONFIG.min_orders
    assert len(ds.payments) >= SMALL_CONFIG.target_payments


def test_overall_success_rate_in_realistic_range():
    ds = generate_dataset(SMALL_CONFIG)
    total = len(ds.payments)
    failed = sum(1 for p in ds.payments if p["status"] == "failed")
    failure_rate = failed / total
    assert 0.03 <= failure_rate <= 0.12  # generous band around the 4-10% target


def test_payment_methods_not_uniform():
    ds = generate_dataset(SMALL_CONFIG)
    counts = defaultdict(int)
    for p in ds.payments:
        counts[p["method"]] += 1
    assert counts["upi"] > counts["netbanking"]
    assert counts["upi"] > counts["wallet"]
    assert len(counts) == 4


def test_failure_categories_not_uniform():
    ds = generate_dataset(SMALL_CONFIG)
    counts = defaultdict(int)
    for f in ds.payment_failures:
        counts[f["failure_category"]] += 1
    assert len(counts) > 1
    most_common = max(counts.values())
    least_common = min(counts.values())
    assert most_common > least_common  # distribution is skewed, not flat


def test_customer_aggregates_match_transactions():
    ds = generate_dataset(SMALL_CONFIG)

    orders_by_customer = defaultdict(int)
    for o in ds.orders:
        orders_by_customer[o["customer_id"]] += 1

    success_by_customer = defaultdict(int)
    failed_by_customer = defaultdict(int)
    ltv_by_customer = defaultdict(float)
    for p in ds.payments:
        if p["status"] == "failed":
            failed_by_customer[p["customer_id"]] += 1
        else:
            success_by_customer[p["customer_id"]] += 1
            ltv_by_customer[p["customer_id"]] += p["amount"]

    checked = 0
    for c in ds.customers:
        cid = c["id"]
        assert c["order_count"] == orders_by_customer.get(cid, 0)
        assert c["successful_payment_count"] == success_by_customer.get(cid, 0)
        assert c["failed_payment_count"] == failed_by_customer.get(cid, 0)
        assert abs(c["lifetime_value"] - ltv_by_customer.get(cid, 0.0)) < 0.01
        checked += 1
    assert checked == len(ds.customers)


def test_incident_window_shows_upi_failure_spike_concentrated_on_one_bank():
    ds = generate_dataset(SMALL_CONFIG)
    start, end = ds.incident_window

    def in_window(p):
        return start <= p["created_at"] <= end

    upi_in = [p for p in ds.payments if p["method"] == "upi" and in_window(p)]
    upi_out = [p for p in ds.payments if p["method"] == "upi" and not in_window(p)]

    def fail_rate(rows):
        return sum(1 for r in rows if r["status"] == "failed") / len(rows) if rows else 0

    rate_in = fail_rate(upi_in)
    rate_out = fail_rate(upi_out)
    assert rate_in > rate_out * 1.5  # clearly, statistically detectable spike

    failed_in_window = [p for p in upi_in if p["status"] == "failed"]
    bank_counts = defaultdict(int)
    for p in failed_in_window:
        bank_counts[p["bank"]] += 1
    incident_bank_share = bank_counts[ds.incident_bank] / len(failed_in_window)
    assert incident_bank_share > 0.3  # disproportionate concentration on one bank


def test_eventually_recovered_is_not_a_trivial_rule_on_category():
    """Ground truth must have noise -- NETWORK_ERROR must not be always/never recoverable."""
    ds = generate_dataset(SMALL_CONFIG)
    by_category = defaultdict(list)
    for f in ds.payment_failures:
        by_category[f["failure_category"]].append(f["eventually_recovered"])

    for category, outcomes in by_category.items():
        if len(outcomes) < 15:
            continue
        recovered_rate = sum(outcomes) / len(outcomes)
        assert 0.02 < recovered_rate < 0.98, (
            f"{category} eventually_recovered rate {recovered_rate} looks deterministic"
        )


def test_recoverability_label_and_ground_truth_are_not_identical():
    """The heuristic `recoverability` label and the richer `eventually_recovered`
    ground truth are computed independently and should disagree sometimes --
    otherwise there would be no meaningful ML task."""
    ds = generate_dataset(SMALL_CONFIG)
    high_label_outcomes = [
        f["eventually_recovered"] for f in ds.payment_failures if f["recoverability"] == "HIGH"
    ]
    assert len(high_label_outcomes) > 10
    disagreement_rate = 1 - (sum(high_label_outcomes) / len(high_label_outcomes))
    assert disagreement_rate > 0.02

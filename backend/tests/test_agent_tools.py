"""Tool-level tests: correctness of the 8 restricted tools, and that the
agent's tool surface can't reach the database in an unrestricted way."""

import ast
import inspect
import uuid
from pathlib import Path

import pytest

from app.agents import tools


def test_get_failed_payments_only_returns_failed_status(test_engine, db_session, dataset):
    rows = tools.get_failed_payments(db_session, limit=500)
    assert len(rows) > 0
    assert all(r["status"] == "failed" for r in rows)
    assert all(r["failure_category"] is not None for r in rows)


def test_get_failed_payments_category_filter(test_engine, db_session, dataset):
    all_rows = tools.get_failed_payments(db_session, limit=5000)
    categories_present = {r["failure_category"] for r in all_rows}
    target = next(iter(categories_present))

    filtered = tools.get_failed_payments(db_session, category=target, limit=5000)
    assert len(filtered) > 0
    assert all(r["failure_category"] == target for r in filtered)


def test_get_payment_details_returns_none_for_unknown_id(test_engine, db_session):
    assert tools.get_payment_details(db_session, uuid.uuid4()) is None


def test_get_payment_details_matches_get_failed_payments(test_engine, db_session, dataset):
    sample = tools.get_failed_payments(db_session, limit=1)[0]
    detail = tools.get_payment_details(db_session, uuid.UUID(sample["payment_id"]))
    assert detail is not None
    assert detail["payment_id"] == sample["payment_id"]
    assert detail["failure_category"] == sample["failure_category"]


def test_get_customer_history_matches_customer_record(test_engine, db_session, dataset):
    customer = dataset.customers[0]
    history = tools.get_customer_history(db_session, customer["id"])
    assert history is not None
    assert history["order_count"] == customer["order_count"]
    assert history["successful_payment_count"] == customer["successful_payment_count"]
    assert history["failed_payment_count"] == customer["failed_payment_count"]


def test_get_failure_statistics_totals_are_internally_consistent(test_engine, db_session, dataset):
    stats = tools.get_failure_statistics(db_session)
    assert stats["total_payments"] == len(dataset.payments)
    assert stats["failed_payments"] == len(dataset.payment_failures)
    assert stats["failure_rate"] == pytest.approx(stats["failed_payments"] / stats["total_payments"])
    assert sum(row["count"] for row in stats["method_breakdown"]) == stats["failed_payments"]


def test_analyze_failure_spike_windows_are_ordered(test_engine, db_session, dataset):
    result = tools.analyze_failure_spike(db_session, recent_days=28, baseline_days=28)
    assert result["recent_window"]["since"] < result["recent_window"]["until"]
    assert result["baseline_window"]["until"] <= result["recent_window"]["since"]
    assert isinstance(result["anomalies"], list)


def test_predict_recovery_tool_matches_service(test_engine, db_session, dataset):
    payment_id = dataset.payment_failures[0]["payment_id"]
    result = tools.predict_recovery(db_session, payment_id)
    assert 0.0 <= result["recovery_probability"] <= 1.0


def test_rank_recovery_opportunities_scoped_to_payment_ids(test_engine, db_session, dataset):
    subset = [f["payment_id"] for f in dataset.payment_failures[:5]]
    ranked = tools.rank_recovery_opportunities(db_session, payment_ids=subset, limit=10)
    assert len(ranked) == len(subset)
    assert {r["payment_id"] for r in ranked} == {str(p) for p in subset}
    expected = [r["expected_recovery"] for r in ranked]
    assert expected == sorted(expected, reverse=True)


def test_get_recovery_metrics_shape(test_engine, db_session, dataset):
    metrics = tools.get_recovery_metrics(db_session)
    assert "total_predictions" in metrics
    assert "segment_counts" in metrics


def test_get_merchant_policy_returns_seeded_policy(test_engine, db_session, dataset):
    policy = tools.get_merchant_policy(db_session)
    assert policy is not None
    assert policy.minimum_recovery_probability == dataset.merchant_policy["minimum_recovery_probability"]


# --- Restriction/permission checks -----------------------------------------

WRITE_KEYWORDS = {"session.add", "session.delete", "session.merge", "insert(", "update(", "delete(", "session.exec(text"}
PROTECTED_TABLES = {"Payment", "Order", "MerchantPolicy"}


def test_tools_module_never_writes_to_protected_models():
    """Static guard: tools.py must contain no write calls at all (it's a
    read-only surface), and in particular no ORM writes against Payment,
    Order, or MerchantPolicy -- the agent must never touch financial state."""
    source = Path(inspect.getfile(tools)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    write_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_source = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if any(kw.rstrip("(") in call_source for kw in ("session.add", "session.delete", "session.merge")):
                write_calls.append(call_source)

    assert write_calls == [], f"tools.py contains unexpected write calls: {write_calls}"


def test_tools_module_has_no_raw_sql_string_execution():
    """The agent's data access must go through SQLModel's query builder
    (parameterized, schema-checked) -- never a raw SQL string that could be
    used to bypass the restricted tool surface."""
    source = Path(inspect.getfile(tools)).read_text(encoding="utf-8")
    assert "session.exec(text(" not in source
    assert "execute(text(" not in source


def test_only_eight_named_tools_are_public():
    """The spec names exactly 8 tools; anything else callable in tools.py
    should be a private helper (leading underscore) or the documented
    policy-lookup exception, not a new data-access surface."""
    expected = {
        "get_failed_payments", "get_payment_details", "get_customer_history",
        "get_failure_statistics", "analyze_failure_spike", "predict_recovery",
        "rank_recovery_opportunities", "get_recovery_metrics",
    }
    public_functions = {
        name for name, obj in inspect.getmembers(tools, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == tools.__name__
    }
    # get_latest_payment_timestamp and get_merchant_policy are documented,
    # read-only exceptions (used internally for the "now" reference and the
    # policy gate) -- everything else must be exactly the 8 named tools.
    extra = public_functions - expected - {"get_latest_payment_timestamp", "get_merchant_policy"}
    assert extra == set(), f"tools.py exposes undocumented functions: {extra}"
    assert expected.issubset(public_functions)

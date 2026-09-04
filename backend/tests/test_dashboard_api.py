def test_dashboard_summary(client, dataset):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["total_payments"] == len(dataset.payments)
    assert body["total_customers"] == len(dataset.customers)
    assert body["total_orders"] == len(dataset.orders)

    failed = sum(1 for p in dataset.payments if p["status"] == "failed")
    assert body["failed_payments"] == failed
    assert body["successful_payments"] == len(dataset.payments) - failed

    expected_rate = round(failed / len(dataset.payments), 4)
    assert body["failure_rate"] == expected_rate

    assert len(body["failure_trend"]) > 0
    assert len(body["failure_category_breakdown"]) > 0

def test_list_customers(client, dataset):
    response = client.get("/api/customers", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(dataset.customers)
    assert len(body["items"]) == 10


def test_get_customer_by_id(client, dataset):
    target = dataset.customers[0]
    response = client.get(f"/api/customers/{target['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(target["id"])
    assert body["email"] == target["email"]


def test_get_customer_not_found(client):
    import uuid

    response = client.get(f"/api/customers/{uuid.uuid4()}")
    assert response.status_code == 404

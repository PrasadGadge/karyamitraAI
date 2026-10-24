from fastapi.testclient import TestClient

from app import app, service


client = TestClient(app)


def setup_function():
    service.orders.clear()


def test_health_catalogue_dataset_and_metrics_are_live_data():
    assert client.get("/api/health").json()["status"] == "ok"
    assert len(client.get("/api/catalogue").json()["records"]) == 6
    assert len(client.get("/api/dataset").json()["records"]) == 6
    assert client.get("/api/metrics").json()["orders_processed"] == 0


def test_process_and_approval_safeguards():
    invalid = client.post("/api/orders/process", json={"message": "Send 2 box small shampoo."}).json()
    assert invalid["state"] == "NEEDS_CLARIFICATION"
    assert client.post(f"/api/orders/{invalid['id']}/approve").status_code == 409
    valid = client.post("/api/orders/process", json={"message": "Send 1 bottle oil."}).json()
    assert client.post(f"/api/orders/{valid['id']}/approve").status_code == 200
    assert client.get(f"/api/orders/{valid['id']}/export").status_code == 200


def test_invalid_request_and_missing_order_have_honest_errors():
    assert client.post("/api/orders/process", json={"message": ""}).status_code == 422
    assert client.get("/api/orders/not-an-order").status_code == 404

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


def test_orders_list_endpoint_tracks_processed_orders():
    res = client.get("/api/orders").json()
    assert res["count"] == 0
    client.post("/api/orders/process", json={"message": "Send 1 bottle oil."})
    res_after = client.get("/api/orders").json()
    assert res_after["count"] == 1
    assert len(res_after["records"]) == 1


def test_llm_request_without_configuration_falls_back_to_rules(monkeypatch):
    from llm_extraction import OpenRouterExtractionAdapter

    monkeypatch.setattr(service, "llm_adapter", OpenRouterExtractionAdapter(api_key=None, model=None))
    result = client.post("/api/orders/process", json={"message": "Send 1 bottle oil.", "extraction_method": "llm"}).json()
    assert result["parser"]["requested_method"] == "llm"
    assert result["parser"]["method"] == "rules"
    assert "unavailable" in result["fallback_reason"].lower()
    assert result["lines"][0]["sku"] == "SYN-OIL-500"


def test_evaluation_records_endpoint_does_not_leak_locked_ground_truth():
    res = client.get("/api/evaluation/records")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 60
    assert data["split_counts"]["development"] == 36
    assert data["split_counts"]["validation"] == 12
    assert data["split_counts"]["locked_test"] == 12
    # Ensure locked ground truth is never exposed
    assert "expected_items" not in res.text.lower()
    assert "moon juice" not in res.text.lower()

import json
import socket

import pytest

from catalogue import Catalogue
from orders import OrderService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def completion(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def test_masks_sensitive_text_without_masking_order_details():
    from llm_extraction import mask_sensitive_text

    message = "Customer: Riya Shah, phone +91 98765 43210, email riya@example.com. Send 2 box 500ml oil."
    masked = mask_sensitive_text(message)
    assert "Riya Shah" not in masked
    assert "98765 43210" not in masked
    assert "riya@example.com" not in masked
    assert "2 box 500ml oil" in masked


def test_valid_provider_response_is_schema_validated_and_receives_masked_text(monkeypatch):
    import llm_extraction

    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse(completion({"lines": [{"product_text": "500ml oil", "quantity": 2, "unit": "box", "source_text": "2 box 500ml oil"}], "unrecognised_text": []}))

    monkeypatch.setattr(llm_extraction, "urlopen", fake_urlopen)
    adapter = llm_extraction.OpenRouterExtractionAdapter(api_key="test-key", model="provider/model", timeout_seconds=7)
    result = adapter.extract("Customer: Riya Shah; phone 9876543210. Send 2 box 500ml oil.")

    sent_text = captured["body"]["messages"][1]["content"]
    assert "Riya Shah" not in sent_text
    assert "9876543210" not in sent_text
    assert "2 box 500ml oil" in sent_text
    assert captured["authorization"] == "Bearer test-key"
    assert captured["timeout"] == 7
    assert result["method"] == "llm"
    assert result["lines"][0]["product_text"] == "500ml oil"


@pytest.mark.parametrize(
    "response",
    [
        completion({"lines": [{"product_text": "oil", "quantity": 1, "unit": "bottle"}]}),
        completion({"lines": [{"product_text": "oil", "quantity": 1, "unit": "bottle", "source_text": "oil", "sku": "INVENTED"}]}),
        {"choices": [{"message": {"content": "not json"}}]},
    ],
)
def test_malformed_or_unsafe_provider_output_is_rejected(monkeypatch, response):
    import llm_extraction

    monkeypatch.setattr(llm_extraction, "urlopen", lambda *_args, **_kwargs: FakeResponse(response))
    adapter = llm_extraction.OpenRouterExtractionAdapter(api_key="test-key", model="provider/model")
    with pytest.raises(llm_extraction.LLMResponseError):
        adapter.extract("Send 1 bottle oil")


def test_missing_configuration_does_not_enable_llm(monkeypatch):
    from llm_extraction import OpenRouterExtractionAdapter

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert not OpenRouterExtractionAdapter.from_environment().is_available


def test_timeout_is_reported_without_leaking_transport_details(monkeypatch):
    import llm_extraction

    monkeypatch.setattr(llm_extraction, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout()))
    adapter = llm_extraction.OpenRouterExtractionAdapter(api_key="test-key", model="provider/model")
    with pytest.raises(llm_extraction.LLMProviderError, match="timed out"):
        adapter.extract("Send 1 bottle oil")


def test_llm_proposal_uses_shared_catalogue_validation_and_rules_fallback(tmp_path):
    from llm_extraction import LLMProviderError

    catalogue_path = tmp_path / "products.csv"
    catalogue_path.write_text("sku,name,aliases,sellable_unit,supported_conversions,price\nOIL,Oil,oil,bottle,bottle:1,82.50\n", encoding="utf-8")

    class FailingAdapter:
        is_available = True

        def extract(self, _message):
            raise LLMProviderError("Provider request failed.")

    service = OrderService(Catalogue(catalogue_path), llm_adapter=FailingAdapter())
    fallback = service.process("Send 1 bottle oil.", extraction_method="llm")
    assert fallback["parser"]["method"] == "rules"
    assert fallback["parser"]["requested_method"] == "llm"
    assert fallback["fallback_reason"] == "Provider request failed."
    assert fallback["lines"][0]["sku"] == "OIL"


def test_llm_unknown_product_remains_unresolved_and_cannot_be_approved(tmp_path):
    catalogue_path = tmp_path / "products.csv"
    catalogue_path.write_text("sku,name,aliases,sellable_unit,supported_conversions,price\nOIL,Oil,oil,bottle,bottle:1,82.50\n", encoding="utf-8")

    class StubAdapter:
        is_available = True

        def extract(self, _message):
            return {"method": "llm", "version": "openrouter-v1", "lines": [{"product_text": "unknown tonic", "quantity": 1, "unit": "bottle", "source_text": "1 bottle unknown tonic"}], "unrecognised_text": []}

    service = OrderService(Catalogue(catalogue_path), llm_adapter=StubAdapter())
    order = service.process("Send 1 bottle unknown tonic.", extraction_method="llm")
    assert order["state"] == "NEEDS_CLARIFICATION"
    assert order["lines"][0]["sku"] is None
    with pytest.raises(ValueError):
        service.approve(order["id"])

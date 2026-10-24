from unittest.mock import MagicMock
import smoke_test_llm
from llm_extraction import LLMProviderError


def test_smoke_test_mock_run():
    exit_code = smoke_test_llm.run_mocked_test()
    assert exit_code == 0


def test_smoke_test_status_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    status, reason, _, _ = smoke_test_llm.check_status()
    assert status == "SKIPPED"
    assert "Neither" in reason


def test_smoke_test_status_when_partially_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    status, reason, _, _ = smoke_test_llm.check_status()
    assert status == "SKIPPED"
    assert "OPENROUTER_MODEL" in reason


def test_smoke_test_fails_on_provider_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "provider/model")

    def fake_extract(_msg):
        raise LLMProviderError("401 Unauthorized: Invalid API key")

    monkeypatch.setattr(smoke_test_llm.OpenRouterExtractionAdapter, "extract", lambda self, msg: fake_extract(msg))
    code = smoke_test_llm.run_smoke_test()
    assert code == 1


def test_smoke_test_succeeds_on_valid_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "valid-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "provider/model")

    monkeypatch.setattr(
        smoke_test_llm.OpenRouterExtractionAdapter,
        "extract",
        lambda self, msg: {"method": "llm", "lines": [{"product_text": "oil", "quantity": 1, "unit": "bottle"}]}
    )
    code = smoke_test_llm.run_smoke_test()
    assert code == 0

"""OpenRouter LLM Adapter Smoke Test Utility for KaryaMitra AI.

Distinguishes four distinct execution states:
  1. SKIPPED: Missing credentials in environment (OPENROUTER_API_KEY or OPENROUTER_MODEL unset).
  2. FAILED: Credentials present, but provider returned error, auth failure, timeout, or invalid output.
  3. SUCCESS: Live provider request succeeded and returned schema-valid output.
  4. MOCKED: Mocked test only (offline verification of adapter serialization, masking, and schema).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from unittest.mock import MagicMock

from llm_extraction import (
    LLMExtractionError,
    LLMUnavailableError,
    OpenRouterExtractionAdapter,
    mask_sensitive_text,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def run_mocked_test() -> int:
    """Offline test verifying adapter logic without external network calls."""
    print("=" * 60)
    print("[MOCKED TEST] Running offline OpenRouter extraction adapter verification...")
    print("=" * 60)

    # 1. Verify masking
    sample_raw = "Customer: Ramesh Gupta, phone +91 98765 43210, email ramesh@example.com. Send 2 box 500ml oil."
    masked = mask_sensitive_text(sample_raw)
    assert "Ramesh Gupta" not in masked, "Customer name should be masked"
    assert "98765 43210" not in masked, "Phone number should be masked"
    assert "ramesh@example.com" not in masked, "Email address should be masked"
    assert "2 box 500ml oil" in masked, "Order content must remain intact"
    print("  [PASS] Sensitive PII masking correctly protects customer privacy.")

    # 2. Verify adapter schema validation via mocked response
    fake_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "lines": [
                            {
                                "product_text": "500ml oil",
                                "quantity": 2,
                                "unit": "box",
                                "source_text": "2 box 500ml oil",
                            }
                        ],
                        "unrecognised_text": [],
                        "delivery_instructions": None,
                        "missing_fields": [],
                        "ambiguous_fields": [],
                    })
                }
            }
        ]
    }

    import llm_extraction

    original_urlopen = llm_extraction.urlopen
    try:
        llm_extraction.urlopen = MagicMock(return_value=FakeResponse(fake_body))
        adapter = OpenRouterExtractionAdapter(api_key="mock-key-for-test", model="mock-model", timeout_seconds=5)
        res = adapter.extract("Customer: Suresh; Send 2 box 500ml oil.")
        assert res["method"] == "llm"
        assert len(res["lines"]) == 1
        assert res["lines"][0]["product_text"] == "500ml oil"
        print("  [PASS] Adapter validates schema and parses proposal correctly.")
    finally:
        llm_extraction.urlopen = original_urlopen

    # 3. Verify unconfigured adapter raises LLMUnavailableError
    unconfigured = OpenRouterExtractionAdapter(api_key="", model="")
    assert not unconfigured.is_available
    try:
        unconfigured.extract("Send 1 bottle oil.")
        assert False, "Unconfigured adapter must raise LLMUnavailableError"
    except LLMUnavailableError:
        print("  [PASS] Unconfigured adapter safely raises LLMUnavailableError without network call.")

    print("\nResult: [MOCKED] Mocked test only passed successfully. (Offline verification clean)")
    return 0


def check_status() -> tuple[str, str, str | None, str | None]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    timeout = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "15").strip()

    has_key = bool(api_key)
    has_model = bool(model)

    if not has_key and not has_model:
        return "SKIPPED", "Neither OPENROUTER_API_KEY nor OPENROUTER_MODEL is configured.", None, None
    if not has_key:
        return "SKIPPED", "OPENROUTER_API_KEY is not configured.", None, model
    if not has_model:
        return "SKIPPED", "OPENROUTER_MODEL is not configured.", api_key[:4] + "..." if len(api_key) > 4 else "set", None

    return "CONFIGURED", f"Both credentials configured. Model: {model}", api_key[:6] + "..." if len(api_key) > 6 else "set", model


def run_smoke_test() -> int:
    status, reason, key_preview, model = check_status()

    print("=" * 60)
    print("KaryaMitra AI — OpenRouter LLM Smoke Test")
    print("=" * 60)
    print(f"Status check: {status}")
    print(f"Details: {reason}")
    if key_preview:
        print(f"Key preview: {key_preview}")
    if model:
        print(f"Model ID: {model}")
    print("-" * 60)

    if status == "SKIPPED":
        print("\nResult: [SKIPPED] Skipped because credentials are missing.")
        print("\nHow to configure when ready:")
        print("  1. Copy .env.example to .env (do NOT commit .env):")
        print("       copy .env.example .env")
        print("  2. Edit .env and supply:")
        print("       OPENROUTER_API_KEY=your_actual_key_here")
        print("       OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free (or your preferred model)")
        print("  3. Re-run: python smoke_test_llm.py")
        print("\nNote: Rules-based extraction remains 100% functional without LLM credentials.")
        return 0

    print("Initiating live provider request to OpenRouter...")
    adapter = OpenRouterExtractionAdapter.from_environment()

    test_message = "Customer: Test Store, phone +91 91234 56789. Send 2 box 500ml oil."
    try:
        result = adapter.extract(test_message)
        print("\nProvider response successfully received and validated:")
        print(f"  Method: {result.get('method')}")
        print(f"  Lines extracted: {len(result.get('lines', []))}")
        print(f"  Sample line: {result.get('lines', [{}])[0] if result.get('lines') else 'none'}")
        print("\nResult: [SUCCESS] Successful real provider request.")
        return 0
    except LLMExtractionError as exc:
        print(f"\nProvider failure: {exc}")
        print("\nResult: [FAILED] Failed because configuration or provider access is invalid.")
        return 1
    except Exception as exc:
        print(f"\nUnexpected error during request: {type(exc).__name__}: {exc}")
        print("\nResult: [FAILED] Failed because configuration or provider access is invalid.")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="KaryaMitra AI LLM Adapter Smoke Test")
    parser.add_argument("--mock", action="store_true", help="Run offline mocked verification only")
    parser.add_argument("--status", action="store_true", help="Check and print configuration status only")
    args = parser.parse_args()

    if args.mock:
        sys.exit(run_mocked_test())

    if args.status:
        status, reason, _, model = check_status()
        print(f"[{status}] {reason}")
        sys.exit(0)

    sys.exit(run_smoke_test())


if __name__ == "__main__":
    main()

from pathlib import Path

import pytest

from catalogue import Catalogue
from orders import OrderService


@pytest.fixture
def service():
    return OrderService(Catalogue(Path(__file__).parents[1] / "data" / "products.csv"), enable_inventory=False)


def test_successful_processing_approval_and_export(service):
    order = service.process("Send 2 box 500ml oil and 5 dozen soap.", "SYN-DEV-001")
    assert order["state"] == "VERIFIED"
    assert service.approve(order["id"])["state"] == "APPROVED"
    assert service.exportable(order["id"])["id"] == order["id"]


def test_unresolved_order_cannot_be_approved(service):
    order = service.process("Send 2 box small shampoo.")
    assert order["state"] == "NEEDS_CLARIFICATION"
    with pytest.raises(ValueError):
        service.approve(order["id"])


def test_rejected_order_cannot_export(service):
    order = service.process("Send 2 box small shampoo.")
    assert service.reject(order["id"])["state"] == "REJECTED"
    with pytest.raises(PermissionError):
        service.exportable(order["id"])


# Regression tests for natural-language order extraction bug fix


def test_test_a_detailed_order_full_processing(service):
    """Test A — Detailed order with instructions: extraction and verification."""
    message = "Bhau, please prepare an order for my shop. I need 4 boxes of 500ml oil and 8 dozen soap bars. Check the product names and prices from the catalogue, convert the quantities into individual units, and show me the item-wise totals and grand total. If any product is unclear, ask me before proceeding. Keep the order pending until I review and approve it."
    order = service.process(message)
    assert len(order["lines"]) == 2, f"Expected exactly 2 lines, got {len(order['lines'])}"
    assert order["lines"][0]["product_text"] == "500ml oil"
    assert order["lines"][0]["quantity"] == 4
    assert order["lines"][0]["requested_unit"] == "box"
    assert order["lines"][1]["product_text"] == "soap bars"
    assert order["lines"][1]["quantity"] == 8
    assert order["lines"][1]["requested_unit"] == "dozen"
    # Both should match catalogue and be verified
    assert order["lines"][0]["verified"] is True
    assert order["lines"][1]["verified"] is True
    assert order["state"] == "VERIFIED"
    # Verify correct conversions and totals
    assert order["lines"][0]["converted_quantity"] == 48  # 4 boxes * 12
    assert order["lines"][0]["line_total"] == 3960.0  # 48 * 82.50
    assert order["lines"][1]["converted_quantity"] == 96  # 8 dozen * 12
    assert order["lines"][1]["line_total"] == 1728.0  # 96 * 18.00


def test_simple_soap_order(service):
    """Test simple order: 'Send 4 boxes 500ml oil and 8 dozen soap.'"""
    message = "Send 4 boxes 500ml oil and 8 dozen soap."
    order = service.process(message)
    assert len(order["lines"]) == 2
    assert order["lines"][0]["product_text"] == "500ml oil"
    assert order["lines"][0]["quantity"] == 4
    assert order["lines"][0]["requested_unit"] == "box"
    assert order["lines"][1]["product_text"] == "soap"
    assert order["lines"][1]["quantity"] == 8
    assert order["lines"][1]["requested_unit"] == "dozen"
    # Both should match catalogue and be verified
    assert order["lines"][0]["verified"] is True
    assert order["lines"][1]["verified"] is True
    assert order["state"] == "VERIFIED"


def test_test_c_delivery_context_full_processing(service):
    """Test C — Order with delivery context: extraction and verification."""
    message = "Please prepare our shop order for tomorrow. We need 4 boxes of 500ml oil and 10 dozen soap bars. Check catalogue prices and show the total before dispatch."
    order = service.process(message)
    assert len(order["lines"]) == 2
    assert order["lines"][0]["product_text"] == "500ml oil"
    assert order["lines"][0]["quantity"] == 4
    assert order["lines"][0]["requested_unit"] == "box"
    assert order["lines"][1]["product_text"] == "soap bars"
    assert order["lines"][1]["quantity"] == 10
    assert order["lines"][1]["requested_unit"] == "dozen"
    # Both should match catalogue and be verified
    assert order["lines"][0]["verified"] is True
    assert order["lines"][1]["verified"] is True
    assert order["state"] == "VERIFIED"


def test_test_d_ambiguous_product_requires_clarification(service):
    """Test D — Ambiguous product must require clarification and block approval."""
    message = "Send 2 boxes of 500ml oil and 2 dozen classic soap. Ask me if the soap product is unclear."
    order = service.process(message)
    assert len(order["lines"]) == 2
    # Oil should be verified
    assert order["lines"][0]["product_text"] == "500ml oil"
    assert order["lines"][0]["verified"] is True
    # Classic soap is ambiguous (two SKUs match)
    assert order["lines"][1]["product_text"] == "classic soap"
    assert order["lines"][1]["verified"] is False
    assert len(order["lines"][1]["match_evidence"]) == 2
    # Order should be in NEEDS_CLARIFICATION state
    assert order["state"] == "NEEDS_CLARIFICATION"
    # Approval must be blocked
    with pytest.raises(ValueError, match="Only a verified order"):
        service.approve(order["id"])


def test_test_e_unknown_product_blocks_approval(service):
    """Test E — Unknown product must remain unresolved and block approval."""
    message = "Send 3 boxes of 500ml oil and 5 dozen mystery drink. Show the grand total."
    order = service.process(message)
    assert len(order["lines"]) == 2
    # Oil should be verified
    assert order["lines"][0]["product_text"] == "500ml oil"
    assert order["lines"][0]["verified"] is True
    # Mystery drink has no catalogue match
    assert order["lines"][1]["product_text"] == "mystery drink"
    assert order["lines"][1]["verified"] is False
    assert order["lines"][1]["sku"] is None
    assert "No catalogue product matches" in order["lines"][1]["findings"][0]
    # Order should be in NEEDS_CLARIFICATION state
    assert order["state"] == "NEEDS_CLARIFICATION"
    # Approval must be blocked
    with pytest.raises(ValueError, match="Only a verified order"):
        service.approve(order["id"])


def test_case_a_keeps_every_requested_line_and_blocks_implicit_unit_approval(service):
    order = service.process("I need 5 bottles of 500ml oil and 10 soap bars.")

    assert [(line["sku"], line["quantity"], line["requested_unit"]) for line in order["lines"]] == [
        ("SYN-OIL-500", 5, "bottle"),
        ("SYN-SOAP-100", 10, None),
    ]
    assert order["lines"][0]["line_total"] == 412.5
    assert order["lines"][1]["verified"] is False
    assert any("Unit is required" in finding for finding in order["lines"][1]["findings"])
    assert order["state"] == "NEEDS_CLARIFICATION"
    with pytest.raises(ValueError, match="Only a verified order"):
        service.approve(order["id"])


def test_case_b_uses_only_catalogue_defined_conversions_and_prices(service):
    order = service.process("Send 2 boxes of 500ml oil and 5 dozen soap.")

    assert order["state"] == "VERIFIED"
    assert [(line["sku"], line["converted_quantity"], line["line_total"]) for line in order["lines"]] == [
        ("SYN-OIL-500", 24, 1980.0),
        ("SYN-SOAP-100", 60, 1080.0),
    ]
    assert sum(line["line_total"] for line in order["lines"]) == 3060.0


def test_incomplete_packaging_request_blocks_approval_without_a_silent_drop(service):
    order = service.process("Please send 2 boxes.")

    assert order["lines"] == []
    assert order["unrecognised_text"] == ["2 boxes"]
    assert order["state"] == "NEEDS_CLARIFICATION"
    with pytest.raises(ValueError, match="Only a verified order"):
        service.approve(order["id"])


def test_llm_fallback_to_rules_when_unconfigured(service):
    """Test that LLM request safely falls back to rules when unconfigured."""
    message = "Send 1 bottle oil."
    order = service.process(message, extraction_method="llm")
    # Should have recorded the requested method
    assert order["parser"]["requested_method"] == "llm"
    # But actually used rules (fallback)
    assert order["parser"]["method"] == "rules"
    # Fallback reason should be present
    assert order["fallback_reason"] is not None
    # The fallback reason should indicate the LLM was unavailable or failed
    assert "unavailable" in order["fallback_reason"].lower() or "failed" in order["fallback_reason"].lower()
    # Order should still be processed correctly
    assert order["state"] == "VERIFIED"

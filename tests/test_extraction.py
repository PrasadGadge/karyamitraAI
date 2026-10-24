import pytest
from extraction import extract


def test_clear_order_is_extracted():
    result = extract("Send 2 box 500ml oil and 5 dozen soap.")
    assert result["method"] == "rules"
    assert result["lines"] == [
        {"product_text": "500ml oil", "quantity": 2, "unit": "box", "source_text": "2 box 500ml oil"},
        {"product_text": "soap", "quantity": 5, "unit": "dozen", "source_text": "5 dozen soap"},
    ]


def test_limited_marathi_hinglish_separator_is_supported():
    result = extract("Bhau, 2 box 500ml oil ani 5 dozen soap pathav.")
    assert len(result["lines"]) == 2


def test_missing_quantity_is_explicit():
    result = extract("Please send soap.")
    assert result["lines"][0]["quantity"] is None


@pytest.mark.parametrize("message", ["", "   ", None])
def test_malformed_input_is_rejected(message):
    with pytest.raises(ValueError):
        extract(message)


# Regression tests for natural-language order extraction bug fix


def test_test_a_detailed_order_with_instructions():
    """Test A — Detailed order with introductory text and processing instructions."""
    message = "Bhau, please prepare an order for my shop. I need 4 boxes of 500ml oil and 8 dozen soap bars. Check the product names and prices from the catalogue, convert the quantities into individual units, and show me the item-wise totals and grand total. If any product is unclear, ask me before proceeding. Keep the order pending until I review and approve it."
    result = extract(message)
    assert len(result["lines"]) == 2, f"Expected exactly 2 product lines, got {len(result['lines'])}"
    assert result["lines"][0]["product_text"] == "500ml oil"
    assert result["lines"][0]["quantity"] == 4
    assert result["lines"][0]["unit"] == "box"
    assert result["lines"][1]["product_text"] == "soap bars"
    assert result["lines"][1]["quantity"] == 8
    assert result["lines"][1]["unit"] == "dozen"


def test_test_b_short_order():
    """Test B — Short order without introductory text."""
    message = "Send 4 boxes 500ml oil and 8 dozen soap."
    result = extract(message)
    assert len(result["lines"]) == 2
    assert result["lines"][0]["product_text"] == "500ml oil"
    assert result["lines"][0]["quantity"] == 4
    assert result["lines"][0]["unit"] == "box"
    assert result["lines"][1]["product_text"] == "soap"
    assert result["lines"][1]["quantity"] == 8
    assert result["lines"][1]["unit"] == "dozen"


def test_soap_bar_variations():
    """Test that 'soap bar' and 'soap bars' are extracted correctly."""
    message1 = "Send 4 boxes 500ml oil and 8 dozen soap bars."
    result1 = extract(message1)
    assert len(result1["lines"]) == 2
    assert result1["lines"][1]["product_text"] == "soap bars"
    
    message2 = "Send 4 boxes of 500ml oil and 8 dozen soap bar."
    result2 = extract(message2)
    assert len(result2["lines"]) == 2
    assert result2["lines"][1]["product_text"] == "soap bar"


def test_test_c_delivery_context():
    """Test C — Order with delivery context and pricing instructions."""
    message = "Please prepare our shop order for tomorrow. We need 4 boxes of 500ml oil and 10 dozen soap. Check catalogue prices and show the total before dispatch."
    result = extract(message)
    assert len(result["lines"]) == 2
    assert result["lines"][0]["product_text"] == "500ml oil"
    assert result["lines"][0]["quantity"] == 4
    assert result["lines"][0]["unit"] == "box"
    assert result["lines"][1]["product_text"] == "soap"
    assert result["lines"][1]["quantity"] == 10
    assert result["lines"][1]["unit"] == "dozen"


def test_test_d_ambiguous_product():
    """Test D — Order with ambiguous product and clarification instruction."""
    message = "Send 2 boxes of 500ml oil and 2 dozen classic soap. Ask me if the soap product is unclear."
    result = extract(message)
    assert len(result["lines"]) == 2
    assert result["lines"][0]["product_text"] == "500ml oil"
    assert result["lines"][0]["quantity"] == 2
    assert result["lines"][0]["unit"] == "box"
    assert result["lines"][1]["product_text"] == "classic soap"
    assert result["lines"][1]["quantity"] == 2
    assert result["lines"][1]["unit"] == "dozen"


def test_test_e_unknown_product():
    """Test E — Order with unknown product and pricing instruction."""
    message = "Send 3 boxes of 500ml oil and 5 dozen mystery drink. Show the grand total."
    result = extract(message)
    assert len(result["lines"]) == 2
    assert result["lines"][0]["product_text"] == "500ml oil"
    assert result["lines"][0]["quantity"] == 3
    assert result["lines"][0]["unit"] == "box"
    assert result["lines"][1]["product_text"] == "mystery drink"
    assert result["lines"][1]["quantity"] == 5
    assert result["lines"][1]["unit"] == "dozen"

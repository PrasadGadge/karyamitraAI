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

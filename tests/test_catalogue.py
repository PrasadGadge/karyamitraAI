from pathlib import Path

from catalogue import Catalogue


CATALOGUE = Catalogue(Path(__file__).parents[1] / "data" / "products.csv")


def line(product, quantity=1, unit="bottle"):
    return {"product_text": product, "quantity": quantity, "unit": unit, "source_text": f"{quantity} {unit} {product}"}


def test_exact_and_alias_match():
    assert CATALOGUE.validate_line(line("500ml oil", 1, "bottle"))["verified"]
    assert CATALOGUE.validate_line(line("oil", 1, "bottle"))["sku"] == "SYN-OIL-500"


def test_ambiguous_and_unknown_products_are_unresolved():
    assert CATALOGUE.validate_line(line("classic soap", 1, "bar"))["match_count"] == 2
    assert CATALOGUE.validate_line(line("unknown thing", 1, "piece"))["match_count"] == 0


def test_explicit_dozen_and_box_rules():
    assert CATALOGUE.validate_line(line("soap", 2, "dozen"))["converted_quantity"] == 24
    assert CATALOGUE.validate_line(line("500ml oil", 2, "box"))["converted_quantity"] == 24


def test_unconfigured_box_and_missing_price_fail_validation():
    assert not CATALOGUE.validate_line(line("small shampoo", 1, "box"))["verified"]
    assert "Catalogue price is missing or invalid." in CATALOGUE.validate_line(line("unpriced cleaner", 1, "bottle"))["findings"]

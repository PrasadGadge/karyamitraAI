"""Catalogue loading, deterministic matching, and explicit unit validation."""
from __future__ import annotations

import csv
import re
from pathlib import Path


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


class Catalogue:
    def __init__(self, path: Path):
        with path.open(encoding="utf-8", newline="") as handle:
            self.products = list(csv.DictReader(handle))

    def match(self, product_text: str) -> list[dict]:
        needle = _normalise(product_text)
        matches: list[dict] = []
        for item in self.products:
            terms = [item["sku"], item["name"], *item["aliases"].split("|")]
            if any(_normalise(term) == needle for term in terms if term):
                matches.append(item)
        return matches

    @staticmethod
    def conversions(product: dict) -> dict[str, int]:
        result: dict[str, int] = {}
        for rule in product.get("supported_conversions", "").split("|"):
            if ":" in rule:
                unit, amount = rule.split(":", 1)
                result[unit] = int(amount)
        return result

    def validate_line(self, extracted: dict) -> dict:
        findings: list[str] = []
        matches = self.match(extracted["product_text"])
        result = {"source_text": extracted["source_text"], "product_text": extracted["product_text"], "quantity": extracted["quantity"], "requested_unit": extracted["unit"], "match_count": len(matches), "match_evidence": [], "sku": None, "product_name": None, "sellable_unit": None, "converted_quantity": None, "unit_price": None, "line_total": None, "findings": findings, "verified": False}
        if len(matches) == 0:
            findings.append("No catalogue product matches this description.")
            return result
        if len(matches) > 1:
            result["match_evidence"] = [{"sku": item["sku"], "name": item["name"]} for item in matches]
            findings.append("Multiple catalogue products match; human clarification is required.")
            return result
        product = matches[0]
        result.update({"sku": product["sku"], "product_name": product["name"], "sellable_unit": product["sellable_unit"], "match_evidence": [{"sku": product["sku"], "name": product["name"], "matched_aliases": product["aliases"].split("|")}]})
        if extracted["quantity"] is None or extracted["quantity"] <= 0:
            findings.append("Quantity is required and must be positive.")
        if not extracted["unit"]:
            findings.append("Unit is required; it was not inferred from the catalogue.")
        else:
            factor = self.conversions(product).get(extracted["unit"])
            if factor is None:
                findings.append(f"Unsupported conversion from {extracted['unit']} for this product.")
            elif extracted["quantity"]:
                result["converted_quantity"] = extracted["quantity"] * factor
        try:
            price = float(product["price"])
            if price <= 0:
                raise ValueError
            result["unit_price"] = price
            if result["converted_quantity"] is not None:
                result["line_total"] = round(price * result["converted_quantity"], 2)
        except (TypeError, ValueError):
            findings.append("Catalogue price is missing or invalid.")
        result["verified"] = not findings
        return result

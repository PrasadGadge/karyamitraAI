"""Small, deliberately limited rules-based order extraction."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PARSER_METHOD = "rules"
PARSER_VERSION = "1.0"
_UNITS = {"box": "box", "boxes": "box", "dozen": "dozen", "bottle": "bottle", "bottles": "bottle", "bar": "bar", "bars": "bar", "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece"}
_LEADING = re.compile(r"^(?:please\s+|send\s+|bhau\s*,?\s*)", re.I)
_TRAILING = re.compile(r"\s+(?:pathav|please|thanks?)\.?$", re.I)
_ITEM = re.compile(r"^(?:(?P<quantity>\d+)\s+)?(?P<product>.+?)$", re.I)
_UNIT_PREFIX = re.compile(r"^(?P<unit>box(?:es)?|dozen|bottles?|bars?|pieces?|pcs?)\s+(?P<product>.+)$", re.I)


@dataclass
class ExtractedLine:
    product_text: str
    quantity: int | None
    unit: str | None
    source_text: str


def _segments(message: str) -> list[str]:
    cleaned = _LEADING.sub("", message.strip())
    cleaned = _TRAILING.sub("", cleaned)
    return [part.strip(" .") for part in re.split(r"\s*(?:,|\band\b|\bani\b)\s*", cleaned, flags=re.I) if part.strip(" .")]


def extract(message: str) -> dict:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    lines: list[dict] = []
    unrecognised: list[str] = []
    for segment in _segments(message):
        match = _ITEM.match(segment)
        if not match or not match.group("product").strip():
            unrecognised.append(segment)
            continue
        product = match.group("product").strip()
        unit_match = _UNIT_PREFIX.match(product)
        unit_raw = ""
        if unit_match:
            unit_raw = unit_match.group("unit").lower()
            product = unit_match.group("product").strip()
        line = ExtractedLine(product_text=product, quantity=int(match.group("quantity")) if match.group("quantity") else None, unit=_UNITS.get(unit_raw) if unit_raw else None, source_text=segment)
        lines.append(asdict(line))
    if not lines:
        raise ValueError("no processable order line found")
    return {"method": PARSER_METHOD, "version": PARSER_VERSION, "lines": lines, "unrecognised_text": unrecognised}

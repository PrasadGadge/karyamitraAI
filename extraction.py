"""Small, deliberately limited rules-based order extraction."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PARSER_METHOD = "rules"
PARSER_VERSION = "1.1"
_UNITS = {"box": "box", "boxes": "box", "dozen": "dozen", "bottle": "bottle", "bottles": "bottle", "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece"}
_LEADING = re.compile(r"^(?:please\s+|send\s+|bhau\s*,?\s*)", re.I)
_TRAILING = re.compile(r"\s+(?:pathav|please|thanks?)\.?\s*$", re.I)
_ITEM = re.compile(r"^(?:(?P<quantity>\d+)\s+)?(?P<product>.+?)$", re.I)
_UNIT_PREFIX = re.compile(r"^(?P<unit>box(?:es)?|dozen|bottles?|pieces?|pcs?)\s+(?P<product>.+)$", re.I)
# Pattern to find product mentions: quantity + unit + product
# Note: "bar" and "bars" are excluded from unit matching to allow them as product descriptors
_PRODUCT_PATTERN = re.compile(
    r"(?P<quantity>\d+)\s+(?P<unit>box(?:es)?|dozen|bottles?|pieces?|pcs?)(?:\s+of\s+)?(?P<product>[^.!?]+?)(?=\s*(?:,|\sand\b|\bani\b|\bpathav\b)|\.|!|\?$)",
    re.I
)
# Fallback pattern: quantity + product (unit might be implicit)
_QUANTITY_PRODUCT_PATTERN = re.compile(
    r"(?P<quantity>\d+)\s+(?P<product>[^.!?]+?)(?:\s*(?:,|\sand\b|\bani\b)|\.|!|\?$)",
    re.I
)


@dataclass
class ExtractedLine:
    product_text: str
    quantity: int | None
    unit: str | None
    source_text: str


def _segments(message: str) -> list[str]:
    """Extract product segments using pattern matching, not simple splitting."""
    cleaned = _LEADING.sub("", message.strip())
    cleaned = _TRAILING.sub("", cleaned)

    segments = []

    # First, try to find explicit quantity + unit + product patterns
    for match in _PRODUCT_PATTERN.finditer(cleaned):
        segment = match.group(0).strip()
        if segment:
            segments.append(segment)

    # If no patterns found, fall back to simple splitting on "and"/"ani"
    if not segments:
        raw_parts = re.split(r"\s*(?:,|\band\b|\bani\b)\s*", cleaned, flags=re.I)
        for part in raw_parts:
            part = part.strip(" .")
            if part and len(part.split()) <= 15:
                segments.append(part)

    return segments


def extract(message: str) -> dict:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    lines: list[dict] = []
    unrecognised: list[str] = []

    # First try to extract using the product pattern
    cleaned = _LEADING.sub("", message.strip())
    # Don't strip trailing words like "pathav" before pattern matching
    # Only strip them for fallback processing

    # Split the message on "and"/"ani" first to handle repeated patterns
    # This is necessary because the regex lookahead stops at separators
    segments = re.split(r"\s+(?:and\b|\bani\b)\s+", cleaned, flags=re.I)
    
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
            
        for match in _PRODUCT_PATTERN.finditer(segment):
            quantity = int(match.group("quantity"))
            unit_raw = match.group("unit").lower()
            product = match.group("product").strip()
            # Strip trailing "and" if present
            if product.lower().endswith(" and"):
                product = product[:-4].strip()

            unit = _UNITS.get(unit_raw)
            source_text = match.group(0).strip()

            line = ExtractedLine(
                product_text=product,
                quantity=quantity,
                unit=unit,
                source_text=source_text
            )
            lines.append(asdict(line))

    # If no patterns found, fall back to segment-based extraction
    if not lines:
        cleaned_for_fallback = _TRAILING.sub("", cleaned)
        raw_parts = re.split(r"\s*(?:,|\band\b|\bani\b)\s*", cleaned_for_fallback, flags=re.I)
        for part in raw_parts:
            part = part.strip(" .")
            if not part or len(part.split()) > 15:
                continue
            match = _ITEM.match(part)
            if not match or not match.group("product").strip():
                unrecognised.append(part)
                continue
            product = match.group("product").strip()
            # Strip leading "of " from product text if present
            if product.lower().startswith("of "):
                product = product[3:].strip()
            unit_match = _UNIT_PREFIX.match(product)
            unit_raw = ""
            if unit_match:
                unit_raw = unit_match.group("unit").lower()
                product = unit_match.group("product").strip()
            line = ExtractedLine(product_text=product, quantity=int(match.group("quantity")) if match.group("quantity") else None, unit=_UNITS.get(unit_raw) if unit_raw else None, source_text=part)
            lines.append(asdict(line))

    if not lines:
        raise ValueError("no processable order line found")
    return {"method": PARSER_METHOD, "version": PARSER_VERSION, "lines": lines, "unrecognised_text": unrecognised}

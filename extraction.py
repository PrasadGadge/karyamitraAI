"""Small, deliberately limited rules-based order extraction."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PARSER_METHOD = "rules"
PARSER_VERSION = "1.2"
_UNITS = {
    "box": "box", "boxes": "box", "dozen": "dozen", "bottle": "bottle",
    "bottles": "bottle", "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
}
_LEADING = re.compile(r"^(?:(?:please|send)\s+|bhau\s*,?\s*)+", re.I)
_TRAILING = re.compile(r"\s+(?:pathav|please|thanks?)\.?\s*$", re.I)
_ITEM = re.compile(r"^(?:(?P<quantity>\d+)\s+)?(?P<product>.+?)$", re.I)
_UNIT_PREFIX = re.compile(r"^(?P<unit>box(?:es)?|dozen|bottles?|pieces?|pcs?)\s+(?P<product>.+)$", re.I)
_UNIT_WORDS = r"box(?:es)?|dozen|bottles?|pieces?|pcs?"
_LINE_END = r"(?=\s*(?:,|\band\b|\bani\b|\bpathav\b|[.!?]|$))"

# Scan the whole message rather than splitting it first. Splitting removed the
# conjunction terminator from each non-final fragment, making those fragments
# impossible for the former pattern to match.
_ORDER_LINE = re.compile(
    rf"\b(?P<quantity>\d+)\s+(?:(?P<unit>{_UNIT_WORDS})(?:\s+of)?\s+)?"
    rf"(?P<product>[^.!?]+?){_LINE_END}",
    re.I,
)
_INCOMPLETE_PACK = re.compile(
    rf"\b\d+\s+(?:{_UNIT_WORDS})(?:\s+of)?(?=\s*(?:,|\band\b|\bani\b|\bpathav\b|[.!?]|$))",
    re.I,
)


@dataclass
class ExtractedLine:
    product_text: str
    quantity: int | None
    unit: str | None
    source_text: str


def _fallback_line(message: str) -> dict | None:
    """Preserve the existing limited support for a single unquantified item."""
    cleaned = _TRAILING.sub("", _LEADING.sub("", message.strip())).strip(" .")
    if re.search(r"[,.!?]|\b(?:and|ani)\b", cleaned, flags=re.I):
        return None
    match = _ITEM.match(cleaned)
    if not match or not match.group("product").strip():
        return None
    product = match.group("product").strip()
    unit_match = _UNIT_PREFIX.match(product)
    unit_raw = unit_match.group("unit").lower() if unit_match else ""
    if unit_match:
        product = unit_match.group("product").strip()
    return asdict(ExtractedLine(
        product_text=product,
        quantity=int(match.group("quantity")) if match.group("quantity") else None,
        unit=_UNITS.get(unit_raw) if unit_raw else None,
        source_text=cleaned,
    ))


def extract(message: str) -> dict:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")

    incomplete_matches = list(_INCOMPLETE_PACK.finditer(message))
    # Preserve offsets while preventing an incomplete prefix such as "2 boxes
    # and 5 dozen soap" from consuming the later valid request as its product.
    masked_message = list(message)
    for incomplete in incomplete_matches:
        masked_message[incomplete.start():incomplete.end()] = " " * (incomplete.end() - incomplete.start())

    lines: list[dict] = []
    for match in _ORDER_LINE.finditer("".join(masked_message)):
        product = match.group("product").strip()
        if not product:
            continue
        unit_raw = match.group("unit")
        # The optional unit group may legally be skipped by the regex. Do not
        # reinterpret a bare "2 boxes" as product "boxes"; report it below as
        # an incomplete pack request instead.
        if unit_raw is None and product.lower() in _UNITS:
            continue
        lines.append(asdict(ExtractedLine(
            product_text=product,
            quantity=int(match.group("quantity")),
            unit=_UNITS.get(unit_raw.lower()) if unit_raw else None,
            source_text=message[match.start():match.end()].strip(),
        )))

    # An incomplete pack request is an actionable extraction failure. Return it
    # to the workflow so approval is blocked instead of inventing a product.
    unrecognised = [match.group(0).strip() for match in incomplete_matches]

    if not lines and not unrecognised:
        fallback = _fallback_line(message)
        if fallback:
            lines.append(fallback)

    if not lines and not unrecognised:
        raise ValueError("no processable order line found")
    return {"method": PARSER_METHOD, "version": PARSER_VERSION, "lines": lines, "unrecognised_text": unrecognised}

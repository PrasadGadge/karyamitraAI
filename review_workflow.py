"""Offline blind-review packet generation and strict human-annotation import."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from catalogue import Catalogue
from evaluation import EVALUATION_DIR, load_evaluation

ROOT = Path(__file__).parent
PACKET_DIR = ROOT / "data" / "review_packets" / "phase2_5_v1"
ARTIFACT_DIR = ROOT / "data" / "review_artifacts"
REVIEW_STATUSES = {"pending_review", "reviewed", "needs_adjudication", "adjudicated"}
OUTCOMES = {"DRAFT", "NEEDS_CLARIFICATION", "VERIFIED"}
UNITS = {"box", "dozen", "bottle", "bar", "piece"}


def _blind_record(record: dict) -> dict:
    """Deliberately copy only inputs and neutral metadata, never candidate labels."""
    return {
        "record_id": record["record_id"],
        "source_type": record["source_type"],
        "language_category": record["language_category"],
        "input_message": record["input_message"],
        "category": record["category"],
        "split": record["split"],
        "reviewer_id": "",
        "review_status": "pending_review",
        "correct_item_count": None,
        "items": [],
        "ambiguity_requires_clarification": None,
        "missing_fields": [],
        "expected_validation_outcome": None,
        "explanation": "",
        "adjudication_status": "not_required",
    }


def build_packet(output_dir: Path = PACKET_DIR) -> Path:
    candidate, locked, _ = load_evaluation()
    output_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "packet_version": "phase2_5_v1",
        "purpose": "Blind independent annotation of synthetic KaryaMitra messages. No candidate answer, parser output, LLM output, or score is included.",
        "records": [_blind_record(record) for record in candidate + locked],
    }
    (output_dir / "blind_review_template.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    catalogue_path = ROOT / "data" / "products.csv"
    (output_dir / "catalogue_for_review.csv").write_bytes(catalogue_path.read_bytes())
    (output_dir / "REVIEW_PROTOCOL.md").write_text("""# KaryaMitra independent review protocol

All messages and catalogue records in this packet are **synthetic**. Review each message against `catalogue_for_review.csv` before looking at any implementation output. Do not open candidate annotation or evaluation files while reviewing.

For each record in `blind_review_template.json`:

1. Add your non-empty `reviewer_id` or initials.
2. Set `review_status` to `reviewed` only after personally inspecting it. Use `needs_adjudication` if uncertain; do not guess.
3. Enter `correct_item_count`. For every unambiguous item, add an object to `items` with `sku`, `quantity`, `unit`, and `normalized_quantity`. Use a `null` SKU only when product identity is unresolved.
4. Set `ambiguity_requires_clarification`, list missing fields (for example `product`, `quantity`, `unit_conversion`, `price`, or `privacy_masking`), and select `DRAFT`, `NEEDS_CLARIFICATION`, or `VERIFIED`.
5. Explain difficult, malformed, Marathi/Hinglish, or privacy-containing messages briefly. Do not infer a product, a missing quantity, an unconfigured box size, or a price.

Only configured conversions in the catalogue are permitted. A dozen means 12 sellable units only where the product has a `dozen:12` rule. A box is valid only where that product has an explicit `box:N` rule. The 12 locked-test records must not be used to tune a parser, prompt, or business rule.

When finished, save a copy as `completed_review.json` and ask the project owner to run the import command in the README. The importer validates the file and creates a new versioned artifact; it never overwrites the candidate annotations.
""", encoding="utf-8")
    return output_dir


def validate_packet(packet: dict, require_all: bool = True) -> list[str]:
    candidate, locked, _ = load_evaluation()
    source_ids = {record["record_id"] for record in candidate + locked}
    records = packet.get("records")
    if not isinstance(records, list):
        return ["records must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    product_by_sku = {product["sku"]: product for product in Catalogue(ROOT / "data" / "products.csv").products}
    for index, annotation in enumerate(records):
        prefix = f"record {index}"
        record_id = annotation.get("record_id")
        if not record_id or record_id not in source_ids:
            errors.append(f"{prefix}: unknown record_id")
        if record_id in seen:
            errors.append(f"{prefix}: duplicate record_id")
        seen.add(record_id)
        status = annotation.get("review_status")
        if status not in REVIEW_STATUSES:
            errors.append(f"{prefix}: invalid review_status")
            continue
        if status == "pending_review":
            continue
        if not str(annotation.get("reviewer_id", "")).strip():
            errors.append(f"{prefix}: reviewer_id is required once review begins")
        if annotation.get("correct_item_count") is None or not isinstance(annotation["correct_item_count"], int) or annotation["correct_item_count"] < 0:
            errors.append(f"{prefix}: correct_item_count must be a non-negative integer")
        items = annotation.get("items")
        if not isinstance(items, list) or annotation.get("correct_item_count") != len(items):
            errors.append(f"{prefix}: item count must equal items length")
        for item in items or []:
            sku, unit = item.get("sku"), item.get("unit")
            if sku is not None and sku not in product_by_sku:
                errors.append(f"{prefix}: unknown SKU {sku}")
            if unit is not None and unit not in UNITS:
                errors.append(f"{prefix}: invalid unit {unit}")
            if item.get("quantity") is not None and (not isinstance(item["quantity"], int) or item["quantity"] <= 0):
                errors.append(f"{prefix}: quantity must be a positive integer or null")
            if sku in product_by_sku and unit and item.get("quantity") is not None:
                conversions = Catalogue.conversions(product_by_sku[sku])
                if unit not in conversions and item.get("normalized_quantity") is not None:
                    errors.append(f"{prefix}: normalized quantity supplied for unsupported unit")
                if unit in conversions and item.get("normalized_quantity") != item["quantity"] * conversions[unit]:
                    errors.append(f"{prefix}: normalized quantity conflicts with catalogue conversion")
        if not isinstance(annotation.get("ambiguity_requires_clarification"), bool):
            errors.append(f"{prefix}: ambiguity_requires_clarification must be boolean")
        if not isinstance(annotation.get("missing_fields"), list):
            errors.append(f"{prefix}: missing_fields must be a list")
        if annotation.get("expected_validation_outcome") not in OUTCOMES:
            errors.append(f"{prefix}: invalid expected_validation_outcome")
    if require_all and seen != source_ids:
        errors.append(f"packet is incomplete: {len(source_ids - seen)} record(s) missing")
    if not any(item.get("review_status") in {"reviewed", "adjudicated"} for item in records):
        errors.append("no completed reviewed/adjudicated record exists")
    return errors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_packet(path: Path, require_all: bool = True) -> tuple[Path, Path]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_packet(packet, require_all=require_all)
    if errors:
        raise ValueError("Invalid human review packet:\n- " + "\n- ".join(errors))
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reviewed = ARTIFACT_DIR / f"human_annotations_{stamp}.json"
    reviewed.write_text(json.dumps({"artifact_version": "human-review-v1", "imported_at": datetime.now(timezone.utc).isoformat(), "source_packet": path.name, "records": packet["records"]}, indent=2), encoding="utf-8")
    candidate, locked, _ = load_evaluation()
    candidate_by_id = {record["record_id"]: record for record in candidate + locked}
    disagreements = []
    for human in packet["records"]:
        if human["review_status"] not in {"reviewed", "adjudicated", "needs_adjudication"}:
            continue
        candidate_record = candidate_by_id[human["record_id"]]
        candidate_skus = [item.get("expected_sku") for item in candidate_record["expected_items"]]
        human_skus = [item.get("sku") for item in human["items"]]
        if candidate_skus != human_skus or candidate_record["expected_validation_outcome"] != human["expected_validation_outcome"]:
            disagreements.append({"record_id": human["record_id"], "candidate_skus": candidate_skus, "human_skus": human_skus, "candidate_outcome": candidate_record["expected_validation_outcome"], "human_outcome": human["expected_validation_outcome"], "resolution": "requires_explicit_adjudication"})
    report = reviewed.with_name(reviewed.stem + "_disagreements.json")
    report.write_text(json.dumps({"human_artifact": reviewed.name, "disagreements": disagreements, "note": "No candidate answer is automatically selected; each disagreement requires explicit adjudication."}, indent=2), encoding="utf-8")
    return reviewed, report


def main() -> None:
    parser = argparse.ArgumentParser(description="KaryaMitra blind-review workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-packet")
    build.add_argument("--output", type=Path, default=PACKET_DIR)
    import_cmd = sub.add_parser("import")
    import_cmd.add_argument("path", type=Path)
    import_cmd.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    if args.command == "build-packet":
        print(build_packet(args.output))
    else:
        artifact, report = import_packet(args.path, require_all=not args.allow_partial)
        print(artifact); print(report)


if __name__ == "__main__":
    main()

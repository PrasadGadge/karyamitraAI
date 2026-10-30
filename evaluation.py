"""Dataset integrity and rules-baseline evaluation without mutating frozen inputs."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from catalogue import Catalogue
from extraction import PARSER_VERSION
from orders import OrderService

EVALUATION_DIR = Path(__file__).parent / "data" / "evaluation"
REVIEW_STATES = {"pending_review", "reviewed", "adjudicated"}
ELIGIBLE_STATES = {"reviewed", "adjudicated"}
REQUIRED_RECORD_FIELDS = {"record_id", "source_type", "language_category", "input_message", "category", "split", "expected_items", "expected_ambiguity", "expected_unresolved_fields", "expected_validation_outcome", "annotation_status", "reviewer_status"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_records(records: list[dict], permitted_splits: set[str]) -> list[str]:
    issues: list[str] = []
    ids: set[str] = set()
    for index, record in enumerate(records):
        missing = REQUIRED_RECORD_FIELDS - record.keys()
        if missing:
            issues.append(f"record {index} missing {sorted(missing)}")
        record_id = record.get("record_id")
        if not record_id or record_id in ids:
            issues.append(f"record {index} has missing or duplicate record_id")
        if isinstance(record_id, str):
            ids.add(record_id)
        if record.get("split") not in permitted_splits:
            issues.append(f"{record_id}: unsupported split")
        if record.get("annotation_status") not in REVIEW_STATES:
            issues.append(f"{record_id}: unsupported annotation status")
        if record.get("source_type") not in {"synthetic"}:
            issues.append(f"{record_id}: unsupported or unlabelled source type")
    return issues


def load_evaluation() -> tuple[list[dict], list[dict], dict]:
    candidate = read_json(EVALUATION_DIR / "development_validation_annotations.json")
    locked_messages = read_json(EVALUATION_DIR / "locked_test_messages.json")
    locked_annotations = read_json(EVALUATION_DIR / "locked_test_annotations.json")
    manifest = read_json(EVALUATION_DIR / "manifest.json")
    records = candidate["records"] + locked_annotations["records"]
    issues = validate_records(records, {"development", "validation", "locked_test"})
    message_ids = {item["record_id"] for item in locked_messages["records"]}
    annotation_ids = {item["record_id"] for item in locked_annotations["records"]}
    if message_ids != annotation_ids:
        issues.append("locked message and annotation IDs differ")
    if issues:
        raise ValueError("Invalid evaluation dataset: " + "; ".join(issues))
    return candidate["records"], locked_annotations["records"], manifest


def verify_frozen_hashes(manifest: dict) -> dict:
    frozen = manifest["frozen_files"]
    actual = {name: sha256(EVALUATION_DIR / name) for name in frozen}
    return {"valid": all(actual[name] == frozen[name] for name in frozen), "expected": frozen, "actual": actual}


def summary() -> dict:
    candidate, locked, manifest = load_evaluation()
    records = candidate + locked
    by_split = Counter(record["split"] for record in records)
    by_category = Counter(record["category"] for record in records)
    by_language = Counter(record["language_category"] for record in records)
    by_review = Counter(record["annotation_status"] for record in records)
    return {"dataset_version": manifest["dataset_version"], "total_records": len(records), "source_composition": dict(Counter(record["source_type"] for record in records)), "split_counts": dict(by_split), "category_distribution": dict(by_category), "language_distribution": dict(by_language), "annotation_status": dict(by_review), "locked_ground_truth_exposed": False, "frozen_integrity": verify_frozen_hashes(manifest)}


def _line_match(actual: dict, expected: dict) -> tuple[bool, bool, bool, bool]:
    sku = actual.get("sku") == expected.get("expected_sku")
    quantity = actual.get("quantity") == expected.get("expected_quantity")
    unit = actual.get("requested_unit") == expected.get("expected_unit")
    normalized = actual.get("converted_quantity") == expected.get("expected_normalized_quantity")
    return sku, quantity, unit, sku and quantity and unit and normalized


def evaluate(records: list[dict], catalogue: Catalogue) -> dict:
    """Evaluate only independently reviewable states; pending candidates are excluded."""
    eligible = [record for record in records if record["annotation_status"] in ELIGIBLE_STATES]
    excluded = [record["record_id"] for record in records if record not in eligible]
    counts = Counter({"records_seen": len(records), "eligible_records": len(eligible), "excluded_unreviewed": len(excluded), "sku_exact": 0, "quantity_exact": 0, "unit_exact": 0, "complete_line_exact": 0, "complete_order_exact": 0, "correctly_unresolved": 0, "incorrectly_resolved_ambiguity": 0, "unknown_handled": 0, "critical_validation_errors": 0})
    service = OrderService(catalogue)
    metric_lines = 0
    for record in eligible:
        order = service.process(record["input_message"], record["record_id"])
        expected_items = record["expected_items"]
        if record["expected_ambiguity"] or "product" in record["expected_unresolved_fields"]:
            unresolved = order["state"] in {"NEEDS_CLARIFICATION", "DRAFT"}
            counts["correctly_unresolved"] += int(unresolved)
            counts["incorrectly_resolved_ambiguity"] += int(record["expected_ambiguity"] and order["state"] == "VERIFIED")
        for actual, expected in zip(order["lines"], expected_items):
            if expected.get("expected_sku") is None:
                counts["unknown_handled"] += int(actual.get("sku") is None)
                continue
            metric_lines += 1
            sku, quantity, unit, whole = _line_match(actual, expected)
            counts["sku_exact"] += int(sku); counts["quantity_exact"] += int(quantity); counts["unit_exact"] += int(unit); counts["complete_line_exact"] += int(whole)
        counts["complete_order_exact"] += int(order["state"] == record["expected_validation_outcome"] and len(order["lines"]) == len(expected_items))
        counts["critical_validation_errors"] += int(order["state"] == "VERIFIED" and record["expected_validation_outcome"] != "VERIFIED")
    def rate(value: int, denominator: int):
        return None if not denominator else {"count": value, "denominator": denominator, "percent": round(value * 100 / denominator, 2)}
    return {"run_at": datetime.now(timezone.utc).isoformat(), "parser": {"method": "rules", "version": PARSER_VERSION}, "eligible": len(eligible), "excluded_unreviewed_record_ids": excluded, "metrics": {"exact_sku": rate(counts["sku_exact"], metric_lines), "exact_quantity": rate(counts["quantity_exact"], metric_lines), "exact_unit": rate(counts["unit_exact"], metric_lines), "complete_order": rate(counts["complete_order_exact"], len(eligible)), "correctly_unresolved": rate(counts["correctly_unresolved"], len(eligible)), "unknown_product_handling": rate(counts["unknown_handled"], len(eligible)), "critical_validation_errors": rate(counts["critical_validation_errors"], len(eligible))}, "raw_counts": dict(counts), "status": "Not evaluated" if not eligible else "Evaluation computed only on reviewed/adjudicated records"}


def run(split: str = "locked_test") -> dict:
    candidate, locked, manifest = load_evaluation()
    records = locked if split == "locked_test" else [item for item in candidate if item["split"] == split]
    result = evaluate(records, Catalogue(Path(__file__).parent / "data" / "products.csv"))
    result.update({"dataset_version": manifest["dataset_version"], "split": split, "frozen_integrity": verify_frozen_hashes(manifest)})
    return result


def save_run(split: str = "locked_test") -> Path:
    """Persist a result without touching corpus inputs; ignored by Git as generated evidence."""
    result = run(split)
    output_dir = Path(__file__).parent / "evaluation_runs"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f"rules-{split}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    print(save_run())

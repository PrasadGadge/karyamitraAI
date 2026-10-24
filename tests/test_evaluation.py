from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from catalogue import Catalogue
from evaluation import evaluate, load_evaluation, run, summary, verify_frozen_hashes


def test_evaluation_dataset_has_stable_schema_and_reproducible_split():
    candidate, locked, manifest = load_evaluation()
    all_records = candidate + locked
    assert len(all_records) == 60
    assert len({record["record_id"] for record in all_records}) == 60
    assert {split: sum(item["split"] == split for item in all_records) for split in ("development", "validation", "locked_test")} == {"development": 36, "validation": 12, "locked_test": 12}
    assert all(record["source_type"] == "synthetic" for record in all_records)
    assert all(record["annotation_status"] == "pending_review" for record in all_records)
    assert manifest["dataset_version"] == "2.0-candidate"


def test_frozen_hashes_and_readiness_summary_are_valid():
    result = verify_frozen_hashes(load_evaluation()[2])
    assert result["valid"]
    readiness = summary()
    assert readiness["annotation_status"] == {"pending_review": 60}
    assert readiness["locked_ground_truth_exposed"] is False


def test_unreviewed_records_are_excluded_from_verified_accuracy():
    reviewed = {"record_id": "TEMP-1", "source_type": "synthetic", "language_category": "English", "input_message": "Send 1 bottle oil.", "category": "clear", "split": "development", "expected_items": [{"expected_sku": "SYN-OIL-500", "expected_quantity": 1, "expected_unit": "bottle", "expected_normalized_quantity": 1}], "expected_ambiguity": False, "expected_unresolved_fields": [], "expected_validation_outcome": "VERIFIED", "annotation_status": "reviewed", "reviewer_status": "teammate"}
    pending = deepcopy(reviewed); pending["record_id"] = "TEMP-2"; pending["annotation_status"] = "pending_review"
    result = evaluate([reviewed, pending], Catalogue(Path(__file__).parents[1] / "data" / "products.csv"))
    assert result["eligible"] == 1
    assert result["raw_counts"]["excluded_unreviewed"] == 1
    assert result["metrics"]["exact_sku"]["denominator"] == 1
    assert result["metrics"]["exact_sku"]["count"] == 1


def test_locked_baseline_is_honestly_not_evaluated_and_repeatable_fields_match():
    first, second = run(), run()
    assert first["status"] == "Not evaluated"
    assert first["eligible"] == 0
    assert first["metrics"] == second["metrics"]
    assert first["frozen_integrity"] == second["frozen_integrity"]


def test_api_does_not_expose_locked_ground_truth_or_messages():
    client = TestClient(app)
    response = client.get("/api/evaluation/summary")
    assert response.status_code == 200
    text = response.text.lower()
    assert "expected_items" not in text
    assert "moon juice" not in text
    assert client.get("/api/dataset").json()["records"][0]["id"] == "SYN-DEV-001"

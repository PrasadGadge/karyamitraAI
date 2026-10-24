import json

import pytest

import review_workflow
from evaluation import load_evaluation, verify_frozen_hashes


def test_blind_packet_contains_all_inputs_but_no_candidate_answers(tmp_path):
    packet_dir = review_workflow.build_packet(tmp_path / "packet")
    template = json.loads((packet_dir / "blind_review_template.json").read_text(encoding="utf-8"))
    encoded = json.dumps(template)
    assert len(template["records"]) == 60
    assert "expected_sku" not in encoded
    assert "expected_items" not in encoded
    assert (packet_dir / "catalogue_for_review.csv").exists()
    assert (packet_dir / "REVIEW_PROTOCOL.md").exists()


def test_import_validation_rejects_unknown_sku_and_unreviewed_packet(tmp_path):
    packet_dir = review_workflow.build_packet(tmp_path / "packet")
    packet = json.loads((packet_dir / "blind_review_template.json").read_text(encoding="utf-8"))
    packet["records"][0].update({"reviewer_id": "AB", "review_status": "reviewed", "correct_item_count": 1, "items": [{"sku": "NOT-A-SKU", "quantity": 1, "unit": "bottle", "normalized_quantity": 1}], "ambiguity_requires_clarification": False, "expected_validation_outcome": "VERIFIED"})
    errors = review_workflow.validate_packet(packet, require_all=False)
    assert any("unknown SKU" in error for error in errors)
    assert review_workflow.validate_packet({"records": packet["records"][1:]}, require_all=False)[-1] == "no completed reviewed/adjudicated record exists"


def test_valid_partial_human_import_creates_versioned_artifact_and_disagreement_report(tmp_path, monkeypatch):
    packet_dir = review_workflow.build_packet(tmp_path / "packet")
    packet_path = packet_dir / "completed.json"
    packet = json.loads((packet_dir / "blind_review_template.json").read_text(encoding="utf-8"))
    packet["records"][0].update({"reviewer_id": "AB", "review_status": "reviewed", "correct_item_count": 1, "items": [{"sku": "SYN-OIL-500", "quantity": 1, "unit": "bottle", "normalized_quantity": 1}], "ambiguity_requires_clarification": False, "expected_validation_outcome": "VERIFIED", "explanation": "Reviewed independently."})
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    monkeypatch.setattr(review_workflow, "ARTIFACT_DIR", tmp_path / "artifacts")
    artifact, report = review_workflow.import_packet(packet_path, require_all=False)
    assert artifact.exists() and report.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["disagreements"] == []


def test_original_locked_artifacts_remain_hash_valid_after_packet_generation():
    assert verify_frozen_hashes(load_evaluation()[2])["valid"]

"""In-memory, traceable order processing service for the Phase 1 prototype."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from catalogue import Catalogue
from extraction import extract

STATES = {"DRAFT", "NEEDS_CLARIFICATION", "VERIFIED", "APPROVED", "REJECTED"}


class OrderService:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue
        self.orders: dict[str, dict] = {}

    @staticmethod
    def _event(event: str, detail: str = "") -> dict:
        return {"at": datetime.now(timezone.utc).isoformat(), "event": event, "detail": detail}

    def process(self, message: str, source_record_id: str | None = None) -> dict:
        started = time.perf_counter()
        order_id = str(uuid.uuid4())
        trace = [self._event("record_loaded", source_record_id or "direct message")]
        try:
            parsed = extract(message)
            trace.append(self._event("extraction_executed", f"{len(parsed['lines'])} line(s)"))
            lines = [self.catalogue.validate_line(line) for line in parsed["lines"]]
            trace.append(self._event("catalogue_lookup_completed"))
            trace.append(self._event("validation_executed"))
            unresolved = [line for line in lines if not line["verified"]]
            state = "NEEDS_CLARIFICATION" if unresolved else "VERIFIED"
            if unresolved:
                trace.append(self._event("unresolved_conditions_identified", f"{len(unresolved)} line(s)"))
            error = None
        except ValueError as exc:
            parsed, lines, unresolved, error = {"method": "rules", "version": "1.0", "lines": [], "unrecognised_text": [message]}, [], [], str(exc)
            state = "DRAFT"
            trace.append(self._event("processing_error", error))
        duration = round((time.perf_counter() - started) * 1000, 3)
        order = {"id": order_id, "source_record_id": source_record_id, "original_message": message, "parser": {"method": parsed["method"], "version": parsed["version"]}, "extracted_lines": parsed["lines"], "unrecognised_text": parsed["unrecognised_text"], "lines": lines, "state": state, "processing_duration_ms": duration, "error": error, "trace": trace, "correction_count": 0, "created_at": datetime.now(timezone.utc).isoformat()}
        self.orders[order_id] = order
        return order

    def get(self, order_id: str) -> dict | None:
        return self.orders.get(order_id)

    def approve(self, order_id: str) -> dict:
        order = self._require(order_id)
        if order["state"] != "VERIFIED":
            raise ValueError("Only a verified order with no unresolved mandatory fields can be approved.")
        order["state"] = "APPROVED"
        order["trace"].append(self._event("approved", "explicit human approval"))
        return order

    def reject(self, order_id: str) -> dict:
        order = self._require(order_id)
        if order["state"] == "APPROVED":
            raise ValueError("An approved order cannot be rejected in this in-memory prototype.")
        order["state"] = "REJECTED"
        order["trace"].append(self._event("rejected", "explicit human rejection"))
        return order

    def correct(self, order_id: str, message: str) -> dict:
        old = self._require(order_id)
        replacement = self.process(message, old["source_record_id"])
        replacement["correction_count"] = old["correction_count"] + 1
        replacement["trace"].insert(0, self._event("human_edit", f"corrected from {order_id}"))
        return replacement

    def exportable(self, order_id: str) -> dict:
        order = self._require(order_id)
        if order["state"] != "APPROVED":
            raise PermissionError("Only explicitly approved orders can be exported.")
        return order

    def metrics(self) -> dict:
        values = list(self.orders.values())
        return {"orders_processed": len(values), "verified_orders": sum(o["state"] == "VERIFIED" for o in values), "needs_clarification": sum(o["state"] == "NEEDS_CLARIFICATION" for o in values), "approved_orders": sum(o["state"] == "APPROVED" for o in values), "rejected_orders": sum(o["state"] == "REJECTED" for o in values), "processing_errors": sum(bool(o["error"]) for o in values), "corrections": sum(o["correction_count"] for o in values), "benchmark_accuracy": "Not available: no independent locked evaluation set exists."}

    def _require(self, order_id: str) -> dict:
        order = self.get(order_id)
        if not order:
            raise KeyError("Order not found")
        return order

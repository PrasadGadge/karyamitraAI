"""In-memory, traceable order processing service with persistent inventory integration."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from catalogue import Catalogue
from extraction import PARSER_METHOD, PARSER_VERSION, extract
from llm_extraction import LLMExtractionError, OpenRouterExtractionAdapter
from repository import InventoryReservationError, InventoryRepository, OrderRepository

STATES = {"DRAFT", "NEEDS_CLARIFICATION", "VERIFIED", "APPROVED", "REJECTED"}


class ExtractionAdapter(Protocol):
    def extract(self, message: str) -> dict: ...


class OrderService:
    def __init__(self, catalogue: Catalogue, llm_adapter: ExtractionAdapter | None = None, enable_inventory: bool = False):
        self.catalogue = catalogue
        self.llm_adapter = llm_adapter or OpenRouterExtractionAdapter.from_environment()
        self.orders: dict[str, dict] = {}
        self.enable_inventory = enable_inventory

    @staticmethod
    def _event(event: str, detail: str = "") -> dict:
        return {"at": datetime.now(timezone.utc).isoformat(), "event": event, "detail": detail}

    def process(self, message: str, source_record_id: str | None = None, extraction_method: str = "rules") -> dict:
        started = time.perf_counter()
        order_id = str(uuid.uuid4())
        trace = [self._event("record_loaded", source_record_id or "direct message")]
        fallback_reason = None
        try:
            if extraction_method == "llm":
                try:
                    parsed = self.llm_adapter.extract(message)
                except LLMExtractionError as exc:
                    parsed = extract(message)
                    fallback_reason = str(exc)
                    trace.append(self._event("llm_fallback_to_rules", fallback_reason))
            else:
                parsed = extract(message)
            trace.append(self._event("extraction_executed", f"{len(parsed['lines'])} line(s)"))
            lines = [self.catalogue.validate_line(line) for line in parsed["lines"]]
            trace.append(self._event("catalogue_lookup_completed"))
            trace.append(self._event("validation_executed"))
            unresolved = [line for line in lines if not line["verified"]]
            unrecognised = parsed["unrecognised_text"]
            state = "NEEDS_CLARIFICATION" if unresolved or unrecognised else "VERIFIED"
            if unresolved or unrecognised:
                detail = f"{len(unresolved)} unresolved line(s)"
                if unrecognised:
                    detail += f"; {len(unrecognised)} unparsed request segment(s)"
                trace.append(self._event("unresolved_conditions_identified", detail))
            error = None
        except ValueError as exc:
            parsed, lines, unresolved, error = {"method": PARSER_METHOD, "version": PARSER_VERSION, "lines": [], "unrecognised_text": [message]}, [], [], str(exc)
            state = "DRAFT"
            trace.append(self._event("processing_error", error))
        duration = round((time.perf_counter() - started) * 1000, 3)
        order = {"id": order_id, "source_record_id": source_record_id, "original_message": message, "parser": {"method": parsed["method"], "requested_method": extraction_method, "version": parsed["version"]}, "extracted_lines": parsed["lines"], "unrecognised_text": parsed["unrecognised_text"], "delivery_instructions": parsed.get("delivery_instructions"), "missing_fields": parsed.get("missing_fields", []), "ambiguous_fields": parsed.get("ambiguous_fields", []), "fallback_reason": fallback_reason, "lines": lines, "state": state, "processing_duration_ms": duration, "error": error, "trace": trace, "correction_count": 0, "created_at": datetime.now(timezone.utc).isoformat()}
        self.orders[order_id] = order
        return order

    def get(self, order_id: str) -> dict | None:
        return self.orders.get(order_id)

    def approve(self, order_id: str) -> dict:
        order = self._require(order_id)
        if order["state"] != "VERIFIED":
            raise ValueError("Only a verified order with no unresolved mandatory fields can be approved.")

        # Check inventory availability and reserve stock (if enabled)
        if self.enable_inventory:
            requirements: list[tuple[str, int]] = []
            for line in order["lines"]:
                if line["verified"] and line.get("sku") and line.get("converted_quantity"):
                    requirements.append((line["sku"], line["converted_quantity"]))
            try:
                OrderRepository.create_approved_order_with_reservations(order, requirements)
            except InventoryReservationError as exc:
                raise ValueError(str(exc)) from None

        order["state"] = "APPROVED"
        order["trace"].append(self._event("approved", "explicit human approval" + (" with stock reservation" if self.enable_inventory else "")))

        return order

    def reject(self, order_id: str) -> dict:
        order = self._require(order_id)
        if order["state"] == "APPROVED":
            raise ValueError("An approved order cannot be rejected in this in-memory prototype.")

        # Release any stock reservations (if inventory enabled)
        if self.enable_inventory:
            InventoryRepository.release_reservation(order_id)

            # Persist to database
            if order_id not in self.orders:
                OrderRepository.create_order(order)
            OrderRepository.update_order_state(order_id, "REJECTED")

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

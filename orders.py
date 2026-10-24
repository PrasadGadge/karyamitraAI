"""In-memory, traceable order processing service with persistent inventory integration."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from catalogue import Catalogue
from extraction import extract
from llm_extraction import LLMExtractionError, OpenRouterExtractionAdapter
from repository import InventoryRepository, OrderRepository

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
            state = "NEEDS_CLARIFICATION" if unresolved else "VERIFIED"
            if unresolved:
                trace.append(self._event("unresolved_conditions_identified", f"{len(unresolved)} line(s)"))
            error = None
        except ValueError as exc:
            parsed, lines, unresolved, error = {"method": "rules", "version": "1.0", "lines": [], "unrecognised_text": [message]}, [], [], str(exc)
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
            insufficient_items = []
            missing_inventory = []
            
            # First, check inventory for all lines BEFORE persisting the order
            for line in order["lines"]:
                if line["verified"] and line.get("sku") and line.get("converted_quantity"):
                    sku = line["sku"]
                    quantity = line["converted_quantity"]
                    
                    # Check if inventory record exists
                    inv = InventoryRepository.get_inventory(sku)
                    if not inv:
                        missing_inventory.append({
                            "sku": sku,
                            "product_name": line.get("product_name", sku),
                            "error": "Inventory record not found"
                        })
                        continue
                    
                    # Check if sufficient stock
                    available = inv["available_quantity"]
                    if available < quantity:
                        insufficient_items.append({
                            "sku": sku,
                            "product_name": line.get("product_name", sku),
                            "requested": quantity,
                            "available": available
                        })
            
            if missing_inventory:
                raise ValueError(f"Inventory record missing for approval: {missing_inventory}. Initialize stock through opening-stock workflow.")
            
            if insufficient_items:
                raise ValueError(f"Insufficient inventory for approval: {insufficient_items}")
            
            # Now persist the order (all inventory checks passed)
            try:
                OrderRepository.create_order(order)
            except Exception:
                raise ValueError("Failed to persist order after inventory check")
            
            # Now reserve stock atomically
            for line in order["lines"]:
                if line["verified"] and line.get("sku") and line.get("converted_quantity"):
                    sku = line["sku"]
                    quantity = line["converted_quantity"]
                    reserved = InventoryRepository.reserve_stock(order_id, sku, quantity)
                    if not reserved:
                        # This shouldn't happen since we checked above, but be defensive
                        InventoryRepository.release_reservation(order_id)
                        OrderRepository.update_order_state(order_id, "VERIFIED")
                        raise ValueError(f"Stock became unavailable during reservation for {sku}")
            
            # Update order state to APPROVED
            try:
                OrderRepository.update_order_state(order_id, "APPROVED")
            except Exception:
                # If state update fails, release reservations
                InventoryRepository.release_reservation(order_id)
                raise
        
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

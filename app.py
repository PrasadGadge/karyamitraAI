from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from catalogue import Catalogue
from database import init_db
from evaluation import load_evaluation
from evaluation import run as run_evaluation
from evaluation import summary as evaluation_summary
from orders import OrderService
from repository import (
    InventoryRepository,
    OrderRepository,
    ProductRepository,
    ShipmentRepository,
)

ROOT = Path(__file__).parent
catalogue = Catalogue(ROOT / "data" / "products.csv")
service = OrderService(catalogue, enable_inventory=True)
dataset = json.loads((ROOT / "data" / "sample_orders.json").read_text(encoding="utf-8"))
_, _locked_eval_records, _ = load_evaluation()
LOCKED_RECORD_IDS = {r["record_id"] for r in _locked_eval_records}

# Initialize database in demo mode for demonstration
init_db(ROOT / "data" / "products.csv", demo_mode=True)

app = FastAPI(title="KaryaMitra AI", version="0.2.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class ProcessRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    source_record_id: str | None = None
    extraction_method: Literal["rules", "llm"] = "rules"


class CorrectRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def order_or_404(order_id: str) -> dict:
    order = service.get(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    llm_adapter = getattr(service, "llm_adapter", None)
    is_avail = bool(getattr(llm_adapter, "is_available", False))
    model_name = getattr(llm_adapter, "model", "") or None
    return {
        "status": "ok",
        "catalogue_records": len(catalogue.products),
        "dataset_records": len(dataset),
        "persistence": "SQLite database; operational data persists across restarts",
        "llm_configured": is_avail,
        "llm_model": model_name,
    }


@app.get("/api/catalogue")
def get_catalogue():
    return {"records": catalogue.products, "source": "data/products.csv", "synthetic": True}


@app.get("/api/dataset")
def get_dataset():
    return {"records": dataset, "source": "data/sample_orders.json", "synthetic": True}


@app.post("/api/orders/process")
def process_order(request: ProcessRequest):
    if request.source_record_id and request.source_record_id in LOCKED_RECORD_IDS:
        raise HTTPException(
            status_code=400,
            detail="Locked-test evaluation records are protected to preserve benchmark integrity and cannot be processed in the normal intake workflow.",
        )
    return service.process(request.message, request.source_record_id, request.extraction_method)


@app.get("/api/orders")
def get_orders():
    return {"records": list(service.orders.values()), "count": len(service.orders)}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    return order_or_404(order_id)


@app.post("/api/orders/{order_id}/approve")
def approve_order(order_id: str):
    order_or_404(order_id)
    try:
        return service.approve(order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/orders/{order_id}/reject")
def reject_order(order_id: str):
    order_or_404(order_id)
    try:
        return service.reject(order_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/orders/{order_id}/correct")
def correct_order(order_id: str, request: CorrectRequest):
    order_or_404(order_id)
    return service.correct(order_id, request.message)


@app.get("/api/orders/{order_id}/export")
def export_order(order_id: str, format: str = "json"):
    order_or_404(order_id)
    try:
        order = service.exportable(order_id)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    rows = [{"order_id": order["id"], "source_record_id": order["source_record_id"], "sku": line["sku"], "product_name": line["product_name"], "quantity": line["converted_quantity"], "unit": line["sellable_unit"], "unit_price": line["unit_price"], "line_total": line["line_total"]} for line in order["lines"]]
    if format == "json":
        return JSONResponse({"order_id": order["id"], "lines": rows})
    if format == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["order_id"])
        writer.writeheader(); writer.writerows(rows)
        return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{order_id}.csv"'})
    raise HTTPException(400, "format must be json or csv")


@app.get("/api/metrics")
def metrics():
    return {**service.metrics(), "catalogue_records_loaded": len(catalogue.products), "dataset_records_loaded": len(dataset), "synthetic_records": len(dataset)}


@app.get("/api/evaluation/summary")
def get_evaluation_summary():
    """Aggregate readiness only: locked-test messages and annotations stay off the UI/API."""
    try:
        readiness = evaluation_summary()
        baseline = run_evaluation("locked_test")
    except ValueError as exc:
        raise HTTPException(500, f"Evaluation dataset integrity error: {exc}") from exc
    return {
        "dataset": {
            **readiness,
            "known_limitations": [
                "100% synthetic corpus (60/60 fictional; 0 real commercial distributor messages)",
                "English-dominated coverage (55/60, 91.7%); regional coverage limited to 5 Hinglish/Marathi patterns",
                "All 60 annotations pending independent human review (0% independently reviewed)",
                "Baseline accuracy honestly not evaluated while no eligible reviewed ground truth exists",
                "In-memory prototype; orders and telemetry reset on server restart",
            ],
            "missing_attributes": [
                "Real commercial customer intake messages",
                "Independently adjudicated ground-truth labels",
                "Generic regional vernacular/multilingual NLP models",
                "Commercial distributor ROI & production ERP deployment",
            ],
        },
        "baseline": {
            "status": baseline["status"],
            "eligible_records": baseline["eligible"],
            "excluded_unreviewed": baseline["raw_counts"]["excluded_unreviewed"],
            "metrics": baseline["metrics"],
            "locked_ground_truth_exposed": False,
        },
    }


@app.get("/api/evaluation/records")
def get_evaluation_records():
    """Safe evaluation dataset records for judge inspection.
    Locked-test expected items and ground-truth answers are strictly excluded.
    """
    candidate, locked, manifest = load_evaluation()
    safe_records = []
    for r in candidate:
        safe_records.append({
            "record_id": r["record_id"],
            "split": r["split"],
            "category": r["category"],
            "language_category": r["language_category"],
            "source_type": r["source_type"],
            "input_message": r["input_message"],
            "annotation_status": r["annotation_status"],
            "reviewer_status": r.get("reviewer_status", "not_assigned"),
        })
    for r in locked:
        safe_records.append({
            "record_id": r["record_id"],
            "split": r["split"],
            "category": r["category"],
            "language_category": r["language_category"],
            "source_type": r["source_type"],
            "input_message": "[Locked test message — protected in locked-test evaluation]",
            "annotation_status": r["annotation_status"],
            "reviewer_status": r.get("reviewer_status", "not_assigned"),
        })
    return {
        "dataset_version": manifest["dataset_version"],
        "records": safe_records,
        "total": len(safe_records),
        "split_counts": {
            "development": sum(1 for r in safe_records if r["split"] == "development"),
            "validation": sum(1 for r in safe_records if r["split"] == "validation"),
            "locked_test": sum(1 for r in safe_records if r["split"] == "locked_test"),
        },
        "locked_ground_truth_exposed": False,
    }


# =============================================================================
# PRODUCTS CATALOGUE ENDPOINTS
# =============================================================================

class ProductCreateRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    aliases: str = ""
    category: str = "general"
    base_unit: str = Field(min_length=1, max_length=20)
    sellable_unit: str = Field(min_length=1, max_length=20)
    supported_conversions: str = ""
    unit_price: float = Field(gt=0)
    low_stock_threshold: int = Field(default=10, ge=0)
    is_active: bool = True


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    aliases: str | None = None
    category: str | None = None
    base_unit: str | None = None
    sellable_unit: str | None = None
    supported_conversions: str | None = None
    unit_price: float | None = Field(None, gt=0)
    low_stock_threshold: int | None = Field(None, ge=0)
    is_active: bool | None = None


@app.get("/api/products")
def list_products(search: str = "", is_active: bool | None = None, limit: int = 100, offset: int = 0):
    """List products with optional search and filters."""
    products = ProductRepository.list_products(search, is_active, limit, offset)
    # Convert prices from minor units to rupees for API response
    for p in products:
        p["unit_price"] = p["unit_price"] / 100.0
    return {"records": products, "count": len(products)}


@app.get("/api/products/{sku}")
def get_product(sku: str):
    product = ProductRepository.get_product(sku)
    if not product:
        raise HTTPException(404, "Product not found")
    # Convert price from minor units to rupees for API response
    product["unit_price"] = product["unit_price"] / 100.0
    return product


@app.post("/api/products")
def create_product(request: ProductCreateRequest):
    try:
        product = ProductRepository.create_product(request.model_dump())
        # Convert price from minor units to rupees for API response
        product["unit_price"] = product["unit_price"] / 100.0
        return product
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/products/{sku}")
def update_product(sku: str, request: ProductUpdateRequest):
    product = ProductRepository.get_product(sku)
    if not product:
        raise HTTPException(404, "Product not found")
    try:
        updated = ProductRepository.update_product(sku, {k: v for k, v in request.model_dump().items() if v is not None})
        # Convert price from minor units to rupees for API response
        updated["unit_price"] = updated["unit_price"] / 100.0
        return updated
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# =============================================================================
# INVENTORY ENDPOINTS
# =============================================================================

class StockAdjustRequest(BaseModel):
    quantity_delta: int = Field(..., description="Positive for incoming, negative for outgoing")
    reason: str = Field(min_length=1, max_length=500)
    reference_id: str | None = None
    reference_type: str | None = None


@app.get("/api/inventory")
def list_inventory(low_stock_only: bool = False, limit: int = 100, offset: int = 0):
    """List inventory levels."""
    return {"records": InventoryRepository.list_inventory(low_stock_only, limit, offset), "count": len(InventoryRepository.list_inventory(low_stock_only))}


@app.get("/api/inventory/{sku}")
def get_inventory(sku: str):
    inventory = InventoryRepository.get_inventory(sku)
    if not inventory:
        raise HTTPException(404, "Inventory record not found")
    return inventory


@app.post("/api/inventory/{sku}/adjust")
def adjust_stock(sku: str, request: StockAdjustRequest):
    """Adjust stock with audit trail."""
    try:
        return InventoryRepository.adjust_stock(
            sku=sku,
            quantity_delta=request.quantity_delta,
            movement_type="manual_adjustment",
            reason=request.reason,
            reference_id=request.reference_id,
            reference_type=request.reference_type
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# =============================================================================
# STOCK MOVEMENTS ENDPOINTS
# =============================================================================

@app.get("/api/stock-movements")
def list_stock_movements(sku: str | None = None, limit: int = 100, offset: int = 0):
    """List stock movement history."""
    return {"records": InventoryRepository.get_stock_movements(sku, limit, offset), "count": len(InventoryRepository.get_stock_movements(sku))}


# =============================================================================
# SHIPMENTS / TRANSPORT ENDPOINTS
# =============================================================================

class ShipmentCreateRequest(BaseModel):
    order_id: str
    transporter_name: str | None = None
    transport_mode: str | None = None
    tracking_reference: str | None = None
    dispatch_date: str | None = None
    expected_delivery_date: str | None = None
    actual_delivery_date: str | None = None
    status: str = "planned"
    freight_cost: float | None = Field(None, ge=0)
    notes: str | None = None


class ShipmentUpdateRequest(BaseModel):
    transporter_name: str | None = None
    transport_mode: str | None = None
    tracking_reference: str | None = None
    dispatch_date: str | None = None
    expected_delivery_date: str | None = None
    actual_delivery_date: str | None = None
    status: str | None = None
    freight_cost: float | None = Field(None, ge=0)
    notes: str | None = None


@app.get("/api/shipments")
def list_shipments(status: str | None = None, order_id: str | None = None, limit: int = 100, offset: int = 0):
    """List shipments with optional filters."""
    shipments = ShipmentRepository.list_shipments(status, order_id, limit, offset)
    # Convert freight costs from minor units to rupees for API response
    for s in shipments:
        if s.get("freight_cost") is not None:
            s["freight_cost"] = s["freight_cost"] / 100.0
    return {"records": shipments, "count": len(shipments)}


@app.get("/api/shipments/{shipment_id}")
def get_shipment(shipment_id: str):
    shipment = ShipmentRepository.get_shipment(shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    # Convert freight cost from minor units to rupees for API response
    if shipment.get("freight_cost") is not None:
        shipment["freight_cost"] = shipment["freight_cost"] / 100.0
    return shipment


@app.post("/api/shipments")
def create_shipment(request: ShipmentCreateRequest):
    try:
        shipment = ShipmentRepository.create_shipment(request.model_dump())
        # Convert freight cost from minor units to rupees for API response
        if shipment.get("freight_cost") is not None:
            shipment["freight_cost"] = shipment["freight_cost"] / 100.0
        return shipment
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/shipments/{shipment_id}")
def update_shipment(shipment_id: str, request: ShipmentUpdateRequest):
    shipment = ShipmentRepository.get_shipment(shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    try:
        updated = ShipmentRepository.update_shipment(shipment_id, {k: v for k, v in request.model_dump().items() if v is not None})
        # Convert freight cost from minor units to rupees for API response
        if updated.get("freight_cost") is not None:
            updated["freight_cost"] = updated["freight_cost"] / 100.0
        return updated
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/shipments/{shipment_id}/dispatch")
def dispatch_shipment(shipment_id: str):
    """Dispatch a shipment - deducts stock and updates status."""
    try:
        shipment = ShipmentRepository.dispatch_shipment(shipment_id)
        # Convert freight cost from minor units to rupees for API response
        if shipment.get("freight_cost") is not None:
            shipment["freight_cost"] = shipment["freight_cost"] / 100.0
        return shipment
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/shipments/{shipment_id}/deliver")
def mark_delivered(shipment_id: str):
    """Mark shipment as delivered."""
    try:
        shipment = ShipmentRepository.mark_delivered(shipment_id)
        # Convert freight cost from minor units to rupees for API response
        if shipment.get("freight_cost") is not None:
            shipment["freight_cost"] = shipment["freight_cost"] / 100.0
        return shipment
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# =============================================================================
# DASHBOARD SUMMARY ENDPOINTS
# =============================================================================

@app.get("/api/dashboard/summary")
def dashboard_summary():
    """Get dashboard summary metrics."""
    inventory = InventoryRepository.list_inventory()
    shipments = ShipmentRepository.list_shipments()
    
    low_stock = [i for i in inventory if i["available_quantity"] <= i["low_stock_threshold"]]
    in_transit = [s for s in shipments if s["status"] == "in_transit"]
    
    # Check if demo mode (synthetic stock) is active
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM stock_movements 
            WHERE movement_type='opening_stock' AND reason LIKE '%demo%'
        """)
        demo_mode = cursor.fetchone()["count"] > 0
    
    return {
        "low_stock_products": len(low_stock),
        "in_transit_shipments": len(in_transit),
        "demo_mode": demo_mode
    }
    
    low_stock_count = sum(1 for inv in inventory if inv["available_quantity"] <= inv["low_stock_threshold"])
    pending_dispatch = sum(1 for s in shipments if s["status"] in ["planned", "ready"])
    in_transit = sum(1 for s in shipments if s["status"] == "in_transit")
    
    # Check for overdue shipments
    from datetime import datetime
    now = datetime.now(timezone.utc)
    overdue = 0
    for s in shipments:
        if s["status"] == "in_transit" and s["expected_delivery_date"]:
            try:
                expected = datetime.fromisoformat(s["expected_delivery_date"])
                if expected < now:
                    overdue += 1
            except:
                pass
    
    return {
        "low_stock_products": low_stock_count,
        "pending_dispatches": pending_dispatch,
        "in_transit_shipments": in_transit,
        "overdue_deliveries": overdue,
        "total_products": len(inventory),
        "total_shipments": len(shipments),
    }

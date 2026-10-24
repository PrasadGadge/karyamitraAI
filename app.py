from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from catalogue import Catalogue
from evaluation import load_evaluation
from evaluation import run as run_evaluation
from evaluation import summary as evaluation_summary
from orders import OrderService

ROOT = Path(__file__).parent
catalogue = Catalogue(ROOT / "data" / "products.csv")
service = OrderService(catalogue)
dataset = json.loads((ROOT / "data" / "sample_orders.json").read_text(encoding="utf-8"))

app = FastAPI(title="KaryaMitra AI", version="0.1.0")
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
        "persistence": "in-memory; orders reset on restart",
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
    return {"dataset": readiness, "baseline": {"status": baseline["status"], "eligible_records": baseline["eligible"], "excluded_unreviewed": baseline["raw_counts"]["excluded_unreviewed"], "metrics": baseline["metrics"], "locked_ground_truth_exposed": False}}


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

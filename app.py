from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from catalogue import Catalogue
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
    return {"status": "ok", "catalogue_records": len(catalogue.products), "dataset_records": len(dataset), "persistence": "in-memory; orders reset on restart"}


@app.get("/api/catalogue")
def get_catalogue():
    return {"records": catalogue.products, "source": "data/products.csv", "synthetic": True}


@app.get("/api/dataset")
def get_dataset():
    return {"records": dataset, "source": "data/sample_orders.json", "synthetic": True}


@app.post("/api/orders/process")
def process_order(request: ProcessRequest):
    return service.process(request.message, request.source_record_id)


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

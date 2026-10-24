"""Complete end-to-end live server and headless browser verification for KaryaMitra AI Phase 3A."""
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8088
BASE_URL = f"http://127.0.0.1:{PORT}"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

def log(msg):
    print(f"[VERIFY] {msg}")

def check(condition, desc):
    if condition:
        print(f"  [PASS] {desc}")
    else:
        print(f"  [FAIL] {desc}")
        sys.exit(1)

def http_get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode('utf-8')

def http_post(path, data=None):
    body = json.dumps(data).encode('utf-8') if data is not None else b""
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method='POST')
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))

def http_post_expect_error(path, data=None):
    body = json.dumps(data).encode('utf-8') if data else b""
    headers = {'Content-Type': 'application/json'} if data else {}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

def run_headless_browser(url, width=1280, height=800):
    import tempfile
    td = tempfile.mkdtemp()
    cmd = [
        EDGE_PATH,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--no-first-run",
        f"--user-data-dir={td}",
        f"--window-size={width},{height}",
        "--dump-dom",
        url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=20)
    return res.stdout

def main():
    log("Starting background Uvicorn server...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(PORT), "--host", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        # Wait for server to come up
        ready = False
        for _ in range(20):
            time.sleep(0.5)
            try:
                status, body = http_get("/api/health")
                if status == 200 and "ok" in body:
                    ready = True
                    break
            except Exception:
                pass

        check(ready, "FastAPI server started and responded on /api/health")

        log("1. Verifying Page Load and Static Assets...")
        status, html = http_get("/")
        check(status == 200, "GET / returns 200")
        check("KaryaMitra AI" in html, "HTML contains brand title 'KaryaMitra AI'")
        check("Dataset Explorer" in html, "HTML contains 'Dataset Explorer' module")
        check("Operational Metrics" in html, "HTML contains 'Operational Metrics' module")

        status, css = http_get("/static/styles.css")
        check(status == 200 and "--color-primary: #0a5444" in css, "CSS loaded with deep emerald theme")

        status, js = http_get("/static/app.js")
        check(status == 200 and "renderOrderResult" in js, "JavaScript loaded with complete controller")

        log("2. Verifying Dataset Explorer and Integrity...")
        status, eval_json_str = http_get("/api/evaluation/records")
        eval_data = json.loads(eval_json_str)
        check(status == 200, "GET /api/evaluation/records returns 200")
        check(eval_data["total"] == 60, "Dataset contains exact 60 total records")
        check(eval_data["split_counts"]["development"] == 36, "Development split has 36 records")
        check(eval_data["split_counts"]["validation"] == 12, "Validation split has 12 records")
        check(eval_data["split_counts"]["locked_test"] == 12, "Locked-test split has 12 records")
        check("expected_items" not in eval_json_str.lower(), "Ground truth 'expected_items' is NEVER exposed")
        check("moon juice" not in eval_json_str.lower(), "Locked test messages like 'moon juice' are protected and not leaked")

        status, summary_json_str = http_get("/api/evaluation/summary")
        summary_data = json.loads(summary_json_str)
        check(summary_data["baseline"]["status"] == "Not evaluated", "Baseline status is honestly 'Not evaluated'")
        check(summary_data["baseline"]["eligible_records"] == 0, "0 eligible records evaluated before human review")

        log("3. Verifying Product Catalogue...")
        status, cat_json_str = http_get("/api/catalogue")
        cat_data = json.loads(cat_json_str)
        check(len(cat_data["records"]) == 6, "Catalogue has 6 products matching products.csv")
        oil = next(p for p in cat_data["records"] if p["sku"] == "SYN-OIL-500")
        check(oil["name"] == "Synthetic 500ml Cooking Oil", "SYN-OIL-500 name matches CSV")
        check(oil["price"] == "82.50", "SYN-OIL-500 price is 82.50")
        check("bottle:1|box:12" in oil["supported_conversions"], "SYN-OIL-500 supported conversions match CSV")

        log("4. Verifying Sample Orders...")
        status, sample_json_str = http_get("/api/dataset")
        sample_data = json.loads(sample_json_str)
        check(len(sample_data["records"]) == 6, "Sample orders has 6 demo records")
        check(sample_data["records"][0]["id"] == "SYN-DEV-001", "First sample is SYN-DEV-001")

        log("5. Testing Order Intake Pipeline (Clear Multi-Item)...")
        status, order1 = http_post("/api/orders/process", {
            "message": "Send 2 box 500ml oil and 5 dozen soap.",
            "source_record_id": "SYN-DEV-001"
        })
        check(status == 200, "Process request returns 200")
        check(order1["state"] == "VERIFIED", "Multi-item clear order state is VERIFIED")
        check(len(order1["lines"]) == 2, "Extracted 2 line items")
        check(order1["lines"][0]["sku"] == "SYN-OIL-500", "Line 1 matched SYN-OIL-500")
        check(order1["lines"][0]["converted_quantity"] == 24, "Line 1 converted 2 boxes -> 24 bottles")
        check(order1["lines"][0]["line_total"] == 1980.0, "Line 1 total is 1980.0 (24 * 82.50)")
        check(order1["lines"][1]["sku"] == "SYN-SOAP-100", "Line 2 matched SYN-SOAP-100")
        check(order1["lines"][1]["converted_quantity"] == 60, "Line 2 converted 5 dozen -> 60 bars")
        check(order1["lines"][1]["line_total"] == 1080.0, "Line 2 total is 1080.0 (60 * 18.00)")
        check(order1["processing_duration_ms"] > 0, f"Actual duration recorded: {order1['processing_duration_ms']} ms")
        check(len(order1["trace"]) >= 4, "Execution trace contains full audit events")

        log("6. Testing Ambiguous Product (Safeguard Gate)...")
        status, ambig_order = http_post("/api/orders/process", {
            "message": "Send 3 classic soap."
        })
        check(ambig_order["state"] == "NEEDS_CLARIFICATION", "Ambiguous order state is NEEDS_CLARIFICATION")
        check(ambig_order["lines"][0]["verified"] is False, "Ambiguous line is not verified")
        check(len(ambig_order["lines"][0]["match_evidence"]) == 2, "Ambiguous line identified 2 competing catalogue matches")

        # Approval gate MUST reject this
        err_code, err_msg = http_post_expect_error(f"/api/orders/{ambig_order['id']}/approve")
        check(err_code == 409, f"Approval gate blocks unverified order with HTTP 409 (Got {err_code})")
        check("Only a verified order with no unresolved mandatory fields can be approved" in err_msg, "Approval gate returns honest safeguard error")

        # Export MUST be blocked
        try:
            http_get(f"/api/orders/{ambig_order['id']}/export")
            check(False, "Exporting unverified order should fail")
        except urllib.error.HTTPError as e:
            check(e.code == 409, "Exporting unverified order blocked with HTTP 409")

        log("7. Testing Unknown Product...")
        status, unknown_order = http_post("/api/orders/process", {
            "message": "Send 4 mystery drink."
        })
        check(unknown_order["state"] == "NEEDS_CLARIFICATION", "Unknown product triggers NEEDS_CLARIFICATION")
        check(unknown_order["lines"][0]["sku"] is None, "Unknown product SKU is None")
        check("No catalogue product matches" in unknown_order["lines"][0]["findings"][0], "Findings record no catalogue match")

        log("8. Testing Human Correction & Reprocessing...")
        status, corrected_order = http_post(f"/api/orders/{ambig_order['id']}/correct", {
            "message": "Send 3 box 500ml oil."
        })
        check(corrected_order["state"] == "VERIFIED", "Corrected order reprocessed to VERIFIED")
        check(corrected_order["correction_count"] == 1, "Correction counter incremented to 1")

        log("9. Testing Human Approval & Export Safeguards...")
        status, approved_order = http_post(f"/api/orders/{order1['id']}/approve")
        check(status == 200, "Approved verified order returns 200")
        check(approved_order["state"] == "APPROVED", "Order state transitioned to APPROVED")

        status, exp_json = http_get(f"/api/orders/{order1['id']}/export?format=json")
        check(status == 200 and "SYN-OIL-500" in exp_json, "Export JSON succeeded with approved lines")

        status, exp_csv = http_get(f"/api/orders/{order1['id']}/export?format=csv")
        check(status == 200 and "SYN-OIL-500,Synthetic 500ml Cooking Oil" in exp_csv, "Export CSV succeeded with approved lines")

        # Cannot reject approved order
        err_code, err_msg = http_post_expect_error(f"/api/orders/{order1['id']}/reject")
        check(err_code == 409, "Rejecting already approved order is forbidden with HTTP 409")

        log("10. Testing Human Rejection on another order...")
        status, rejected_order = http_post(f"/api/orders/{unknown_order['id']}/reject")
        check(status == 200 and rejected_order["state"] == "REJECTED", "Order successfully REJECTED")

        log("11. Verifying Metrics Update...")
        status, metrics_str = http_get("/api/metrics")
        metrics = json.loads(metrics_str)
        check(metrics["orders_processed"] >= 4, f"Orders processed counter updated: {metrics['orders_processed']}")
        check(metrics["approved_orders"] == 1, f"Approved counter is 1: {metrics['approved_orders']}")
        check(metrics["rejected_orders"] == 1, f"Rejected counter is 1: {metrics['rejected_orders']}")
        check(metrics["corrections"] == 1, f"Corrections counter is 1: {metrics['corrections']}")

        log("12. Testing LLM Selection with Safe Unconfigured Fallback...")
        status, llm_order = http_post("/api/orders/process", {
            "message": "Send 1 bottle oil.",
            "extraction_method": "llm"
        })
        check(status == 200, "LLM request returns 200 via fallback")
        check(llm_order["parser"]["requested_method"] == "llm", "Requested method was recorded as 'llm'")
        check(llm_order["parser"]["method"] == "rules", "Actual parser safely fell back to 'rules'")
        check(llm_order["fallback_reason"] is not None and "unavailable" in llm_order["fallback_reason"].lower(), "Fallback reason explicitly records unavailable configuration")
        check(llm_order["state"] == "VERIFIED", "Fallback order verified against catalogue")

        log("13. Testing Headless Edge Browser DOM Rendering (Desktop width: 1280px)...")
        rendered_dom = run_headless_browser(BASE_URL, 1280, 800)
        check("KaryaMitra AI" in rendered_dom, "Browser rendered 'KaryaMitra AI' heading")
        check("Order Intake" in rendered_dom, "Browser rendered 'Order Intake' section")
        check("Dataset Explorer" in rendered_dom, "Browser rendered 'Dataset Explorer' nav tab")
        check("Operational Metrics" in rendered_dom, "Browser rendered 'Operational Metrics' nav tab")
        check("Human Review" in rendered_dom, "Browser rendered 'Human Review' nav tab")
        check("Dataset Transparency &amp; Health Notice" in rendered_dom or "Dataset Transparency" in rendered_dom, "Browser rendered Dataset Health Notice")
        check("record-detail-modal" in rendered_dom, "Browser rendered Record Details modal component")

        log("14. Testing Headless Edge Browser DOM Rendering (Mobile width: 375px)...")
        mobile_dom = run_headless_browser(BASE_URL, 375, 812)
        check("KaryaMitra AI" in mobile_dom, "Mobile view rendered title properly")
        check("workspace-grid" in mobile_dom, "Mobile responsive container active")

        log("ALL BROWSER & API VERIFICATION SUITES PASSED PERFECTLY!")

    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_process.kill()

if __name__ == "__main__":
    main()

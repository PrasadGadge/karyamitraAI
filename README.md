# KaryaMitra AI — Phase 1 Foundation

KaryaMitra AI turns a small set of supported informal order messages into catalogue-grounded draft orders. This is a new, local prototype for PRAGYAN 2K26—not a recovered prior application.

## What is implemented

- FastAPI backend and local static HTML/CSS/JavaScript UI.
- A local CSV catalogue and JSON message dataset, both explicitly labelled **synthetic development data**.
- Deliberately limited rules extraction for tested English and Marathi/Hinglish separator patterns (`and`, `ani`, `pathav`).
- Catalogue matching by SKU, product name, or registered alias; ambiguous and unknown matches remain unresolved.
- Explicit `box`/`dozen` conversion rules, catalogue-only prices, validation, timing, an in-memory audit trace, approval/rejection, and approved-only JSON/CSV export.
- Pytest coverage for extraction, validation, workflow safeguards, and API data paths.

## Architecture

`static UI → FastAPI (app.py) → rules or optional OpenRouter extraction → catalogue.py → orders.py → in-memory result/trace`

The browser only displays results returned by the API; matching and validation run in Python. Data is loaded from `data/products.csv` and `data/sample_orders.json` at application startup. Orders are intentionally in memory, so they disappear when the server restarts.

## Run on Windows PowerShell

```powershell
cd "C:\Users\ACER\OneDrive\Desktop\KaryaMitra AI"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# Stable standard server (no automatic reload)
python -m uvicorn app:app
# Recommended Windows development server (source reload; .venv and evaluation_runs excluded)
python run_dev.py
```

Open `http://127.0.0.1:8000`. The interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Optional LLM extraction

Rules-based extraction is the default and remains fully usable without LLM configuration. To enable OpenRouter extraction, copy `.env.example` to `.env` and set both `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; never commit `.env`. Select **LLM-based parser** in the Order Workspace. The backend masks confidently identified labelled customer names, supported phone numbers, and email addresses before making an external request, then passes the proposal through the same catalogue validation and human approval safeguards as the rules parser.

Masking is risk reduction, not a guarantee of anonymity: free-form text can contain identifiers the conservative detector does not recognise. Do not send sensitive customer information unless external processing is authorised. LLM output cannot supply authoritative prices, SKUs, inventory, pack definitions, or approval decisions. If configuration is absent or the provider fails, the UI reports the reason and uses the rules parser instead.

## API endpoints

- `GET /api/health`, `/api/catalogue`, `/api/dataset`, `/api/metrics`
- `POST /api/orders/process`
- `GET /api/orders/{order_id}`
- `POST /api/orders/{order_id}/correct`, `/approve`, `/reject`
- `GET /api/orders/{order_id}/export?format=json|csv`

Example request:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/orders/process -ContentType application/json -Body '{"message":"Send 2 box 500ml oil and 5 dozen soap.","source_record_id":"SYN-DEV-001"}'
```

## Limits and planned work

The catalogue and messages are fictional development data, not customer data or price data. There is no LLM, external API, WhatsApp/OCR/voice integration, persistent storage, real distributor validation, or ROI claim. The parser must not be treated as support for arbitrary Marathi/Hinglish.

## Phase 2 evaluation readiness

`data/evaluation/` contains a versioned, 60-record synthetic corpus: 36 development, 12 validation, and 12 locked-test records. The frozen locked-test messages and separate ground-truth annotations are SHA-256 protected by `manifest.json`. The application never serves either locked file or its expected answers; `/api/evaluation/summary` exposes aggregate readiness only.

Every candidate annotation is currently `pending_review`, because no independent human reviewer has verified the coding agent's candidate labels. The rules baseline is therefore honestly **Not evaluated** for accuracy: unreviewed records are excluded from verified denominators. Generate a machine-readable, ignored run record with:

```powershell
.\.venv\Scripts\python.exe evaluation.py
```

Before Phase 3, a separate teammate must review or adjudicate each intended evaluation label without tuning the parser to the locked test set.

## Phase 2.5: independent human review

Create a blind packet containing all 60 synthetic messages, the catalogue, empty annotation fields, and a review protocol. It deliberately excludes candidate labels, parser/LLM output, and scores.

```powershell
.\.venv\Scripts\python.exe review_workflow.py build-packet
```

Give `data/review_packets/phase2_5_v1/` to a separate teammate. They edit a copy of `blind_review_template.json`, fill their reviewer ID and annotations, and save it outside the project as `completed_review.json`. Import it only after a human has actually completed the review:

```powershell
.\.venv\Scripts\python.exe review_workflow.py import C:\path\to\completed_review.json
```

The importer rejects unknown or duplicate IDs, unknown SKUs, invalid units, unsupported normalized conversions, missing required fields, incomplete packets, and packets with no completed review. It writes a new, ignored versioned human artifact and a disagreement report. It never overwrites candidate annotations or automatically resolves a disagreement.

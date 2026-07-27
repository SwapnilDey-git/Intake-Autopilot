from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import databases
import json
import logging
import math
import os
import re
import shutil
import unicodedata
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")

# Connects to the docker postgres instance; override via env var outside docker-compose
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://admin:password@postgres:5432/intake")
database = databases.Database(DATABASE_URL)

app = FastAPI(title="Intake Backend API")

# --- Excel write-up (dev spec Sec.9: "Clients/{Surname}_{Firstname}_{TaxYear}/EA_{year}.xlsx") ---
CLIENTS_DIR = Path(os.environ.get("CLIENTS_DIR", "/storage/Clients"))
EXCEL_TEMPLATE_PATH = Path(os.environ.get("EXCEL_TEMPLATE_PATH", "/app/templates/EA_2025_template.xlsx"))

# Flat drop directory ai-service saves every original upload into (see ai-service/main.py's
# STORAGE_DIR) -- same bind mount, same env var name, so a source file for form_id lives at
# STORAGE_DIR / forms.filename regardless of which of the three intake paths produced it.
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/storage"))

# Filenames arriving at ai-service are inconsistent across intake paths -- real names for
# dashboard/Gmail uploads, extensionless UUIDs for n8n's raw-binary webhook path -- so the
# filed copy's extension is sniffed from magic bytes rather than trusted from the name.
def sniff_extension(content: bytes) -> str:
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return ".bin"

# Field -> cell mapping from Phase1_Developer_Specification.md.pdf Sec.8 ("Data model"),
# which describes it as "confirmed against the supplied sheet" -- but the client never
# actually handed that sheet into this repo, so this map is a best-effort reconstruction
# from the spec's prose table, not verified against the real file. Two known-uncertain
# spots: svs_sva (spec text says "B11/D11", ambiguous which is the value cell -- using
# D11 literally per the text) and A25 (spec lists it as a target with no corresponding
# source field on our intake form -- left unmapped). Re-check every cell here against
# the client's real EA_2025.xlsx before relying on this in production; swap the file at
# EXCEL_TEMPLATE_PATH for the real one first.
EXCEL_CELL_MAP = {
    "tax_year": "B1",
    "e_card_number": "B4",
    "honorare": "C9",              # Leistungserloese
    "svs_sva": "D11",              # Sozialversicherung 9225
    "provision_travel": "C13",     # Provisionen 9190
    "wko_contribution": "C15",     # part of Sonstiger Aufwand 9230
    "marital_status": "A23",
    "children": "A24",
}
REISEKOSTEN_CELL = "C16"  # Reisekosten 9160 -- computed, not a raw extracted field

UNMAPPED_VALUES = {None, "", "Unknown", "Not Found"}

# --- Completeness check (wayfinder ticket 21) -------------------------------
# Automated pass/fail: is a submission missing any field a filing genuinely needs?
# Decided 2026-07-23 (grilling): identity + signature are hard requirements, plus
# the money fields that are rarely legitimately zero for a real filing client.
# provision_travel is deliberately OPTIONAL -- it is genuinely often zero (many
# carers don't travel), so requiring it would false-flag every no-travel form and
# train reviewers to ignore the badge. Shipped as a constant so the client's real
# "must-have" answer swaps in one line later; wayfinder ticket 22 (auto-follow-up)
# will consume exactly this missing_fields list. This is a WARNING signal, never a
# hard gate -- a reviewer may still approve an incomplete form (e.g. chasing a
# signature separately); the verdict is recorded to audit_log at review time.
MANDATORY_FIELDS = [
    "tax_year", "e_card_number", "name",
    "honorare", "svs_sva", "wko_contribution",
    "is_signed",
]

def _field_is_present(field_key: str, value) -> bool:
    # "Blank" reuses UNMAPPED_VALUES so completeness and the Excel writer agree on
    # what counts as no-value. A blank money field is genuinely ambiguous (real zero
    # vs. omission) and can't be resolved from extraction -- flagging it is
    # deliberately conservative, and a human confirms.
    if field_key == "is_signed":
        # Boolean gate: an unsigned form (false / "no" / absent) is incomplete.
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "yes", "1", "signed"}
    if isinstance(value, str):
        return value.strip() not in UNMAPPED_VALUES
    return value not in UNMAPPED_VALUES

def evaluate_completeness(fields: dict) -> dict:
    """Pure pass/fail over MANDATORY_FIELDS. Returns the verdict plus the named
    missing fields so the dashboard can show them and ticket 22 can later ask the
    client for exactly those."""
    fields = fields or {}
    missing = [k for k in MANDATORY_FIELDS if not _field_is_present(k, fields.get(k))]
    return {"is_complete": not missing, "missing_fields": missing, "mandatory_fields": MANDATORY_FIELDS}

# Straight-line (haversine) distance x a circuity constant approximates real
# road distance closely enough for a reimbursement calc -- see
# .scratch/phase1-next-steps/research/05-geocoding-routing.md for the full
# justification for skipping OSRM/real routing entirely. 1.25 sits in the
# middle of the researched 1.2-1.3 range and is accepted without
# pre-validation per that ticket's decision.
TRAVEL_CIRCUITY_FACTOR = 1.25
EARTH_RADIUS_KM = 6371.0


def normalize_address_text(value) -> str:
    """address_geocode.address_text is matched verbatim (case/whitespace-
    insensitive) -- this is the single normalization applied on both the
    write side (manual inserts) and the read side (lookup), so they agree.
    Rows extracted before ai-service's coerce_field_value fix may still carry
    a raw dict here instead of a flat string -- treated as unmatchable rather
    than crashing, same as a missing field."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


async def compute_travel_suggestion(home_address: str, address_austria: str) -> dict:
    """Looks up both addresses in address_geocode and, if both are known,
    returns a suggested travel_distance_km (haversine x circuity). Returns
    which address(es) are missing from the lookup table otherwise, so the
    dashboard can tell the reviewer why no suggestion was made (falls back
    to the existing fully-manual entry in that case)."""
    home_norm = normalize_address_text(home_address)
    austria_norm = normalize_address_text(address_austria)
    missing = []
    if not home_norm:
        missing.append("home_address")
    if not austria_norm:
        missing.append("address_austria")
    if missing:
        return {"distance_km": None, "missing_addresses": missing}

    if not database.is_connected:
        return {"distance_km": None, "missing_addresses": ["home_address", "address_austria"]}

    rows = await database.fetch_all(
        "SELECT address_text, lat, lon FROM address_geocode WHERE address_text IN (:home, :austria)",
        {"home": home_norm, "austria": austria_norm},
    )
    by_address = {r["address_text"]: r for r in rows}
    home_row = by_address.get(home_norm)
    austria_row = by_address.get(austria_norm)

    if home_row is None:
        missing.append("home_address")
    if austria_row is None:
        missing.append("address_austria")
    if missing:
        return {"distance_km": None, "missing_addresses": missing}

    distance_km = haversine_km(home_row["lat"], home_row["lon"], austria_row["lat"], austria_row["lon"])
    return {"distance_km": round(distance_km * TRAVEL_CIRCUITY_FACTOR, 1), "missing_addresses": []}


def sanitize_path_component(value: str) -> str:
    """Strip diacritics/separators for filesystem paths, per dev spec Sec.9
    ("Sanitise names ... keep the original in-sheet")."""
    value = unicodedata.normalize("NFKD", (value or "").strip())
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\-]+", "", value)
    return value or "Unknown"


def build_client_folder_name(full_name: str, tax_year: str) -> str:
    """Build a filesystem-safe client folder from the single free-text 'name'
    field, preserving the name in the order the writer wrote it.

    We deliberately do NOT split into firstname/surname. The form captures name
    as one free-text field, and the literal-extraction prompt in ai-service now
    transcribes it verbatim -- which on these forms is frequently surname-first
    (e.g. "Ray Arnab" for a person named Arnab Ray). The previous
    firstname-then-surname split therefore produced a swapped Surname_Firstname
    ("Arnab_Ray") whenever the form was filled surname-first, and word order
    cannot be recovered from a single free-text token. Keeping the name as
    written is the only assumption-free option: each whitespace token is
    sanitized (sanitize_path_component strips spaces, so join explicitly) and
    joined with underscores, preserving original order."""
    tax_year_clean = sanitize_path_component(tax_year)
    parts = [sanitize_path_component(p) for p in (full_name or "").strip().split()]
    parts = [p for p in parts if p and p != "Unknown"]
    if parts:
        return f"{'_'.join(parts)}_{tax_year_clean}"
    return f"Unknown_{tax_year_clean}"

# Only the dashboard dev server needs to call this API. `next dev` falls back to
# the next free port (3001, 3002, ...) whenever 3000 is already taken by another
# project on the machine, so a fixed allow_origins entry silently breaks CORS the
# moment that happens -- match any localhost port instead.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    try:
        await database.connect()
    except Exception as e:
        logger.warning(
            "=" * 60 + "\n"
            "DATABASE CONNECTION FAILED - running in MOCK MODE.\n"
            f"Reason: {e}\n"
            "All /api/forms/pending results are FAKE placeholder data\n"
            "until Postgres is reachable and the service is restarted.\n"
            + "=" * 60
        )

    # Per dev spec Sec.9, approvals write into a per-client copy of the EA_2025.xlsx
    # template (Clients/{Surname}_{Firstname}_{TaxYear}/EA_{year}.xlsx), not one shared
    # flat sheet -- see EXCEL_CELL_MAP above for the field->cell mapping and its caveats.
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not EXCEL_TEMPLATE_PATH.exists():
        logger.warning(
            f"Excel template not found at {EXCEL_TEMPLATE_PATH} — approvals will fail "
            "to write until a template (even the placeholder in backend/templates/) is present."
        )

@app.on_event("shutdown")
async def shutdown():
    if database.is_connected:
        await database.disconnect()

@app.get("/api/forms/pending")
async def get_pending_forms():
    if database.is_connected:
        query = """
            SELECT f.id, f.filename, f.status, e.json_result, e.confidence
            FROM forms f
            LEFT JOIN extractions e ON f.id = e.form_id
            WHERE f.status != 'approved' AND f.status != 'rejected'
        """
        results = await database.fetch_all(query=query)
        # An empty list is a legitimate "queue is empty" answer, not a signal
        # to fall back to mock data — only a real disconnect should do that.
        forms = [dict(r) for r in results]
        for form in forms:
            parsed = form.get("json_result")
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    parsed = None
            if isinstance(parsed, dict):
                form["travel_suggestion"] = await compute_travel_suggestion(
                    parsed.get("home_address", ""), parsed.get("address_austria", "")
                )
            else:
                form["travel_suggestion"] = {"distance_km": None, "missing_addresses": ["home_address", "address_austria"]}
            # Completeness verdict on the extracted values (ticket 21). The dashboard
            # recomputes this live as the reviewer edits, using this payload's
            # mandatory_fields list -- so the list has one source of truth (here) while
            # the badge still clears the moment a reviewer fills a blank.
            form["completeness"] = evaluate_completeness(parsed if isinstance(parsed, dict) else {})
        return forms

    logger.warning("Serving MOCK pending-forms data — database is not connected.")
    return [{
        "id": 1,
        "filename": "form1.pdf",
        "status": "extracted",
        "json_result": '{"name": "Ana Maria", "address": "Romania", "income": "25000"}',
        "confidence": None,
        "_mock": True
    }]

class NewFormExtraction(BaseModel):
    filename: str
    status: str  # "extracted" or "failed"
    fields: dict | None = None
    confidence: dict | None = None
    error: str | None = None

@app.post("/api/forms")
async def create_form(payload: NewFormExtraction):
    """Persists a manual dashboard upload's extraction result (or failure)
    to Postgres. Without this, forms created via the dashboard's own upload
    button only ever existed in browser state — never in the DB — so
    idempotency/audit-log/review couldn't see them at all."""
    if not database.is_connected:
        return {"success": True, "mock": True, "id": None, "message": "Simulated create (mock mode)."}

    try:
        form_row = await database.fetch_one(
            "INSERT INTO forms (filename, status) VALUES (:filename, :status) RETURNING id",
            {"filename": payload.filename, "status": payload.status},
        )
        form_id = form_row["id"]

        if payload.status == "extracted":
            await database.execute(
                "INSERT INTO extractions (form_id, json_result, confidence) VALUES (:form_id, :json_result, :confidence)",
                {
                    "form_id": form_id,
                    "json_result": json.dumps(payload.fields or {}),
                    "confidence": json.dumps(payload.confidence or {}),
                },
            )
            await database.execute(
                "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'extraction', 'dashboard', :details)",
                {"form_id": form_id, "details": json.dumps({"fields": payload.fields, "confidence": payload.confidence})},
            )
        else:
            await database.execute(
                "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'extraction_failed', 'dashboard', :details)",
                {"form_id": form_id, "details": json.dumps({"error": payload.error})},
            )

        return {"success": True, "id": form_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

class ReviewUpdate(BaseModel):
    approved: bool
    updated_data: dict
    reviewer_name: str

# Reisekosten = distance(home -> Vienna) x 2 (round trip) x rate x trips,
# capped at EUR 6,000 (Kennzahl 9160). Distance/trips are reviewer-entered
# for now (no self-hosted geocoding/routing stood up yet).
TRAVEL_RATE_EUR_PER_KM = 0.42
TRAVEL_ROUND_TRIP_FACTOR = 2
TRAVEL_CAP_EUR = 6000

@app.post("/api/forms/{form_id}/review")
async def submit_review(form_id: int, review: ReviewUpdate):
    if not review.reviewer_name or not review.reviewer_name.strip():
        return {"success": False, "error": "reviewer_name is required"}

    if not database.is_connected:
        return {"success": True, "mock": True, "message": "Simulated approval success."}

    try:
        d = review.updated_data
        e_card_number = (d.get("e_card_number") or "").strip() or None
        tax_year = (d.get("tax_year") or "").strip() or None

        if review.approved and e_card_number and tax_year:
            duplicate = await database.fetch_one(
                """
                SELECT id FROM forms
                WHERE status = 'approved' AND e_card_number = :e AND tax_year = :t AND id != :form_id
                """,
                {"e": e_card_number, "t": tax_year, "form_id": form_id},
            )
            if duplicate:
                await database.execute(
                    "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'duplicate_blocked', :actor, :details)",
                    {
                        "form_id": form_id,
                        "actor": review.reviewer_name,
                        "details": json.dumps({
                            "conflicting_form_id": duplicate["id"],
                            "e_card_number": e_card_number,
                            "tax_year": tax_year,
                        }),
                    },
                )
                return {
                    "success": False,
                    "reason": "duplicate",
                    "message": f"A form for e-card {e_card_number} / tax year {tax_year} is already approved "
                                f"(form #{duplicate['id']}). Resolve manually before re-approving this one.",
                    "conflicting_form_id": duplicate["id"],
                }

        query = "INSERT INTO reviews (form_id, approved, updated_data, reviewer_name) VALUES (:form_id, :approved, :updated_data, :reviewer_name)"
        values = {
            "form_id": form_id,
            "approved": review.approved,
            "updated_data": json.dumps(d),
            "reviewer_name": review.reviewer_name,
        }
        await database.execute(query=query, values=values)

        status = "approved" if review.approved else "rejected"
        await database.execute(
            "UPDATE forms SET status = :status, e_card_number = :e, tax_year = :t WHERE id = :form_id",
            {"status": status, "e": e_card_number, "t": tax_year, "form_id": form_id},
        )
        await database.execute(
            "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, :event_type, :actor, :details)",
            {
                "form_id": form_id,
                "event_type": "approval" if review.approved else "rejection",
                "actor": review.reviewer_name,
                "details": json.dumps(d),
            },
        )

        # Record the completeness verdict on the reviewer's CURRENT values (not the
        # original extraction) -- so filling a blank in the dashboard before approving
        # is reflected, and the audit trail shows whether an incomplete form was
        # knowingly approved. Warning only; never blocks the approval above.
        completeness = evaluate_completeness(d)
        await database.execute(
            "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'completeness', :actor, :details)",
            {
                "form_id": form_id,
                "actor": review.reviewer_name,
                "details": json.dumps(completeness),
            },
        )

        reisekosten = None
        if review.approved:
            try:
                distance_km = float(d.get("travel_distance_km") or 0)
                trip_count = float(d.get("trip_count") or 0)
                reisekosten = round(
                    min(distance_km * TRAVEL_ROUND_TRIP_FACTOR * TRAVEL_RATE_EUR_PER_KM * trip_count, TRAVEL_CAP_EUR),
                    2,
                )
            except (TypeError, ValueError):
                reisekosten = None

            if not EXCEL_TEMPLATE_PATH.exists():
                raise RuntimeError(
                    f"Excel template missing at {EXCEL_TEMPLATE_PATH} — cannot write approval."
                )

            client_folder_name = build_client_folder_name(d.get("name", ""), tax_year or "")
            client_dir = CLIENTS_DIR / client_folder_name
            client_dir.mkdir(parents=True, exist_ok=True)
            year_component = sanitize_path_component(tax_year or "UnknownYear")
            client_xlsx_path = client_dir / f"EA_{year_component}.xlsx"

            if not client_xlsx_path.exists():
                shutil.copy(EXCEL_TEMPLATE_PATH, client_xlsx_path)

            from openpyxl import load_workbook
            wb = load_workbook(client_xlsx_path)
            ws = wb.active
            for field_key, cell_ref in EXCEL_CELL_MAP.items():
                value = d.get(field_key)
                if value not in UNMAPPED_VALUES:
                    ws[cell_ref] = value
            if reisekosten is not None:
                ws[REISEKOSTEN_CELL] = reisekosten
            wb.save(client_xlsx_path)

            excel_path = str(client_xlsx_path)
            await database.execute(
                "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'write', :actor, :details)",
                {
                    "form_id": form_id,
                    "actor": review.reviewer_name,
                    "details": json.dumps({"excel_path": excel_path, "reisekosten": reisekosten}),
                },
            )

            # File the original upload alongside the Excel output. Best-effort: a missing
            # source file (e.g. it predates STORAGE_DIR, or was cleaned up) shouldn't block
            # an otherwise-successful approval that already wrote the Excel file above.
            form_row = await database.fetch_one(
                "SELECT filename FROM forms WHERE id = :form_id", {"form_id": form_id}
            )
            source_filename = form_row["filename"] if form_row else None
            if source_filename:
                source_path = STORAGE_DIR / source_filename
                if source_path.exists():
                    content = source_path.read_bytes()
                    original_path = client_dir / f"original_intake{sniff_extension(content)}"
                    shutil.copy(source_path, original_path)
                    await database.execute(
                        "INSERT INTO audit_log (form_id, event_type, actor, details) VALUES (:form_id, 'file', :actor, :details)",
                        {
                            "form_id": form_id,
                            "actor": review.reviewer_name,
                            "details": json.dumps({"original_path": str(original_path)}),
                        },
                    )
                else:
                    logger.warning(f"Source upload missing for form {form_id} at {source_path} — skipping file-filing.")

        return {
            "success": True,
            "status": status,
            "reisekosten": reisekosten,
            "excel_path": excel_path if review.approved else None,
            "completeness": completeness,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

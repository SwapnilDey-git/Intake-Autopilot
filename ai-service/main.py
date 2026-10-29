from fastapi import FastAPI, UploadFile, File, Request
import uvicorn
import shutil
import os
import json
import logging
import time
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import ollama

logger = logging.getLogger("uvicorn.error")

MODEL_RETRY_BACKOFF_SECONDS = [2, 5, 10]  # 3 attempts total

app = FastAPI(title="Intake AI Extraction Service (Airgapped)")

# `next dev` falls back to the next free port whenever 3000 is already taken by
# another project on the machine, so a fixed allow_origins entry silently breaks
# CORS the moment that happens -- match any localhost port instead.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default matches the container's mounted shared volume; overridable via env so the
# service can also run standalone (e.g. the eval harness pointing at native Ollama),
# where "/storage" is a read-only root path that can't be created.
STORAGE_DIR = os.environ.get("STORAGE_DIR", "/storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

MODEL_NAME = os.environ.get("MODEL_NAME", "llava")
# Real intake forms are multi-page scans. At 300 DPI a 3-4 page E1/E1a rasterises to
# ~37k image tokens, over qwen2.5vl's default 32768 window. Two levers:
#   * RENDER_DPI  -- lower DPI = far fewer image tokens (tokens scale ~DPI^2). 200 DPI
#     keeps printed+handwritten tax forms legible while cutting tokens ~2.2x, so most
#     forms fit the window AND infer fast. This is the primary lever.
#   * MODEL_NUM_CTX -- modest headroom above default for the occasional larger scan.
# NOTE: pushing num_ctx very high (e.g. 65536) does NOT help -- it makes every
# inference so slow that multi-page forms hit the backend's 900s timeout and fail
# with ZERO output, which is worse for accuracy than a smaller, legible-but-fast page.
RENDER_DPI = int(os.environ.get("RENDER_DPI", "200"))
MODEL_NUM_CTX = int(os.environ.get("MODEL_NUM_CTX", "40960"))
# ollama.Client() defaults to timeout=None (infinite). A single hung/stalled
# Ollama call (seen in practice under host memory pressure) then blocks its
# worker thread forever, which never releases INFERENCE_SEMAPHORE below --
# permanently wedging every subsequent request behind it with no error, no
# CPU usage, and no way to recover short of restarting this container. Bound
# it well under the backend's own 900s AI_EXTRACT_TIMEOUT_S so a stuck call
# fails and retries (or surfaces as extraction_failed) instead of hanging.
client = ollama.Client(timeout=200)

# --- Bounded inference concurrency (wayfinder ticket 17) --------------------
# ai-service used to serialize inference BY ACCIDENT: the async /extract route
# called the SYNC ollama client directly, so a single blocking call froze the whole
# event loop for the entire inference (4-9 min on the old CPU box; ~8.5s on the Mac's
# native Ollama/Metal). That accidental full-serialization was also the only thing
# keeping two inferences from ever contending for memory at once.
#
# We now run the blocking call off the loop via asyncio.to_thread (so health checks
# and other requests stay responsive during inference) AND cap true concurrency with
# this semaphore -- the EXPLICIT replacement for the mutex the serialization used to
# provide. Default 2 concurrent on a 32GB Mac (qwen2.5vl:7b ~6-8GB weights + per-
# request KV/image context; 2 is comfortable, 3-4 pushes the ceiling with big vision
# inputs). Set AI_MAX_CONCURRENCY=1 to restore strict one-at-a-time.
#
# NOTE: realizing *actual* parallel throughput also needs native Ollama's own
# OLLAMA_NUM_PARALLEL >= AI_MAX_CONCURRENCY. That is a GLOBAL host setting shared with
# every other project's Ollama on this Mac, so it's left to the operator (see
# RUNNING.md) rather than forced here. If it's lower, requests past that limit queue
# INSIDE Ollama -- still correct, just serialized there instead of here.
AI_MAX_CONCURRENCY = int(os.environ.get("AI_MAX_CONCURRENCY", "2"))
INFERENCE_SEMAPHORE = asyncio.Semaphore(AI_MAX_CONCURRENCY)

import pillow_heif
pillow_heif.register_heif_opener()  # lets PIL.Image.open() read HEIC/HEIF, which PyMuPDF can't

def coerce_field_value(value):
    """The model is asked for flat strings but doesn't reliably deliver them --
    it sometimes nests a field as {"value": ..., "_confidence": ...} (echoing the
    per-field confidence format even though only the top-level object should
    carry that), sometimes as a structured address-like object ({"street":
    ..., "city": ...}), or as a partial object with no usable value at all.
    Returning any of those shapes as-is would ship a raw dict as far as the
    dashboard, which can't render an object as a React child -- and every other
    consumer of this endpoint (n8n, a future channel) would have to reimplement
    the same recovery logic. Normalize once, here, so /extract's contract is
    always a flat string or bool no matter what the model does internally."""
    if isinstance(value, dict):
        nested = value.get("value")
        if isinstance(nested, (str, int, float, bool)):
            return nested
        address_parts = [value.get(k) for k in ("street", "city", "state", "country")]
        address_parts = [p for p in address_parts if isinstance(p, str) and p]
        if address_parts:
            return ", ".join(address_parts)
        # Some vision models (notably qwen2.5vl) don't return a flat scalar for
        # each field's value -- they wrap it in a single-/multi-key object that
        # semantically names the datum, e.g. {"year": 2026}, {"amount": "€250/-"},
        # {"number": "210..."} or {"surname": "Ghosh", "first_name": "Anil"}. The
        # street/city branch above only catches the address-shaped variant; for
        # every other shape we'd otherwise drop a perfectly-read value as "Unknown"
        # (this silently cost ~9 of 12 fields with qwen2.5vl). Flatten any object
        # whose values are scalars by joining them, preserving field order.
        scalar_parts = [v for v in value.values() if isinstance(v, (str, int, float, bool))]
        if scalar_parts:
            return " ".join(str(v) for v in scalar_parts)
        return "Unknown"
    if isinstance(value, list):
        return "Unknown"
    return value

def coerce_bool_value(value):
    """is_signed goes through the same nesting problems as every other field
    (e.g. {"value": true, "_confidence": 1}) but coerce_field_value's "Unknown"
    fallback is wrong for a boolean -- unwrap the same way, then collapse
    whatever comes out to an actual bool instead of a sentinel string."""
    unwrapped = coerce_field_value(value)
    if isinstance(unwrapped, bool):
        return unwrapped
    if isinstance(unwrapped, str):
        return unwrapped.strip().lower() in ("true", "yes", "1")
    return bool(unwrapped) if isinstance(unwrapped, (int, float)) else False

import re
_BARE_10_DIGIT_RE = re.compile(r"^\d{10}$")

def _reject_svnr_shaped_stnr(key: str, value):
    """A 'stnr' reading that's exactly 10 bare digits with no separator is
    indistinguishable from an SVNR/e-card number -- the Austrian Steuernummer is
    conventionally printed with a Finanzamt-code/body separator (e.g. '12 345/
    6789'), never as one unbroken 10-digit run. Confirmed on a real E1 (both the
    deterministic AcroForm lane and this text lane independently mis-read the
    SVNR as the Steuernummer on different documents; temperature=0 means a retry
    reproduces the same wrong read rather than correcting it, so this has to be
    caught here, not hoped away by re-running). backend/extractors.py's
    deterministic lane carries the equivalent guard already -- this mirrors it
    for the text/vision lanes, which have no format validation of their own.
    Downgrades to 'Not Found' rather than raising an error so a genuinely better
    candidate elsewhere in the merge (or a human) can still supply the real
    value."""
    if not isinstance(value, str):
        return value
    if key == "e_card_number":
        digits = re.sub(r"\D", "", value)
        return value if len(digits) == 10 else ("Not Found" if digits else value)
    if key != "stnr":
        return value
    if _BARE_10_DIGIT_RE.match(re.sub(r"\s", "", value)):
        return "Not Found"
    # The stnr hint used to show '12 345/6789' as an example and the model copied
    # it verbatim off a scan with no readable StNr.
    if re.sub(r"\D", "", value) == "123456789":
        return "Not Found"
    return value


# Two tokenizations, unioned: "10 136,00" needs space-grouping, but "9230 904,80"
# (Kennzahl then amount) must NOT be fused -- a superset is fine for grounding.
_NUM_TOKEN_RES = (re.compile(r"-?\d[\d.,]*\d|\d"), re.compile(r"-?\d(?:[\d.,]|\s(?=\d{3}\b))*\d|\d"))

_KENNZAHL_CODES = {9040, 9050, 9100, 9110, 9120, 9130, 9134, 9140, 9150, 9160, 9170,
                   9180, 9190, 9200, 9210, 9220, 9221, 9225, 9227, 9228, 9229, 9230,
                   9233, 9243, 9258}

_EXPENSE_FIELDS = ("svs_sva", "kleinmaterial", "provisionen", "abschreibung", "sonstiger_aufwand")


def _money(v):
    if not isinstance(v, str):
        return None
    s = re.sub(r"[^\d,.\-]", "", v)
    if not s or not re.search(r"\d", s):
        return None
    neg = s.startswith("-")
    s = s.lstrip("-")
    # Models emit "1.234,56", "1,234.56" and even "1,234,56" -- a 2-digit tail
    # after the LAST separator is the decimal part; every other separator groups.
    m = re.match(r"^(.*)[.,](\d{2})$", s)
    whole, frac = (m.group(1), m.group(2)) if m else (s, "0")
    whole = re.sub(r"[.,]", "", whole) or "0"
    try:
        n = float(f"{whole}.{frac}")
    except ValueError:
        return None
    return -n if neg else n


def _reject_duplicate_money(fields: dict) -> dict:
    """Vision reads of blank Kennzahl rows tend to borrow another row's figure
    (seen on a scanned E1a: SV came back as the income figure, blank lines as the
    expense sum). An expense equal to the income, to another expense, or to the
    sum of the other expenses can't be trusted -- downgrade it to Not Found so the
    reviewer fills it rather than the sheet silently double-counting."""
    nums = {k: _money(fields.get(k)) for k in ("honorare",) + _EXPENSE_FIELDS}
    bad = set()
    # A figure equal to a Kennzahl code is the row's printed code, not its amount.
    for k, v in nums.items():
        if v is not None and v == int(v) and int(v) in _KENNZAHL_CODES:
            bad.add(k)
            nums[k] = None
    for k in _EXPENSE_FIELDS:
        v = nums[k]
        if v is None or v == 0:
            continue
        others = [nums[o] for o in _EXPENSE_FIELDS if o != k and nums[o]]
        if v < 0:
            bad.add(k)
        elif nums["honorare"] is not None and abs(v - nums["honorare"]) < 0.01:
            bad.add(k)
        elif any(abs(v - o) < 0.01 for o in others):
            bad.add(k)
        elif len(others) >= 2 and abs(v - sum(others)) < 0.01:
            bad.add(k)
    for k in bad:
        fields[k] = "Not Found"
    return fields

def call_model_with_retry(messages):
    """Retries the Ollama call with backoff — the model/container can be
    mid-restart or still cold-loading, which is transient, not a real failure."""
    last_error = None
    for attempt, backoff in enumerate([0] + MODEL_RETRY_BACKOFF_SECONDS):
        if backoff:
            time.sleep(backoff)
        try:
            return client.chat(
                model=MODEL_NAME,
                messages=messages,
                format='json',
                options={"temperature": 0, "seed": 42, "num_ctx": MODEL_NUM_CTX},
            )
        except Exception as e:
            last_error = e
            logger.warning(
                f"Ollama call failed (attempt {attempt + 1}/{1 + len(MODEL_RETRY_BACKOFF_SECONDS)}): {e}"
            )
    raise last_error


async def call_model_bounded(messages):
    """Async wrapper for call_model_with_retry: runs the blocking Ollama call in a
    worker thread (asyncio.to_thread) so it never freezes the event loop, gated by
    INFERENCE_SEMAPHORE so at most AI_MAX_CONCURRENCY inferences run at once. The
    shared ollama.Client wraps a thread-safe httpx.Client, so concurrent .chat calls
    from the thread pool are safe. See the AI_MAX_CONCURRENCY note above (ticket 17)."""
    async with INFERENCE_SEMAPHORE:
        return await asyncio.to_thread(call_model_with_retry, messages)

@app.on_event("startup")
def startup_event():
    try:
        print(f"Checking for airgapped local model: {MODEL_NAME}...")
        client.pull(MODEL_NAME)
        print(f"Model {MODEL_NAME} is ready for local offline inference.")
    except Exception as e:
        print(f"Warning: Could not communicate with Ollama container: {e}")

@app.post("/extract")
async def extract_document(request: Request):
    content_type = request.headers.get("content-type", "")
    
    doc_type = ""
    if "application/json" in content_type:
        data = await request.json()
        filename = data.get("filename", "n8n_upload.pdf")
        doc_type = data.get("doc_type") or ""
        file_base64 = data.get("file_base64")
        if not file_base64:
            return {"error": "Missing file_base64 in JSON payload."}
            
        # Strip potential data URI prefix (e.g. "data:application/pdf;base64,...")
        if "," in file_base64:
            file_base64 = file_base64.split(",")[1]
            
        import base64
        content = base64.b64decode(file_base64)
    elif "multipart/form-data" in content_type:
        form = await request.form()
        upload_file = form.get("file") or form.get("data")
        if not upload_file:
            return {"error": "Missing file payload. Please send either 'file' or 'data'."}
        content = await upload_file.read()
        filename = upload_file.filename
    else:
        # n8n HTTP Request V2 sends the file as a raw binary body
        content = await request.body()
        if not content:
            return {"error": "Missing raw body payload."}
        filename = "raw_upload.pdf" # Default filename for raw binary

    # 1. Save incoming file
    file_path = os.path.join(STORAGE_DIR, filename)
    with open(file_path, "wb") as buffer:
        buffer.write(content)
        
    try:
        # 2. PyMuPDF: Convert every page to a PNG image for the vision model.
        # Intake photos are often split across multiple PDF pages (e.g. the
        # signature line lands on page 2), so all pages must be sent, not just page 1.
        import fitz, base64, io
        from PIL import Image
        base64_images = []
        try:
            doc = fitz.open(file_path)
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(dpi=RENDER_DPI)
                base64_images.append(base64.b64encode(pix.tobytes("png")).decode("utf-8"))
            doc.close()
        except Exception as fitz_error:
            # PyMuPDF has no built-in HEIC/HEIF codec (only reachable if a phone's
            # raw HEIC file arrives as-is -- WhatsApp's own photo picker already
            # re-encodes to JPEG, which fitz handles above). Retry once via Pillow
            # (+pillow-heif); if that also fails, this genuinely isn't an image/PDF
            # we can read, so surface the original PyMuPDF error, not this fallback's.
            try:
                with Image.open(file_path) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="PNG")
                    base64_images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
            except Exception:
                raise fitz_error

        # 3. Local Airgapped VLM: Extract JSON natively from the image(s).
        # A scanned OFFICIAL doc (honorar/svs/bescheid/E-form) that reaches the vision
        # lane must be read with a TARGETED prompt for the fields it carries -- running
        # the handwritten-intake prompt on a printed SVS statement returns "Not Found"
        # for everything (it looks for handwriting that isn't there). Only the genuine
        # handwritten intake sheet / unlabelled photos use the intake prompt.
        _vk = _TEXT_FIELDS.get((doc_type or "").lower())
        if _vk:
            FIELD_KEYS = _vk
            prompt = _build_vision_prompt(_vk)
        else:
          FIELD_KEYS = [
            "tax_year", "e_card_number", "name", "address_austria", "home_address",
            "honorare", "wko_contribution", "provision_travel", "svs_sva",
            "marital_status", "children", "is_signed"
          ]

          prompt = f"""
        Transcribe the following fields from this handwritten tax intake form.
        You may be given more than one image — they are pages/photos of the SAME
        form, so check all of them before deciding a field is not found (e.g. the
        signature is often on a later page than the other fields).

        LITERAL EXTRACTION — follow these rules exactly, do NOT deviate:
        - Transcribe ONLY the handwriting the writer actually wrote next to or
          below each printed label. Copy it character for character, exactly as
          written — including any currency symbols, slashes, commas, dots, spaces
          or units the writer wrote, and excluding any they did NOT write. Do not
          add or drop characters to make a value look "correct" or "clean".
        - Assume NOTHING. Do NOT guess, infer, autocomplete, correct spelling,
          translate, expand abbreviations, normalise formatting, or otherwise
          "tidy up" a value. If the handwriting reads "AnnaB", output "AnnaB", not
          "Arnab". If a number looks like "7" output "7", even if "9" seems more
          plausible.
        - The value of a field is ONLY the handwriting that comes AFTER that
          field's printed label. NEVER use the printed label text itself as the
          value. For example, for 'home_address' the label may read "Address in
          Romania — <handwritten street>"; the value is the handwritten street,
          never the word "Romania".
        - If a field's handwritten value is missing, blank, crossed out, or
          genuinely illegible, set its "value" to "Not Found". Do NOT invent or
          approximate a plausible value to fill the gap.

        Return ONLY a JSON object with these exact keys:
        'tax_year', 'e_card_number', 'name', 'address_austria', 'home_address',
        'honorare', 'wko_contribution', 'provision_travel', 'svs_sva',
        'marital_status', 'children', 'is_signed'.

        For EACH of those keys, the value must be a JSON object of exactly this
        shape: {{"value": <the literally transcribed text>, "confidence": <a number
        from 0.0 to 1.0>}}. "value" MUST be a plain string, number, or boolean —
        never a nested object and never wrapped in extra keys. "confidence"
        reflects only how sure you are that you READ the handwriting correctly, and
        must be LOW when the writing is ambiguous — but low confidence is never a
        licence to guess: transcribe the ambiguous marks literally and lower the
        number instead.
        If a field is not found on any of the images, set its "value" to "Not Found"
        and its "confidence" to 0.0.
        CRITICAL: For 'is_signed', "value" must be true or false (a boolean) — check
        the bottom of every image for a signature. If there is a signature on any
        image, set "value" to true. If no signature line is filled in on any image,
        set "value" to false.

        Example shape for one field: {{"name": {{"value": "Maria Popescu", "confidence": 0.9}}}}
        """

        try:
            response = await call_model_bounded([{
                'role': 'user',
                'content': prompt,
                'images': base64_images
            }])
        except Exception as e:
            logger.error(f"Ollama unreachable after retries: {e}")
            return {
                "error": "service_unavailable",
                "message": f"AI model service did not respond after {1 + len(MODEL_RETRY_BACKOFF_SECONDS)} attempts: {e}"
            }

        # 4. Format Output
        raw_content = response['message']['content']
        try:
            llm_json = json.loads(raw_content)
            if not isinstance(llm_json, dict):
                raise TypeError(f"Expected a JSON object, got {type(llm_json).__name__}")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "Model returned JSON that wasn't the expected object shape, treating all "
                f"fields as not-found. Error: {e}. Raw response: {raw_content!r}"
            )
            llm_json = {}

        fields = {}
        confidence = {}
        for key in FIELD_KEYS:
            raw = llm_json.get(key)
            # The model puts confidence *inside* each field's own value object
            # ({"value": ..., "confidence": ...}) rather than in a separate
            # top-level object, no matter how the prompt asks for it -- so read
            # it from there. A field with no usable confidence still keeps its
            # extracted value; the two are scored independently.
            if isinstance(raw, dict) and "value" in raw:
                value, conf_raw = raw.get("value"), raw.get("confidence", raw.get("_confidence"))
            else:
                value, conf_raw = raw, None
            if value is None:
                value = False if key == "is_signed" else "Unknown"
            fields[key] = _reject_svnr_shaped_stnr(
                key, coerce_bool_value(value) if key == "is_signed" else coerce_field_value(value)
            )
            try:
                confidence[key] = max(0.0, min(1.0, float(conf_raw)))
            except (TypeError, ValueError):
                # Model didn't return a usable confidence for this field -
                # None (not a fabricated number) so callers can tell it's missing.
                confidence[key] = None

        _reject_duplicate_money(fields)

        # Born-digital E1a whose amounts are drawn as shapes (no text): the full-page
        # read above shifts figures between rows. Re-read every money line from its
        # own row's amount cell instead -- the row is located by its Kennzahl code
        # in the text layer, so a figure can't land on the wrong line.
        if (doc_type or "").lower() == "e1a":
            cells = await _read_kennzahl_cells(file_path)
            if cells is not None:
                for k in _CELL_MONEY_FIELDS:
                    fields[k] = cells.get(k, "Not Found")
                    confidence[k] = None
                fields["_kz_cells_checked"] = cells.get("_checked")
        return {"fields": fields, "confidence": confidence}

    except Exception as e:
        logger.error(f"Unhandled error processing {filename}: {e}", exc_info=True)
        return {"error": str(e), "message": "Failed to process document locally"}


# ---------------------------------------------------------------------------
# Kennzahl-cell reader (E1a with a text layer but vector-drawn amounts).
# FinanzOnline "E 1a-PDF" printouts carry every label and Kennzahl code as text,
# but the filled amounts are drawn as outlines, so neither lane 2 (text parse)
# nor lane 3 (LLM over text) can see them, and the full-page vision read assigns
# them to the wrong rows. Here each Kennzahl's row is found from the text layer,
# its amount cell is cropped, a blank cell is detected from pixels (no model
# call), and only a non-blank cell is shown to the model -- alone -- to read
# the number. The printed "Summe der Aufwendungen" and "Gewinn/Verlust" rows
# are read too and used as an arithmetic cross-check.
# ---------------------------------------------------------------------------

# EA field -> E1a Kennzahlen summed into it.
_CELL_KZ = {
    "honorare": [9040],
    "kleinmaterial": [9100],
    "abschreibung": [9130, 9134, 9135],
    "reisekosten": [9160],
    "provisionen": [9190],
    "svs_sva": [9225],
    "sonstiger_aufwand": [9230],
}
_CELL_MONEY_FIELDS = ("honorare", "svs_sva", "kleinmaterial", "provisionen",
                      "abschreibung", "sonstiger_aufwand", "reisekosten")
_CELL_TOTAL_ROWS = {"summe_aufwand": r"Summe der Aufwendungen", "gewinn": r"^\s*Gewinn/Verlust"}
# Expense Kennzahlen on the E1a 2023 layout (9230 = residual "übrige"), used only
# for the cross-check: every non-blank expense cell must add up to the Summe row.
_CELL_EXPENSE_KZ = range(9100, 9300)
_CELL_INK_MIN = 15  # dark pixels at 150 dpi below which a cell counts as blank


def _kz_hlines(page):
    """Horizontal ruling segments (x0, x1, y) from the page's vector drawings."""
    out = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.y - q.y) < 0.8 and abs(p.x - q.x) > 20:
                    out.append((min(p.x, q.x), max(p.x, q.x), (p.y + q.y) / 2))
            elif it[0] == "re":
                r = it[1]
                if r.width > 20:
                    out += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]
    return out


def _kz_cell(page, anchor, hlines, x_left):
    """Amount cell right of x_left on the row whose ruling encloses `anchor`."""
    import fitz
    probe = x_left + 20
    spans = [(x0, x1, y) for x0, x1, y in hlines if x0 <= probe <= x1]
    top = max([y for _, _, y in spans if y <= anchor.y0 + 1], default=None)
    bot = min([y for _, _, y in spans if y >= anchor.y1 - 1], default=None)
    if top is None or bot is None or bot - top > 80:
        return None
    right = max(x1 for _, x1, _ in spans)
    return fitz.Rect(x_left + 2, top + 1.2, right - 1.5, bot - 1.2)


def _kz_ink(page, rect) -> int:
    import fitz
    pix = page.get_pixmap(clip=rect, dpi=150, colorspace=fitz.csGRAY)
    return sum(1 for v in pix.samples if v < 140)


def _kz_locate(file_path):
    """[(key, page_no, rect)] for every Kennzahl row (key = int code) and total
    row (key = 'summe_aufwand'/'gewinn') whose amount cell is non-blank, plus the
    count of Kennzahl rows located. None if this PDF isn't that kind of form."""
    import fitz
    doc = fitz.open(file_path)
    try:
        cells, located = [], 0
        for pno, page in enumerate(doc):
            W = page.rect.width
            codes, labels = [], []
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    txt = "".join(s["text"] for s in l["spans"])
                    r = fitz.Rect(l["bbox"])
                    if re.fullmatch(r"9\d{3}", txt.strip()) and r.x0 > 0.6 * W:
                        codes.append((int(txt.strip()), r))
                    else:
                        labels.append((txt, r))
            if not codes:
                continue
            hl = _kz_hlines(page)
            col_x = min(r.x1 for _, r in codes)
            for code, r in codes:
                c = _kz_cell(page, r, hl, r.x1)
                if c is None:
                    continue
                located += 1
                if _kz_ink(page, c) > _CELL_INK_MIN:
                    cells.append((code, pno, c))
            for key, pat in _CELL_TOTAL_ROWS.items():
                for txt, r in labels:
                    if re.search(pat, txt):
                        c = _kz_cell(page, r, hl, col_x)
                        if c is not None and _kz_ink(page, c) > _CELL_INK_MIN:
                            cells.append((key, pno, c))
                        break
        # Needs most of a real E1a's rows found, else this isn't the layout we know.
        return (cells, located) if located >= 20 else None
    finally:
        doc.close()


async def _read_one_cell(file_path, pno, rect):
    import fitz, base64
    with fitz.open(file_path) as doc:
        pix = doc[pno].get_pixmap(clip=rect, dpi=300)
        img = base64.b64encode(pix.tobytes("png")).decode()
    # No sample number in the prompt: a weak model copies the example when unsure.
    prompt = ("This image is ONE cell of a printed Austrian tax form. It contains a single "
              "euro amount. Copy it exactly as printed. Return ONLY JSON: {\"value\": \"...\"}")
    resp = await call_model_bounded([{"role": "user", "content": prompt, "images": [img]}])
    try:
        v = json.loads(resp["message"]["content"]).get("value", "")
    except Exception:
        return None
    v = str(coerce_field_value(v) or "").strip()
    return v if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", v) else None


async def _read_kennzahl_cells(file_path):
    """{ea_field: 'n.nnn,nn', '_checked': bool|None} from per-row cell reads, or
    None when the PDF isn't a text-layer E1a we can locate rows on. A blank cell
    gives no key (the caller sets 'Not Found'). '_checked' is True when the read
    expense cells add up to the printed Summe and income - Summe == Gewinn,
    False when they don't, None when the form prints neither total."""
    try:
        loc = await asyncio.to_thread(_kz_locate, file_path)
    except Exception as e:
        logger.warning(f"Kennzahl-cell locate failed: {e}")
        return None
    if loc is None:
        return None
    cells, _ = loc
    cells.sort(key=lambda c: (c[1], c[2].y0))  # reading order
    # Expense rows = Kennzahl rows above the printed Summe der Aufwendungen; rows
    # after it (Korrekturen, Freibetraege, ...) are neither mapped nor summed.
    end = next((i for i, c in enumerate(cells) if c[0] == "summe_aufwand"), len(cells))
    mapped = {k for kzs in _CELL_KZ.values() for k in kzs}
    read, expense_kz = {}, set()
    for i, (key, pno, rect) in enumerate(cells):
        is_expense = isinstance(key, int) and i < end and key in _CELL_EXPENSE_KZ
        if key in read or not (is_expense or key in mapped or isinstance(key, str)):
            continue  # first occurrence wins (Gewinn/Verlust repeats later)
        v = await _read_one_cell(file_path, pno, rect)
        if v is not None:
            read[key] = v
            if is_expense:
                expense_kz.add(key)
    out = {}
    for ea, kzs in _CELL_KZ.items():
        vals = [_money(read[k]) for k in kzs if k in read]
        vals = [v for v in vals if v is not None]
        if vals:
            out[ea] = f"{sum(vals):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    exp = [_money(read[k]) for k in expense_kz]
    summe, gewinn, inc = _money(read.get("summe_aufwand")), _money(read.get("gewinn")), _money(read.get(9040))
    checks = []
    if summe is not None:
        checks.append(abs(sum(v for v in exp if v is not None) - summe) < 0.01)
        if gewinn is not None and inc is not None:
            checks.append(abs(inc - summe - gewinn) < 0.01)
    out["_checked"] = all(checks) if checks else None
    return out


# ---------------------------------------------------------------------------
# Lane 3 -- LLM over TEXT (no rasterization).
# perfect-extraction ticket 03: born-digital, code-less docs (Honorar / SVS /
# Bescheid) and the flat-text E-forms with no widget layer are handed to the SAME
# local model as plain text -- far faster and less lossy than rendering a legible
# page and running vision. The backend (which owns PyMuPDF) extracts the text
# layer and posts it here with the doc_type; we return the same {fields, confidence}
# contract as /extract, keyed by EA-record field names so the merge folds it in
# directly. Figure accuracy of this lane is the "text bet" -- to be confirmed
# against the ground-truth harness before it's trusted over the reviewer.
# ---------------------------------------------------------------------------

# Which EA fields to pull from each doc class's text (subset of the 14 auto fields
# that this doc class authoritatively carries -- see ticket 02 field->source matrix).
_TEXT_FIELDS = {
    "honorar": ["honorare", "provisionen"],
    "svs": ["svs_sva"],
    # The Bescheid is a tax-office notice addressed TO the taxpayer, so its header
    # carries their name + Austrian address + Steuernummer -- a reliable identity
    # source when the folder has no intake sheet / E-form.
    "bescheid": ["stnr", "name", "address_austria"],
    # E1 is the routing cover sheet (identity + which Beilage is attached) -- it
    # does not itself print Einnahmen/Ausgaben/SVS figures (those live on the E1a
    # Beilage). Asking for them here only invites hallucination: observed in
    # practice returning the SAME fabricated number for all three fields at once.
    "e1": ["stnr", "e_card_number", "name", "address_austria"],
    "e1a": ["stnr", "e_card_number", "name", "address_austria", "honorare", "svs_sva", "provisionen",
            "kleinmaterial", "abschreibung", "sonstiger_aufwand"],
    "steuererklaerung": ["stnr", "name", "address_austria", "honorare", "svs_sva", "provisionen",
                          "kleinmaterial", "abschreibung", "sonstiger_aufwand"],
    # E9 = EU/EWR Bescheinigung -- an income certificate FOR the non-resident spouse,
    # so the person it is about IS the spouse (sole source of the spouse identity). It
    # does NOT print a Familienstand string, so marital_status is left to the intake
    # sheet. FamBH = Familienbeihilfe notice -> the child/children names.
    "e9": ["spouse"],
    "fambh": ["children"],
}
# What each field means, in the document's own German terms, so the model knows
# what to look for. Kept deliberately literal -- no code numbers (they drift).
_FIELD_HINTS = {
    "honorare": "the taxpayer's total income / Honorar (Summe der Betriebseinnahmen / "
                "Leistungserlöse; for an agency Honorar note it is the SUM of the monthly "
                "fee amounts). On a single Honorarnote/invoice this is the Gesamtbetrag "
                "line (the grand total, after any zuzüglich USt is added) -- that figure "
                "is the taxpayer's OWN income, not a commission. If the document contains "
                "SEVERAL separate Honorarnoten/invoices (e.g. one per month, each on its "
                "own page), this field is the SUM of ALL of their Gesamtbetrag figures "
                "added together -- never just one page's total. A euro amount.",
    "provisionen": "commissions the taxpayer PAID OUT to a third party (Provisionen an "
                   "Dritte) -- an expense line, distinct from the taxpayer's own income/"
                   "Honorar. A Honorarnote's Gesamtbetrag/Pauschale/USt total is income, "
                   "never this field. If the document has no separate line explicitly "
                   "labelled Provision(en), this field is Not Found. A euro amount.",
    "svs_sva": "the compulsory social-insurance contribution total to SVS/SVA "
               "(Sozialversicherung der Selbständigen / Pflichtversicherungsbeiträge). "
               "An expense, normally far smaller than the income -- NEVER the "
               "Betriebseinnahmen/Leistungserlöse/Honorar figure. If no separate SV/"
               "Pflichtversicherung line carries its own amount, this field is Not Found. "
               "A euro amount.",
    "kleinmaterial": "the expense line for materials/supplies (Waren, Rohstoffe, "
                     "Hilfsstoffe und Zutaten -- Kleinmaterial). An expense, distinct "
                     "from Honorar/income. If that line is blank or empty on the form, "
                     "this field is Not Found -- never take the amount from a "
                     "neighbouring row (e.g. Reise-/Fahrtspesen). A euro amount.",
    "abschreibung": "the depreciation expense line (Abschreibungen / AfA -- "
                    "Absetzung für Abnutzung). An expense. If that line is blank or "
                    "empty on the form, this field is Not Found -- never the Gewinn/"
                    "Verlust, Summe or Grundfreibetrag figure. A euro amount.",
    "sonstiger_aufwand": "the catch-all other-expenses line (übrige Betriebsausgaben / "
                         "sonstige Aufwendungen, e.g. pauschalierte Betriebsausgaben, often "
                         "printed as Kennzahl 9230) -- ONE itemized expense line, distinct "
                         "from the more specific expense lines above (Kleinmaterial, "
                         "Abschreibung, SVS, Provisionen). NEVER the SUM/TOTAL of all "
                         "expense lines (Summe der Betriebsausgaben / Gesamtausgaben / "
                         "Aufwand gesamt) -- if the document only shows a combined total and "
                         "no separate line for sonstige Aufwendungen/9230, this field is "
                         "Not Found. A euro amount.",
    "stnr": "the Austrian tax number (Steuernummer) as printed on THIS document -- a "
            "Finanzamt code (2-3 digits) plus a 3-4 digit body, joined by a space or "
            "slash. If no Steuernummer is printed, it is Not Found. NOT "
            "the SVNR/e-card number, and NOT a field labelled VNR/Vers.Nr./"
            "Versicherungsnummer (that is the same kind of number as SVNR, just a "
            "different label for it on some tax-office documents) -- if the only "
            "identifier printed is under a VNR/Versicherungsnummer/SVNR label, this "
            "field is Not Found.",
    "e_card_number": "the taxpayer's own Austrian social-insurance number "
                     "(Versicherungsnummer / SVNR / VNR / e-card number): exactly 10 "
                     "digits, the last 6 being the birth date DDMMYY. NOT the "
                     "Steuernummer, and NOT a child's or spouse's number. If not "
                     "printed, it is Not Found.",
    "name": "the taxpayer's full name (the person the document is FOR/addressed to -- "
            "NOT a tax office, agency, or SVS institution name).",
    "address_austria": "the taxpayer's Austrian postal address (street, postal code, city) "
                       "as printed in the document header/address block.",
    "spouse": "the full name of the taxpayer's spouse/partner. On an E9 / Bescheinigung "
              "EU/EWR the person the certificate is ABOUT (whose foreign income is being "
              "certified) IS that non-resident spouse -- return THAT person's name. A "
              "person's NAME only: never a tax-office/institution name and never an income "
              "amount or figure.",
    "marital_status": "the taxpayer's marital status / Familienstand as printed: verheiratet "
                      "(married), ledig (single), geschieden, verwitwet, or in eingetragener "
                      "Partnerschaft.",
    "children": "the name(s) of the taxpayer's child/children (Kind/Kinder) named on the "
                "Familienbeihilfe notice. Copy the names as printed; if only a count is shown, "
                "give the number.",
}
_MAX_TEXT_CHARS = int(os.environ.get("LANE3_MAX_TEXT_CHARS", "24000"))


def _build_text_prompt(fields: list) -> str:
    lines = "\n".join(f"        - '{f}': {_FIELD_HINTS.get(f, f)}" for f in fields)
    keys = ", ".join(f"'{f}'" for f in fields)
    return f"""
        You are reading the TEXT of an Austrian tax document (already extracted from
        the PDF -- no image). Find ONLY these fields and transcribe them literally:
{lines}

        RULES:
        - Read each name/address field for the PERSON the document is FOR/addressed
          to -- NEVER a tax office, agency, or SVS institution's own name/address (a
          Finanzamt header's own Postfach/PO-box address is a common false match;
          the taxpayer's own address is elsewhere in the document, e.g. under a
          "Familien- oder Nachname"/"Straße" label or the letter's own address block).
        - Copy the value exactly as printed (keep the German number format, e.g.
          "1.234,56", and any currency symbol). Do NOT convert, round, or reformat.
        - Do NOT guess or infer. If a field is not present in the text, set its
          "value" to "Not Found" and "confidence" to 0.0.
        - A euro amount field is the FINAL/TOTAL figure for that line, not a subtotal
          of one month, unless the document only shows one figure.
        - Each field is a DIFFERENT piece of information. Never fill two different
          keys with the same figure unless the text truly prints that exact figure
          in both places -- if you can only find one real number, put it under the
          single field it actually belongs to and set the rest to "Not Found".
        - "value" is ONLY the data itself, NEVER the printed label next to it. If
          the text reads "VNR: 5530211078", the label is "VNR" and the value is
          "5530211078" -- never return "VNR: 5530211078" as a value, and never let
          that label make you put the number under the wrong field.

        Return ONLY a JSON object with exactly these keys: {keys}.
        For EACH key the value must be an object {{"value": <string>, "confidence": <0.0-1.0>}}.
        "value" MUST be a plain string. "confidence" is how sure you are you read it correctly.
        """


def _build_vision_prompt(fields: list) -> str:
    """Targeted VISION prompt for a scanned OFFICIAL doc (not the handwritten intake
    sheet): read just the fields this doc class carries, from the image(s)."""
    lines = "\n".join(f"        - '{f}': {_FIELD_HINTS.get(f, f)}" for f in fields)
    keys = ", ".join(f"'{f}'" for f in fields)
    return f"""
        You are reading image(s) — a scan or photo — of an Austrian tax document.
        Find ONLY these fields and transcribe each exactly as printed:
{lines}

        RULES:
        - Copy the value exactly as printed (keep the German number format like
          "1.234,56" and any currency symbol). Do NOT convert, round, or reformat.
        - Read each name/address field for the PERSON the document is FOR/addressed
          to -- NEVER a tax office, agency, or SVS institution's own name/address (a
          Finanzamt header's own Postfach/PO-box address is a common false match;
          the taxpayer's own address is elsewhere on the page, e.g. under a
          "Familien- oder Nachname"/"Straße" label or the letter's own address block).
        - Do NOT guess. If a field is not visible in the image(s), set its "value" to
          "Not Found" and its "confidence" to 0.0.
        - Forms list amounts in a table, one Kennzahl per row. Read each field ONLY
          from the row whose label matches it. Many rows are left BLANK -- a blank
          row's field is "Not Found"; never shift a figure up or down from another
          row to fill it.
        - Computed result rows (Summe der Betriebsausgaben / Aufwand gesamt,
          Gewinn/Verlust, Grundfreibetrag, Einkünfte) are NEVER the value of any
          individual expense field.
        - Each field is a DIFFERENT piece of information. Never fill two different
          keys with the same figure unless the page truly prints that exact figure
          in both places.
        - "value" is ONLY the data itself, NEVER the printed label next to it. If
          the page reads "VNR: 5530211078", the label is "VNR" and the value is
          "5530211078" -- never return "VNR: 5530211078" as a value, and never let
          that label make you put the number under the wrong field.

        Return ONLY a JSON object with exactly these keys: {keys}.
        For EACH key the value must be an object {{"value": <string>, "confidence": <0.0-1.0>}}.
        """


@app.post("/extract_text")
async def extract_text(request: Request):
    data = await request.json()
    text = (data.get("text") or "")[:_MAX_TEXT_CHARS]
    doc_type = (data.get("doc_type") or "").lower()
    if not text.strip():
        return {"error": "empty_text", "message": "No document text supplied."}

    wanted = _TEXT_FIELDS.get(doc_type)
    if not wanted:
        # Unknown class: pull the identity + headline figures generically.
        wanted = ["stnr", "honorare", "svs_sva"]

    prompt = _build_text_prompt(wanted) + "\n\n=== DOCUMENT TEXT ===\n" + text
    try:
        response = await call_model_bounded([{"role": "user", "content": prompt}])
    except Exception as e:
        logger.error(f"Ollama unreachable after retries (text lane): {e}")
        return {"error": "service_unavailable", "message": str(e)}

    raw_content = response["message"]["content"]
    try:
        llm_json = json.loads(raw_content)
        if not isinstance(llm_json, dict):
            raise TypeError(f"Expected a JSON object, got {type(llm_json).__name__}")
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Text lane: model returned non-object JSON ({e}). Raw: {raw_content!r}")
        llm_json = {}

    fields, confidence = {}, {}
    for key in wanted:
        raw = llm_json.get(key)
        if isinstance(raw, dict) and "value" in raw:
            value, conf_raw = raw.get("value"), raw.get("confidence", raw.get("_confidence"))
        else:
            value, conf_raw = raw, None
        if value is None:
            value = "Unknown"
        value = _reject_svnr_shaped_stnr(key, coerce_field_value(value))
        # Drop non-answers so they never outrank a real value in the merge.
        if isinstance(value, str) and value.strip() in ("", "Not Found", "Unknown"):
            continue
        fields[key] = value
        try:
            confidence[key] = max(0.0, min(1.0, float(conf_raw)))
        except (TypeError, ValueError):
            confidence[key] = None

    # Grounding: the text lane can see every number on the page, so a money value
    # it returns that isn't printed anywhere in that text is invented (seen on an
    # E1a whose text layer carried only labels: round 100000/10000/... figures).
    # An Honorar note's honorare is a cross-page SUM, so it's exempt there.
    printed = {round(n, 2) for rx in _NUM_TOKEN_RES for n in (_money(t) for t in rx.findall(text)) if n is not None}
    for k in ("honorare",) + _EXPENSE_FIELDS:
        if k == "honorare" and doc_type == "honorar":
            continue
        n = _money(fields.get(k))
        if n is not None and round(abs(n), 2) not in printed and round(n, 2) not in printed:
            fields[k] = "Not Found"
    _reject_duplicate_money(fields)
    for k in [k for k, v in fields.items() if v == "Not Found"]:
        fields.pop(k)
        confidence.pop(k, None)
    return {"fields": fields, "confidence": confidence}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)

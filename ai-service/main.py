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

STORAGE_DIR = "/storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

MODEL_NAME = os.environ.get("MODEL_NAME", "llava")
client = ollama.Client()

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
                options={"temperature": 0, "seed": 42},
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
    
    if "application/json" in content_type:
        data = await request.json()
        filename = data.get("filename", "n8n_upload.pdf")
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
                pix = page.get_pixmap(dpi=300)
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

        # 3. Local Airgapped VLM: Extract JSON natively from the image(s)
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
            fields[key] = coerce_bool_value(value) if key == "is_signed" else coerce_field_value(value)
            try:
                confidence[key] = max(0.0, min(1.0, float(conf_raw)))
            except (TypeError, ValueError):
                # Model didn't return a usable confidence for this field -
                # None (not a fabricated number) so callers can tell it's missing.
                confidence[key] = None

        return {"fields": fields, "confidence": confidence}
        
    except Exception as e:
        logger.error(f"Unhandled error processing {filename}: {e}", exc_info=True)
        return {"error": str(e), "message": "Failed to process document locally"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)

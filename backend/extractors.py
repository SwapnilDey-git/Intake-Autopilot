"""Deterministic document extractors — perfect-extraction lanes 1 & 2.

Wayfinder effort `perfect-extraction` (see .scratch/perfect-extraction/map.md). Ticket 03
decided a **deterministic-first, four-lane cascade** per document; this module is lanes 1
and 2 — the *exact*, model-free reads that shrink the slow CPU-vision workload to just
scans/photos/handwriting:

  * Lane 1  — AcroForm field-read. Born-digital BMF forms (E1/E1a/L1k) carry real AcroForm
              fields. Two techniques:
                (a) self-documenting named fields (L1k `SVNR`, `BMF_steuernummer_NEU`);
                (b) generic amount widgets (E1/E1a `Zahl40..Zahl80`) whose Kennzahl is a
                    *printed label* beside them -> a widget<->label spatial join reads the
                    figure and maps it by the label WORDING (version-stable), never by the
                    Kennzahl code (which drifts across form versions -- verified 2026-08-21:
                    current E1a uses 9180=Provisionen, 9220/9258=SV, NOT the 9190/9225 an
                    older note assumed).
  * Lane 2  — deterministic Kennzahl text-parse for flat-text forms with no widgets. Same
              label-keyed mapping, run over the text layer.

Everything this module can't read deterministically it declines (`ok=False`) with a `lane`
hint (`vision` | `llm_text`) so the caller falls back to the existing vision path (lane 4)
or the future LLM-over-text path (lane 3).

Output field names are already **EA-record names** (see backend/main.py EA_RECORD_FIELDS), so
the merge (`merge_year_fields`) folds them in with no extra mapping.

PII: this module READS document values (that's its job) but is written so its *callers* can
audit it without echoing PII — the companion `.scratch/perfect-extraction/validate_extractors.py`
runs it over the real corpus and prints only fill-counts and pattern-match rates, never a value.
"""
from __future__ import annotations
import re

# PyMuPDF is optional here: if the backend image doesn't ship it, the deterministic
# lanes simply disable themselves and every doc declines to the vision fallback -- the
# backend must still boot. (requirements.txt now lists pymupdf so it's normally present.)
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred import name
    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore  # legacy alias
        HAVE_PYMUPDF = True
    except ImportError:
        fitz = None  # type: ignore
        HAVE_PYMUPDF = False


# --- value shape guards -----------------------------------------------------
# Austrian SVNR / e-card number = 10 digits (4-digit serial+check, then DDMMYY).
_SVNR_RE = re.compile(r"\b(\d{4}\s?\d{6})\b")
# Steuernummer: 2-digit Finanzamt + 7-digit body, printed various ways
# ("12 345/6789", "12-345/6789", "12/345/6789"); accept 8-9 bare digits.
_STNR_RE = re.compile(r"\b\d{2}[\s/\-]?\d{3}[\s/\-]?\d{3,4}\b")


def _s(v) -> str:
    return str(v or "").strip()


def _looks_svnr(v: str) -> bool:
    return bool(_SVNR_RE.search(re.sub(r"\s+", " ", v or "")))


def _looks_stnr(v: str) -> bool:
    digits = re.sub(r"\D", "", v or "")
    return 7 <= len(digits) <= 10


# --- Kennzahl label -> EA field (version-stable: keyed on printed wording) ---
# Each entry matches the German label text printed on the E1/E1a row next to the
# amount widget. Order = specificity; first match on a row wins. Keyed on the
# printed WORDING, never the Kennzahl code, because codes drift across form
# versions -- verified against the real corpus 2026-08-28: the client's E1a uses
#   9040 Betriebseinnahmen | 9100 Waren/Rohstoffe/Hilfsstoffe | 9134 Abschreibungen
#   9160 Reise-/Fahrtspesen | 9190 Provisionen an Dritte | 9225 Pflichtversicherung
#   9233 pauschalierte Betriebsausgaben
# (so an earlier note's 9130/9180/9220 codes were wrong -- the labels are stable).
# All six EA money lines are mapped now (the soft-expense lines Kleinmaterial/AfA/
# Sonstiges are read here rather than left reviewer-entered). Note "betriebsAUSgaben"
# (9233) must not collide with "betriebsEINnahmen" (9040) -- distinct German words.
_LABEL_TO_EA = [
    (re.compile(r"(?i)pflichtversicherung|sozialversicherungsbeitr|\bsv-beitr"), "svs_sva"),
    (re.compile(r"(?i)provisionen"), "provisionen"),  # 9190 "Provisionen [EKR] an Dritte" -- tolerate interleaved column tokens
    (re.compile(r"(?i)rohstoffe|hilfsstoffe|\bwaren\b.*(rohstoff|hilfsstoff)"), "kleinmaterial"),
    (re.compile(r"(?i)abschreibung"), "abschreibung"),
    # 9160 "Reise- und Fahrtspesen inkl. Kilometergeld" -- the practice's EA takes
    # Reisekosten straight from this line (real-folder check 2026-10-26).
    (re.compile(r"(?i)reise-?\s*und\s+fahrtspesen|fahrtspesen|reisekosten"), "reisekosten"),
    (re.compile(r"(?i)pauschalierte.*betriebsausgaben|übrige\s+(betriebsausgaben|aufwend)|sonstige\s+aufwend"), "sonstiger_aufwand"),
    # honorare income (9040) is NOT taken off the E1a row here: the amount widget's
    # left-label is a generic "Achtung: Wert 0..." note on ~12/13 real forms, so a
    # label-join mis-binds it. Only a genuine "Summe der Betriebseinnahmen" subtotal
    # row is trusted; income's authoritative source is the Honorar note anyway.
    (re.compile(r"(?i)summe\s+der\s+betriebseinnahmen|betriebseinnahmen.*§\s*109a"), "honorare"),
]

# Doc types this module attempts. Everything else -> declined (caller falls back).
FORM_TYPES = {"e1", "e1a", "l1k", "steuererklaerung"}


def _yoverlap(word_bbox, rect) -> bool:
    """True if a text word vertically overlaps a widget's row (mid-line test)."""
    _, y0, _, y1 = word_bbox[:4]
    mid = (y0 + y1) / 2.0
    return rect.y0 - 1 <= mid <= rect.y1 + 1


def _row_label(words, rect) -> str:
    """The printed text to the LEFT of a widget on its row = that row's label."""
    row = [w for w in words if _yoverlap(w, rect) and w[2] <= rect.x0 + 2]
    row.sort(key=lambda w: w[0])
    return " ".join(w[4] for w in row)


def _widget_value(w) -> str:
    # text widgets expose the filled value on .field_value
    return _s(getattr(w, "field_value", None))


def _collect_widget_values(doc) -> dict:
    """{field_name: value} for every widget carrying a non-empty value. These
    XFA-descended BMF forms return empty get_form_text_fields(), so the widget
    layer is the real source of values (verified on the corpus 2026-08-21)."""
    out: dict[str, str] = {}
    for page in doc:
        try:
            widgets = list(page.widgets() or [])
        except Exception:
            continue
        for w in widgets:
            name, val = getattr(w, "field_name", None), _widget_value(w)
            if name and val:
                out.setdefault(name, val)
    return out


def _extract_form_kennzahlen(doc) -> dict:
    """Lane 1b: for each filled amount widget, read the figure and map it by the
    Kennzahl LABEL printed on its row. Returns {ea_field: value}."""
    out: dict[str, str] = {}
    for page in doc:
        try:
            words = page.get_text("words")
            widgets = list(page.widgets() or [])
        except Exception:
            continue
        for w in widgets:
            val = _widget_value(w)
            if not val:
                continue
            label = _row_label(words, w.rect)
            if not label:
                continue
            for rx, ea in _LABEL_TO_EA:
                if rx.search(label):
                    out.setdefault(ea, val)  # first row wins if a label repeats
                    break
    return out


def _extract_l1k(wv: dict) -> dict:
    """Lane 1a: L1k identity, read ONLY from the taxpayer block (`L1k_1`/`L1ab`).
    The `L1k_2` block's NACHNAME/VORNAME/SVNR belong to the *child* the Familienbonus
    is claimed for, so name is never taken from L1k (it would be the child's).
    `wv` is the {widget_name: value} map (get_form_text_fields is empty for L1k)."""
    out: dict[str, str] = {}

    def find(suffix: str, block: str | None = None):
        for k, v in wv.items():
            if k.lower().endswith("." + suffix.lower()) and (block is None or block.lower() in k.lower()):
                s = _s(v)
                if s:
                    return s
        return None

    stnr = find("BMF_steuernummer_NEU", "L1k_1") or find("BMF_steuernummer_NEU")
    if stnr and _looks_stnr(stnr):
        out["stnr"] = stnr
    svnr = find("SVNR", "L1k_1")  # taxpayer only; never fall back to the child's SVNR
    if svnr and _looks_svnr(svnr):
        out["e_card_number"] = svnr
    return out


def _extract_vcf(content: bytes) -> dict:
    """Parse a vCard's TEL/EMAIL. The corpus's cards are WhatsApp exports (TEL +
    FN, the number sometimes only in the `waid=` param, rarely any EMAIL), but this
    handles standard vCards too. Deterministic, model-free. Returns {tel?, email?}
    -- ONLY the contact fields the vcf authoritatively carries. `name` is
    deliberately NOT taken: a WhatsApp display name is a nickname, not the legal
    filing name (and vcf isn't in name's authority list anyway)."""
    try:
        text = content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        try:
            text = content.decode("latin-1", "ignore")
        except Exception:
            return {}
    # RFC-6350 line unfolding: a CRLF followed by a space/tab continues the line.
    text = re.sub(r"\r?\n[ \t]", "", text)
    tel = email = None
    for line in text.splitlines():
        if ":" not in line:
            continue
        head, _, value = line.partition(":")
        prop = head.split(";", 1)[0].strip().upper()
        value = value.strip()
        if "ENCODING=QUOTED-PRINTABLE" in head.upper():
            try:
                import quopri
                value = quopri.decodestring(value.encode("utf-8", "ignore")).decode("utf-8", "ignore")
            except Exception:
                pass
        if prop == "TEL" and not tel:
            if not value:  # WhatsApp card: the number lives only in the waid= param
                m = re.search(r"(?i)waid=([\d+]+)", head)
                value = m.group(1) if m else ""
            if value:
                tel = value
        elif prop == "EMAIL" and not email and value:
            email = value
    out: dict[str, str] = {}
    if tel:
        out["tel"] = tel
    if email:
        out["email"] = email
    return out


def _extract_e1_identity(doc) -> dict:
    """Steuernummer off the E1/E1a widget layer.

    The widget NAME 'SteuernummerInfo' is reused by BMF across SEVERAL unrelated
    fields on the same page -- verified on a real E1: it's bound to both the
    genuine Steuernummer boxes AND the 10-digit SVNR/e-card boxes. Bare name
    matching plus a first-non-empty-wins collector (the old `wv` dict approach)
    can silently return the SVNR instead of the Steuernummer whenever the
    Steuernummer boxes happen to be blank and the SVNR ones aren't. Disambiguate
    by the printed row label -- the same spatial technique _extract_form_kennzahlen
    uses -- and reject a value with the unambiguous SVNR shape and no
    Steuernummer-shaped formatting cue.
    """
    out: dict[str, str] = {}
    for page in doc:
        try:
            words = page.get_text("words")
            widgets = list(page.widgets() or [])
        except Exception:
            continue
        for w in widgets:
            name = getattr(w, "field_name", None) or ""
            if not (name == "SteuernummerInfo" or name.lower().endswith("steuernummer")
                    or "steuernummer_neu" in name.lower()):
                continue
            val = _widget_value(w)
            if not val or not _looks_stnr(val):
                continue
            label = _row_label(words, w.rect).lower()
            if "sozialversicherungsnummer" in label or "e-card" in label or "svnr" in label:
                continue  # this widget instance is actually the SVNR/e-card box
            if _looks_svnr(val) and not _STNR_RE.search(re.sub(r"\s+", " ", val)):
                continue  # unambiguous 10-digit SVNR shape, no Steuernummer formatting cue
            out["stnr"] = val
            break
        if "stnr" in out:
            break
    return out


# --- FinanzOnline printout identity -------------------------------------------
# A Steuererklärung printed from FinanzOnline carries TWO kinds of names:
#   * the page header "Teilnehmer*in: <name>  Bearbeiter*in: <name>" -- the tax
#     ADVISOR's FinanzOnline account that filed it (the same on every client's
#     printout), and
#   * "Unternehmensdaten -> Firmenname <name>" -- the taxpayer (for these sole
#     traders the business name IS the person's name).
# The LLM-over-text lane used to take the first name it saw, i.e. the advisor's,
# which then became the new client's display name. These helpers read both
# deterministically so the caller can (a) force the taxpayer name and (b) reject
# any extracted name that is really the filer. Children's names ("Angaben zum
# Kind -> Familien- oder Nachname") are deliberately never used.
_FILER_LABEL_RE = re.compile(r"(?i)\b(Teilnehmer|Bearbeiter|Benutzer)(\*?in(nen)?|\(in\)|/in)?\s*:")
# Plain "Name" row of a FinanzOnline Anbringen/Antrag printout (Name / Anschrift /
# Ort / Finanzamt / Steuernummer) -- the taxpayer the submission is for.
_NAME_ROW_RE = re.compile(r"^\s*Name\b[\s:]*(.*)$")
_FIRMENNAME_RE = re.compile(r"(?i)^\s*Firmenname\b[\s:]*(.*)$")


def _clean_name(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip(" :\t")


def _finanzonline_filer_names(text: str) -> list[str]:
    """Names printed after 'Teilnehmer*in:' / 'Bearbeiter*in:' / 'Benutzer*in:' (the filer, never
    the taxpayer). A value runs until the next label on the same line."""
    out: list[str] = []
    for line in (text or "").splitlines():
        matches = list(_FILER_LABEL_RE.finditer(line))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            val = _clean_name(line[m.end():end])
            # drop a trailing timestamp/date the header sometimes carries
            val = _clean_name(re.split(r"\s\d{1,2}\.\d{1,2}\.\d{2,4}", val)[0])
            if val and re.search(r"[A-Za-zÀ-ž]{2}", val):
                out.append(val)
    return out


def _finanzonline_taxpayer_name(text: str) -> str | None:
    """The 'Firmenname' value from the Unternehmensdaten block. Handles both
    text-layer shapes PyMuPDF produces for a two-column table row: label and
    value on one line ("Firmenname   Popescu Ana") or the value on the next
    non-empty line."""
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        m = _FIRMENNAME_RE.match(line)
        if not m:
            continue
        val = _clean_name(m.group(1))
        if not val:
            for nxt in lines[i + 1:i + 4]:
                if _clean_name(nxt):
                    val = _clean_name(nxt)
                    break
        # a value that is itself another row label means the cell was empty
        if val and not re.match(r"(?i)^(anschrift|plz|ort|steuernummer|land)\b", val) \
                and re.search(r"[A-Za-zÀ-ž]{2}", val):
            return val[:255]
    return None


def _finanzonline_name_row(text: str) -> str | None:
    """Fallback for Anbringen/Antrag printouts with no Unternehmensdaten block:
    the first exact 'Name' row (value on the same line or the next one). Only
    called when the doc carries the FinanzOnline filer header."""
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        m = _NAME_ROW_RE.match(line)
        if not m:
            continue
        val = _clean_name(m.group(1))
        if not val:
            for nxt in lines[i + 1:i + 3]:
                if _clean_name(nxt):
                    val = _clean_name(nxt)
                    break
        if val and not re.match(r"(?i)^(anschrift|ort|finanzamt|steuernummer|bv|bereich)\b", val) \
                and re.search(r"[A-Za-zÀ-ž]{2}", val):
            return val[:255]
        return None
    return None


def name_matches_filer(name: str, filer_names: list[str]) -> bool:
    """True when an extracted name is really the filer's (advisor's) name --
    compared token-set-wise so 'Mag. X Y' == 'Y X' and title/order noise is ignored."""
    def toks(s: str) -> set[str]:
        return {t for t in re.findall(r"[A-Za-zÀ-ž]{2,}", (s or "").lower())
                if t not in {"mag", "dr", "mmag", "dipl", "ing", "stb", "prof"}}
    nt = toks(name)
    if not nt:
        return False
    return any(nt and (nt <= toks(f) or toks(f) <= nt) for f in filer_names if toks(f))


def finanzonline_identity(text: str) -> dict:
    """{'name': taxpayer name or None, 'filer_names': [...]} for a FinanzOnline
    printout's text layer; empty dict when the text isn't one."""
    filers = _finanzonline_filer_names(text)
    name = _finanzonline_taxpayer_name(text)
    if not name and filers:
        name = _finanzonline_name_row(text)
    if name and filers and name_matches_filer(name, filers):
        name = None  # never hand back the filer as the taxpayer
    if not filers and not name:
        return {}
    return {"name": name, "filer_names": filers}


# Confidence assigned to a deterministic read. AcroForm named-field reads are as
# certain as parsing gets; the spatial label-join is a hair less (row heuristics),
# so it's marked slightly lower to reflect honest uncertainty to the reviewer.
_CONF_NAMED = 0.99
_CONF_JOIN = 0.90


_SNIFF_MAX_CHARS = 20000


def sniff_text(content: bytes, filename: str = "") -> str:
    """The PDF text layer (bounded to _SNIFF_MAX_CHARS), for content-based
    classification -- e.g. recognising the handwritten Stabinger intake form by
    its printed header even when the filename is a useless WhatsApp UUID.

    Returns "" for images, scans with no text layer, when PyMuPDF is absent, or on
    any read failure -- it is a best-effort sniff, never a hard dependency and never
    raises. (A photographed form has no text layer, so this returns "" for it; the
    image path handles those via the vision fallback.)

    Also reads the text of a typed .odt/.docx note (see _office_text) -- e.g. the
    intake answers typed up by the office instead of filled in by hand."""
    if content and content[:2] == b"PK" and (filename or "").lower().endswith((".odt", ".docx")):
        return _office_text(content)[:_SNIFF_MAX_CHARS]
    if not HAVE_PYMUPDF or not content or content[:4] != b"%PDF":
        return ""
    try:
        with fitz.open(stream=content, filetype=_filetype(filename)) as doc:
            out = []
            total = 0
            for p in doc:
                t = p.get_text() or ""
                out.append(t)
                total += len(t)
                if total >= _SNIFF_MAX_CHARS:
                    break
        return "".join(out)[:_SNIFF_MAX_CHARS]
    except Exception:
        return ""


def _office_text(content: bytes) -> str:
    """Plain text of an .odt (content.xml) or .docx (word/document.xml): paragraph
    and line breaks kept as newlines, tags dropped. "" on any failure, never raises.
    Pure stdlib -- no office suite in the container."""
    import html
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = set(z.namelist())
            part = "content.xml" if "content.xml" in names else "word/document.xml"
            if part not in names:
                return ""
            x = z.read(part)[:2_000_000].decode("utf-8", "ignore")
    except Exception:
        return ""
    x = re.sub(r"</(text:p|text:h|w:p)>|<text:line-break/>|<w:br/>|<w:cr/>", "\n", x)
    x = re.sub(r"<text:tab/>|<w:tab/>", "\t", x)
    return html.unescape(re.sub(r"<[^>]+>", "", x))


def extract_document(content: bytes, doc_type: str, filename: str = "") -> dict:
    """Deterministically extract EA fields from a document, or decline.

    Returns {ok, lane, fields, confidence}:
      ok=True   -> `fields` (EA-record names) read deterministically; `lane`='acroform'.
      ok=False  -> nothing read; `lane` in {'vision','llm_text'} tells the caller which
                   fallback to use ('vision' for scans/photos/handwriting; 'llm_text' for
                   born-digital code-less docs like honorar/svs/bescheid -> lane 3).
    Never raises: any read failure returns a declined result with lane='vision'.
    """
    dt = (doc_type or "").lower()

    # vCard: a plain-text parse, no PyMuPDF needed. Handle it before the PDF path.
    if dt == "vcf" or (filename or "").lower().endswith(".vcf"):
        vf = _extract_vcf(content)
        if vf:
            return {"ok": True, "lane": "vcard", "fields": vf,
                    "confidence": {k: _CONF_NAMED for k in vf}}
        return _declined("vision")  # unreadable card -> flag it; rare

    # The Stabinger paper intake form: its text layer is only the PRINTED wording
    # (that's how classify recognised it) -- the client's answers are handwriting
    # (ink/image). Lane 3 would read labels only and fall back to a generic field
    # set without tax_year, leaving the doc yearless. Always vision, whose
    # handwritten-intake prompt reads the full form field set incl. tax_year.
    if dt == "intake_form_paper":
        return _declined("vision")

    # The intake answers TYPED into an .odt/.docx note: plain text, so lane 3
    # (LLM-over-text) with the intake field set -- there is nothing to render.
    if dt == "intake_note":
        text = _office_text(content)
        if text.strip():
            return {"ok": False, "lane": "llm_text", "fields": {}, "confidence": {}, "text": text}
        return _declined("vision")

    if not HAVE_PYMUPDF:
        return _declined("vision")
    try:
        doc = fitz.open(stream=content, filetype=_filetype(filename))
    except Exception:
        return _declined("vision")

    try:
        try:
            is_form = bool(doc.is_form_pdf)
        except Exception:
            is_form = False
        try:
            text = "".join(p.get_text() for p in doc)
        except Exception:
            text = ""
        scanned = len(text) < 50 * max(1, doc.page_count)

        fields: dict[str, str] = {}
        conf: dict[str, float] = {}
        # Values live on the widget layer for these XFA-descended forms
        # (get_form_text_fields() is empty) -- read them there.
        wv = _collect_widget_values(doc) if is_form else {}

        if dt == "l1k":
            for k, v in _extract_l1k(wv).items():
                fields[k] = v
                conf[k] = _CONF_NAMED
        elif dt in ("e1", "e1a", "steuererklaerung"):
            for k, v in _extract_e1_identity(doc).items():
                fields[k] = v
                conf[k] = _CONF_NAMED
            if is_form:
                for k, v in _extract_form_kennzahlen(doc).items():
                    fields.setdefault(k, v)
                    conf.setdefault(k, _CONF_JOIN)

        # Taxpayer-vs-filer identity off a FinanzOnline printout's text layer. Not a
        # field read on its own (it must not short-circuit lane 3, which still has
        # to read the money lines) -- the caller applies it on top of whichever lane
        # produced the fields.
        # Computed for EVERY doc type: any FinanzOnline printout (FamBH, honorar,
        # Bescheid, Antrag...) carries the advisor in its header.
        identity = finanzonline_identity(text)

        if fields:
            return {"ok": True, "lane": "acroform", "fields": fields, "confidence": conf,
                    "identity": identity}

        # Nothing deterministic. Route the fallback: scanned/handwritten -> vision;
        # born-digital text -> lane 3 (LLM-over-text), carrying the text layer so the
        # caller can forward it to ai-service /extract_text without re-opening the PDF.
        if scanned:
            return _declined("vision")
        return {"ok": False, "lane": "llm_text", "fields": {}, "confidence": {}, "text": text,
                "identity": identity}
    finally:
        doc.close()


def _filetype(filename: str) -> str:
    ext = (filename or "").lower().rsplit(".", 1)
    if len(ext) == 2 and ext[1] in ("pdf",):
        return "pdf"
    if len(ext) == 2 and ext[1] in ("png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"):
        return ext[1]
    return "pdf"  # default; fitz sniffs the stream regardless


def _declined(lane: str) -> dict:
    return {"ok": False, "lane": lane, "fields": {}, "confidence": {}}

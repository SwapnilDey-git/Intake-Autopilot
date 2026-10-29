CREATE TABLE IF NOT EXISTS forms (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'uploaded',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Idempotency key (populated at approval time) — lets the backend detect
-- re-submission of the same physical form before it duplicates a row in
-- EA_2025.xlsx. NULL on forms that haven't been approved yet.
ALTER TABLE forms ADD COLUMN IF NOT EXISTS e_card_number VARCHAR(50);
ALTER TABLE forms ADD COLUMN IF NOT EXISTS tax_year VARCHAR(10);
CREATE INDEX IF NOT EXISTS idx_forms_ecard_taxyear ON forms(e_card_number, tax_year);

-- Multi-file case grouping (2026-08-19). Real intake is not one form per email --
-- a single client email/WhatsApp arrives as a whole case folder: the tax form(s)
-- plus assessment notices, invoices, income certificates, signature photos and
-- junk (avg ~40 files, seen up to 94). A `case` is one such submission; its
-- attachments are `forms` rows linked by case_id. Exactly one is the `primary`
-- (the E1/E1a/L1k/Steuererklärung we run extraction on); the rest are `supporting`
-- (filed alongside the Excel on approval, never extracted). Pure junk
-- (desktop.ini, Thumbs.db, .~lock, contact cards) is dropped and never inserted.
-- Backward-compatible: legacy single-upload forms simply have case_id = NULL and
-- still surface through /api/forms/pending unchanged.
CREATE TABLE IF NOT EXISTS cases (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50),               -- 'gmail' | 'whatsapp' | 'webhook' | 'dashboard'
    external_ref VARCHAR(255),        -- gmail message id / wa sender+ts (dedupe key)
    sender VARCHAR(255),              -- from-address / wa phone (may hold PII; local-only DB)
    subject VARCHAR(500),
    client_name_guess VARCHAR(255),   -- best-effort label for the queue before review
    status VARCHAR(50) DEFAULT 'open',-- open | approved | rejected
    filed_dir VARCHAR(500),           -- client folder the supporting docs were filed into (set once)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Re-delivery of the same Gmail message must not create a second case. Partial
-- unique index (NULLs allowed for channels without a stable ref).
CREATE UNIQUE INDEX IF NOT EXISTS idx_cases_external_ref
    ON cases(external_ref) WHERE external_ref IS NOT NULL;

ALTER TABLE forms ADD COLUMN IF NOT EXISTS case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE;
-- classified type (e1a, e1, l1k, steuererklaerung, bescheid, honorar, fambh, svs,
-- gisa, antrag, signature, photo, other) and role within the case.
ALTER TABLE forms ADD COLUMN IF NOT EXISTS doc_type VARCHAR(50);
ALTER TABLE forms ADD COLUMN IF NOT EXISTS role VARCHAR(20);  -- 'primary' | 'supporting'
CREATE INDEX IF NOT EXISTS idx_forms_case ON forms(case_id);

CREATE TABLE IF NOT EXISTS extractions (
    id SERIAL PRIMARY KEY,
    form_id INTEGER REFERENCES forms(id) ON DELETE CASCADE,
    json_result JSONB NOT NULL,
    confidence JSONB
);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    form_id INTEGER REFERENCES forms(id) ON DELETE CASCADE,
    approved BOOLEAN DEFAULT FALSE,
    updated_data JSONB
);

-- No login system exists yet, so this is a free-text label the reviewer
-- types in the dashboard, not an authenticated identity.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS reviewer_name VARCHAR(255);

-- who/what/when for every extraction, approval, rejection, duplicate block,
-- Excel write, original-document filing, and WhatsApp first-contact greeting.
-- event_type values: extraction, extraction_failed, approval, rejection,
-- duplicate_blocked, write, file, completeness, greeting_sent. NOTE: form_id
-- is a nullable FK -- the 'greeting_sent' event has no associated form, so it
-- is written with form_id = NULL.
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    form_id INTEGER REFERENCES forms(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    actor VARCHAR(255),
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- First-contact dedupe for the WhatsApp intake channel (ticket 20a). One row
-- per WhatsApp sender (wa_id = the sender's phone in Meta's international
-- format). A sender is recorded on their FIRST inbound message of ANY kind
-- (text or media) so a media-first client who skips the greeting is never
-- greeted later. The auto-greeting fires only when a brand-new sender's first
-- message is a plain text (no document) -- see n8n/Intake_Flow_Real.json's
-- WhatsApp branch. greeted_at is NULL until/unless the greeting is actually
-- sent. Insert is done with `ON CONFLICT (wa_id) DO NOTHING RETURNING wa_id`,
-- so a returned row == genuinely-new sender (race-safe against two fast
-- messages). Purely a runtime dedupe table -- carries no tax data.
CREATE TABLE IF NOT EXISTS whatsapp_contacts (
    wa_id VARCHAR(32) PRIMARY KEY,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    greeted_at TIMESTAMP
);

-- Small lookup table of known carer/client addresses -> coordinates, populated
-- by a one-time offline batch geocode (see RUNNING.md's "Travel distance
-- geocoding" section) plus ad hoc manual inserts as new addresses show up --
-- deliberately not backed by a live geocoding service (self-hosted/airgapped
-- constraint applies to the runtime inference path, not this one-off admin
-- data-entry step). address_text is matched verbatim (trimmed/lowercased) by
-- compute_travel_suggestion() below, so OCR variance between extractions of
-- the same physical address can miss a lookup hit -- a known limitation, not
-- yet solved with fuzzy matching.
CREATE TABLE IF NOT EXISTS address_geocode (
    id SERIAL PRIMARY KEY,
    address_text VARCHAR(500) NOT NULL UNIQUE,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    source VARCHAR(50) DEFAULT 'manual',
    geocoded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================================
-- Person-centric, per-year model (2026-08-20, ADR-0001).
-- The real client data is per-PERSON folders spanning multiple tax years,
-- not one-email-per-case. A `client` (natural person) is now the top-level
-- unit; it owns many `tax_years`; each tax year produces one EA sheet. A
-- `case` (email/WhatsApp/folder submission) is an attach-point that routes
-- its documents to a client. All columns here are additive and nullable so
-- the existing single-form / case flows keep working unchanged.
-- =====================================================================

-- One natural person the practice files for (mostly Romanian 24h-carers).
CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(255),        -- shown in the queue (may hold PII; local-only DB)
    normalized_name VARCHAR(255),     -- lowercased / diacritics-stripped, for name matching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_clients_normname ON clients(normalized_name);

-- Identities used to route an inbound submission to an existing client:
-- email address, WhatsApp phone, or a matched name. kind in ('email','phone','name').
-- A given (kind,value) maps to at most one client (guards against silently
-- merging two people who share a value).
CREATE TABLE IF NOT EXISTS client_identities (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    kind VARCHAR(20) NOT NULL,
    value VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_client_identities_kind_value
    ON client_identities(kind, value);

-- One assessment year for one client -- the unit that produces a single EA sheet.
-- ea_fields holds the merged, reviewer-confirmable EA record (income + the six
-- Kennzahl expense figures + household); status tracks the year's progress; ea_path
-- is the generated EA_{year}.xlsx location once written.
CREATE TABLE IF NOT EXISTS tax_years (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',  -- draft | reviewed | generated
    ea_fields JSONB,
    ea_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tax_years_client_year
    ON tax_years(client_id, year);

-- A submission belongs to a client (routed at intake; NULL until matched).
ALTER TABLE cases ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL;

-- A document, once its year is known, belongs to a person-year. doc_year is the
-- raw year parsed from the filename/content before it is bound to a tax_years row.
ALTER TABLE forms ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS tax_year_id INTEGER REFERENCES tax_years(id) ON DELETE SET NULL;
ALTER TABLE forms ADD COLUMN IF NOT EXISTS doc_year INTEGER;
CREATE INDEX IF NOT EXISTS idx_forms_client ON forms(client_id);
CREATE INDEX IF NOT EXISTS idx_forms_taxyear ON forms(tax_year_id);

-- Questionnaire invites (2026-10-07). The office creates one personal link per
-- (client, year); its ref is printed on -- and embedded in -- the PDF the client
-- sends back, which is how a returned questionnaire is matched and tracked.
-- The public form page stores nothing; this table lives only on the office box.
CREATE TABLE IF NOT EXISTS questionnaire_invites (
    ref VARCHAR(24) PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    returned_at TIMESTAMP,
    form_id INTEGER REFERENCES forms(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_q_invites_client ON questionnaire_invites(client_id);

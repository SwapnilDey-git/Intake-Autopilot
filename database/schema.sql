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

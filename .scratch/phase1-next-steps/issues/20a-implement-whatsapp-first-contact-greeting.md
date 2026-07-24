Type: task
Status: open
Blocked by: (build unblocked — see note)

## Task

Implement the WhatsApp first-contact auto-reply designed in ticket 20 (resolved
2026-07-24). **Build + test-tier verification only — real go-live stays gated** on Meta
Business Verification (ticket 08) + explicit user sign-off, and the Romanian half of the
copy is client-gated. Channel-ordering was deliberately overridden *for build* (ticket 20,
decision 4): a no-PII/no-review/no-outcome greeting does not inherit ticket 07's PII-reply
deferral, so this build does not wait on 07b.

Target workflow: `n8n/Intake_Flow_Real.json` (live id `sn3IWsWJ04lCYkYG`), WhatsApp branch.

## Build spec (from ticket 20's Answer)

1. **DB — new table.** Add to `database/schema.sql` (re-runnable, `IF NOT EXISTS`):
   ```sql
   CREATE TABLE IF NOT EXISTS whatsapp_contacts (
       wa_id VARCHAR(32) PRIMARY KEY,
       first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       greeted_at TIMESTAMP
   );
   ```
   Remember: schema is NOT auto-applied — run `psql ... -f database/schema.sql` after adding
   (see CLAUDE.md / RUNNING.md).

2. **Sender extraction + seen-check — BEFORE the media filter.** Insert a step between
   `WhatsApp Webhook (Receive Message)` and `Filter Media Messages (WhatsApp)` that pulls the
   sender `wa_id` and a `has_media` flag from the inbound payload, then runs the atomic upsert:
   ```sql
   INSERT INTO whatsapp_contacts (wa_id) VALUES ($1)
   ON CONFLICT (wa_id) DO NOTHING RETURNING wa_id;
   ```
   A returned row ⇒ genuinely new sender (race-safe against two fast messages). Marking seen
   on *any* first message (media or text) per ticket 20 decision 2 — so a media-first sender is
   recorded and never later greeted.

3. **Greeting branch.** Fires only when `is_new` (row returned) AND `has_media` is false.
   Send via **HTTP Request node** → Graph API `POST /{phone-number-id}/messages` reusing the
   existing WABA bearer token (same auth as `Get Media URL` / `Download Media Bytes`). Body is
   a free-form text message — **no Meta message-template approval needed** (24h customer-service
   window opened by the inbound message). On success, set `greeted_at = now()` for that `wa_id`
   and write an `audit_log` row (`event_type='greeting_sent'`, `actor='n8n-whatsapp'`).
   Best-effort: `retryOnFail` + error branch → audit the failure; never block/crash intake.

4. **Greeting copy — one swappable constant.** Bilingual German + Romanian.
   - German (CONFIRMED, from real usage — `client_reply.md` line 10, verbatim):
     `Hallo. Bitte reichen Sie Ihre Einkommensteuererklärung ein. Ich sende Ihnen dann das
     Informationsblatt, die E-Card und den Personalausweis zu. Bitte teilen Sie mir mit, wie
     hoch die Versandkosten sind. Vielen Dank.`
   - Romanian (**PLACEHOLDER — confirm with client before go-live; do NOT machine-translate
     into live delivery**).
   Keep both in a single config location so the client's real copy swaps in one edit
   (mirrors ticket 21's mandatory-field constant).

5. **Media / intake path unchanged.** `Filter Media Messages (WhatsApp)` true-branch and
   everything downstream (`Extract Media Info` → ... → DB inserts) stays exactly as-is.

## Verification (test tier — nothing reaches a real client)

- Meta Cloud API **test tier**: register a small whitelist of verified recipient numbers
  (no Business Verification required at this tier).
- Cases: (a) new sender, text-only → greeting sent once, `greeted_at` + audit row written;
  (b) same sender texts again → NO second greeting; (c) new sender, media-first → NO greeting,
  `wa_id` recorded, doc flows through the existing intake path; (d) send-failure path → audit
  row, intake not blocked.
- Confirm node/connection integrity via Postgres (per the ticket-09 / ticket-16 live-testing
  discipline — "success" execution status alone is not trust).

## Gates carried forward (do NOT cross without sign-off)

- **Real go-live:** Meta Business Verification (ticket 08) + explicit user sign-off. Standing
  constraint: no autonomous client messaging goes live without it.
- **Romanian copy:** client-gated (no real Romanian first-contact text exists yet).
- **Watch:** this stands up the WhatsApp *send* node/credential for the first time — do not let
  the PII approval-reply (ticket 07b) later ride this same send path without its own review.

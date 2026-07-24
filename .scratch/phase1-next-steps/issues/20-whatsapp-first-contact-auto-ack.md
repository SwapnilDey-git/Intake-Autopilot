Type: grilling
Status: resolved

## Question

**Opened 2026-07-23** from the collaborator's 5-step wishlist, item 1: auto-reply to a
client's **first** WhatsApp message. Per the continuation context this is "in scope, easy —
exact wording already exists from real usage, just needs wiring into n8n."

Scope it before building (this is a decision ticket; the build spins off separately):

1. **Trigger definition** — what counts as "first contact"? The inbound WhatsApp webhook
   (`WhatsApp Webhook (Receive Message)` in `n8n/Intake_Flow_Real.json`) fires on every
   message. First-contact means: first message from a sender we've not seen? First message
   with no media (a greeting, vs. a doc submission)? Needs a dedupe/"seen sender" check —
   where does that state live (a Postgres table? a WhatsApp label equivalent)?
2. **Wording** — confirm/obtain the exact real auto-ack text (task, analogous to 07a). It
   reportedly exists from real usage; get it verbatim and confirm language (Romanian? per
   the carer audience) and whether it needs placeholders.
3. **Channel-ordering conflict (important)** — ticket 07 deliberately deferred *all*
   WhatsApp auto-send behind Gmail auto-reply (07b) shipping first. Does a fixed
   first-contact template — no PII, no review dependency, not tied to an approval outcome —
   justify overriding that ordering, or does it wait behind 07b too? This is the real
   decision here.
4. **Send infra** — first WhatsApp auto-send on the platform. Requires the WABA send path
   (Meta Business Verification, ticket 08) to be live for *real* delivery, though the n8n
   logic can be built/tested against the test tier first.

Recommended build order (from the session) put this first among the wishlist items — but
only after (3) is decided and (2)'s wording is in hand. No auto-send goes live to real
clients without explicit user sign-off (standing constraint).

## Answer

**Resolved 2026-07-24 (grilling).** Design settled for the two non-client-gated questions
(trigger/dedupe + channel-ordering) plus the ancillary ones that surfaced. Build spins off
separately; go-live stays gated.

**Evidence check first (the ticket's "wording already exists" premise).** Verified against
`.scratch/client_reply.md` (real client WhatsApp dump, PII, marked "delete after using" —
opened with explicit user go-ahead). Finding **overturned the initial framing**: the
collaborator's own numbered flow (line 9) is `1) receive the initial message and reply
2) receive intake docs + assess completeness 3) contact re missing info 4) create folder
5) fill worksheet` — i.e. tickets 20 / 21 / 22 / 06a / Excel-fill respectively. The real
first-contact reply (line 10) is a **greeting that prompts the client to submit their docs**,
NOT a "documents received" acknowledgement. There is no doc-received ack anywhere in real
usage. So this ticket is a **greeting-reply**, not an intake ack.

**Decisions:**
1. **Trigger** — fires on a client's **first inbound message with no document attached** (a
   greeting). Reply prompts them to submit their tax docs. (Pivoted away from a doc-received
   ack, which isn't part of the real flow.)
2. **Dedupe rule** — a `wa_id` is marked **seen on its first inbound message of any kind**
   (text or media). Greeting fires only for a no-media first message from an unseen sender.
   Fails safe toward *not* re-greeting someone already mid-flow (over-messaging real clients
   is the worse error) rather than tracking greeted-only.
3. **State** — new Postgres table `whatsapp_contacts(wa_id PK, first_seen_at, greeted_at)`,
   written with atomic `INSERT ... ON CONFLICT (wa_id) DO NOTHING RETURNING` (race-safe against
   two fast messages; the returned row drives the greet decision). Chosen over n8n workflow
   static data (fragile — this workflow gets duplicate-imported, static data resets) and over
   overloading `audit_log` (whose `actor` is the channel `'n8n-whatsapp'`, not the sender).
4. **Channel-ordering conflict (the real crux)** — **override ticket 07's WhatsApp-behind-Gmail
   deferral for BUILD; keep go-live gated.** 07 deferred the *approval/rejection reply*, which
   carries PII, depends on a review outcome, and has two per-client variants — none of which
   apply to a fixed, no-PII, no-review, no-outcome first-contact greeting. The real go-live gate
   is Meta Business Verification (ticket 08) + the standing "no autonomous client messaging
   without explicit sign-off", both stronger than 07b and unchanged. So: build + test-tier
   verify now; real send stays dark. NB — this stands up the WhatsApp *send node/credential* for
   the first time; watch that the PII approval-reply (07b) doesn't later ride this same send path
   without its own review.
5. **Wording** — bilingual German + Romanian, shipped as **one swappable config constant**
   (like ticket 21's field list). German = line 10 verbatim (confirmed). **Romanian half is a
   placeholder — no Romanian first-contact copy exists in the file** (the file's Romanian text
   belongs to the payment/completion messages); confirm real Romanian copy with the client
   before go-live. Never machine-translate client-facing copy into live delivery.
6. **Send mechanism** — HTTP Request node to Graph API `POST /{phone-number-id}/messages`
   reusing the existing WABA bearer token (matches the current `Get Media URL` / `Download
   Media Bytes` httpRequest nodes; no new credential type). **No Meta message-template approval
   needed** — the reply lands inside the 24-hour customer-service window opened by the inbound
   message, so it's a free-form session message. Writes an `audit_log` row (`greeting_sent`,
   `actor: 'n8n-whatsapp'`); best-effort with retry, never blocks intake.

**Proposed wiring (for the build ticket):** a sender-extraction + `whatsapp_contacts` upsert
sits **before** the existing `Filter Media Messages (WhatsApp)` IF (so media-first senders also
get marked seen per decision 2); the greeting HTTP send hangs off the *no-media + newly-inserted*
path; the media/intake path is unchanged.

**Test plan:** verify on Meta's Cloud API **test tier** (sends only to a small whitelist of
verified numbers, no Business Verification required), so nothing reaches a real client.

**Still gated (unchanged):** real go-live (Meta ticket 08 + explicit user sign-off); the
Romanian half of the greeting copy (client). Build itself is now unblocked.

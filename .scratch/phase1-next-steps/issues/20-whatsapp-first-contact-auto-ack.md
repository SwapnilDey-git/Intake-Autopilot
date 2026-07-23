Type: grilling
Status: open

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

(pending)

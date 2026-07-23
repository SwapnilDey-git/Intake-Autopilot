Type: grilling
Status: open
Blocked by: 07a, 07b, 21

## Question

**Opened 2026-07-23 — NEW SCOPE, not a deferred original-plan item.** From the
collaborator's wishlist, item 3: the system autonomously **detects a specific missing
field, composes a message asking the client for it, sends it, and waits for a resend.**

**Why this is flagged new scope** (verified against PRODUCT.md / DESIGN.md this session):
missing/incomplete-field handling was always designed as a **human-facing dashboard
warning** — to stop a reviewer approving something incomplete by accident — never as an
autonomous auto-reply trigger. The only auto-reply scoped anywhere (tickets 07/07a/07b) is
a single templated confirmation fired when a **human clicks Approve/Reject** — not the
system detecting a missing field, composing a message, and sending it unattended. This was
flagged to the collaborator as a separate future step, awaiting their sign-off — do NOT
build it without new, explicit scoping.

Open decisions (once unblocked):

1. **Autonomy boundary** — does it auto-send, or draft-for-human-approval? (Standing
   constraint: no autonomous client messaging exists on any channel; everything
   client-facing today is a human manually sending.)
2. **Wording** — needs the real client-approved templates, per field or generic (task,
   like 07a — blocked by 07a which is still pending).
3. **Wait/resume state machine** — how does a resend get correlated back to the original
   incomplete submission? New stateful conversation logic the pipeline doesn't have today.
4. **Channel** — WhatsApp and/or Gmail; inherits 07's Gmail-first ordering and the
   send-infra gates (07b, ticket 08 for WhatsApp).

Blocked by: 07a (wording), 07b (Gmail send infra), 21 (the completeness signal that would
detect "missing"). Explicitly do not start without a fresh scoping pass + user sign-off.

## Answer

(pending — new scope, blocked; awaiting explicit go-ahead)

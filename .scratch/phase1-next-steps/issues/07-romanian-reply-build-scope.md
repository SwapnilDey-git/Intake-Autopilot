Type: grilling
Status: resolved
Blocked by: 01

## Question

`draft_reply`/`send_message` (Romanian auto-reply on approval/rejection) is on hold per project memory, but that hold was framed around WhatsApp being blocked on WABA verification (see ticket 08). Gmail intake has no such blocker and is already active. Decision: build the Romanian-reply draft + Gmail-send now (independent of WhatsApp), or hold the whole feature until WhatsApp is also unblocked so both channels ship together? If building now: where does the Romanian copy come from (fixed template vs. LLM-drafted), and does it fire on approval, rejection, or both?

## Answer

**Decided (2026-07-15), three-part:**

1. **Sequencing: build now, Gmail-only.** Gmail intake has no blocker and is already active, so the Romanian-reply feature ships on that channel now rather than waiting on WhatsApp's still-client-side prerequisites (ticket 09). WhatsApp gets wired into the same reply logic later, once its own prerequisites clear — not a rebuild, just a second send-channel added to the same trigger point.
2. **Copy source: neither a dev-written fixed template nor LLM-drafted — request the actual Romanian wording from the client.** Neither the developer nor an LLM should be inventing client-facing message copy in a language neither party is a native speaker of verifying — accurate tone/phrasing for a real carer-facing message is the client's call, not ours to guess or auto-translate. Spun off as a new client-side ask, ticket 07a.
3. **Trigger: both approval and rejection.** The carer gets closure either way — a confirmation message on approval, and on rejection a message noting what needs fixing/resubmitting. This means **two separate template variants** are needed from the client (approval-copy, rejection-copy), not one.

**Follow-on tickets**: 07a (client ask for the two Romanian templates) and 07b (build the actual send logic once the templates exist, blocked by 07a) — see those tickets for detail. 07b also surfaced a real schema gap while scoping: nothing in `database/schema.sql` currently captures the original sender's email address, so even once the copy exists, `backend`'s `submit_review` (which runs later, decoupled from the n8n execution that received the email) has no address to reply to yet — that's now part of 07b's scope, not a separate ticket, since it's a small addition needed to make the reply send at all.

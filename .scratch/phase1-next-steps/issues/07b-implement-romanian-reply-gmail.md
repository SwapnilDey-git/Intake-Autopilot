Type: task
Status: open
Blocked by: 07a

## Question

Implement the Gmail-only Romanian auto-reply, per ticket 07's decision (build now, template-based copy from the client via 07a, fires on both approval and rejection).

1. **Schema gap surfaced while scoping this**: nothing currently captures the original sender's email address. `n8n`'s `Gmail Trigger` node has it in-context at intake time (message metadata), but it's never persisted — by the time `backend`'s `submit_review` runs (later, decoupled, triggered from the dashboard reviewing a Postgres row, not from the live n8n execution that received the email), there's no address to reply to. Add a `forms.sender_email` column (`database/schema.sql`, `IF NOT EXISTS` per this repo's convention) and populate it in the Gmail intake path's `Insert Form DB (Gmail)` node in `n8n/Intake_Flow_Real.json`. Leave it `NULL` for the webhook and dashboard-upload paths (no email available there) — the send step (below) should just no-op if it's `NULL`, not error.
2. **Template substitution**: once 07a returns the two Romanian templates (and whatever placeholders the client wants), add them somewhere sensible (env var, a small config file, or a new table if the client wants them editable without a redeploy — decide based on what 07a returns) and a small substitution function in `backend/main.py`.
3. **Send step**: on `submit_review`'s approval/rejection branches, if `forms.sender_email` is not null, send the appropriate templated message via a Gmail node — either a new n8n workflow triggered by `backend` (webhook-in-reverse) or backend calling Gmail's API directly. Reuse the existing Gmail OAuth2 credential (id `"2"` in `n8n/Intake_Flow_Real.json`, already created manually in the n8n UI for the Gmail Trigger) rather than provisioning a second one.
4. **Audit log**: record the send (or the no-op skip, or a send failure) as a new `audit_log` event — `event_type='reply_sent'` or similar, consistent with this project's existing pattern of logging every side effect.

Verify: extend ticket 01's end-to-end test — send a test PDF through the Gmail intake path (needs the Gmail credential to actually be active — check RUNNING.md's Gmail intake section for current activation status), approve it, confirm a Romanian reply email actually arrives, confirm the `audit_log` row.

## Answer

(pending)

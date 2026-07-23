Type: grilling
Status: open

## Question

**Opened 2026-07-23** from the collaborator's wishlist, item 2: assess submitted docs for
**completeness** — turn today's *human-facing* signals into an *automated* pass/fail.

Current state (verified): the dashboard shows a hardcoded "Historically Unreliable Fields"
banner for `e_card_number`, `name`, `honorare`, `svs_sva` (ticket 15a) and per-field
confidence was proven uncalibrated (always 1.0), so confidence is NOT a usable
completeness signal. There is no automated "is this submission complete?" check anywhere.

Scope the design (decision ticket; build spins off):

1. **What defines "complete"** — which of the 12 FIELD_KEYS are mandatory vs. optional?
   Is `is_signed` a hard gate? Does completeness mean "all required fields non-empty," or
   "non-empty AND plausible" (format checks on e-card number, dates, amounts)?
2. **What the signal drives** — dashboard state only (a clear pass/fail badge to stop a
   reviewer approving something incomplete), or does it *gate* something automated
   downstream (e.g. it's the trigger for the item-3 auto-follow-up)? Note item 3 (ticket
   22) depends on this signal existing.
3. **Where it computes** — in `ai-service` right after extraction, or in `backend` at
   persist/review time? (Backend already owns the review/audit path.)
4. **Audit** — record the completeness verdict as an `audit_log` event, per repo pattern.

Not blocked — extends existing logic, no new client input required. Third in the session's
recommended build order (after auto-ack, file-filing — filing is already done).

## Answer

(pending)

Type: grilling
Status: resolved


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

**Resolved 2026-07-23 (grilling + build, same session).**

**1. What defines "complete" — mandatory set.** First-principles trap surfaced during
the grill: for the money fields, a *blank* value is ambiguous — it could be a genuine zero
or a client omission, and extraction cannot tell them apart (both come back empty). So the
line isn't "all fields non-empty"; it's "which blanks are *probably* omissions worth
flagging." Decision:

- **Mandatory (7):** `tax_year`, `e_card_number`, `name` (identity — can't file or even name
  the client folder without them), `is_signed` (legal gate — an unsigned form isn't
  filable; `false`/absent counts as incomplete), and `honorare`, `svs_sva`,
  `wko_contribution` (money fields that are rarely legitimately zero for a real filing
  client, so a blank there is almost certainly a real omission = good signal).
- **Optional (5):** `provision_travel` (deliberately dropped from mandatory — genuinely
  often zero for non-travelling carers; requiring it would false-flag every no-travel form
  and train reviewers to ignore the badge), plus `address_austria`, `home_address`,
  `marital_status`, `children` (natural defaults / rarely block a filing).
- The mandatory set ships as a **configurable constant** (`MANDATORY_FIELDS` in
  `backend/main.py`), so the client's real "must-have" answer swaps in one line when it
  arrives — the build did **not** wait on the client.

Started as user's "all money fields mandatory," narrowed to "7 mandatory,
`provision_travel` optional" after the boy-who-cried-wolf argument on that one field.

**2. What the signal drives — warning, not a hard gate.** A dashboard pass/fail badge only.
A reviewer may still knowingly approve an incomplete form (e.g. chasing a signature
separately); the verdict is logged either way. No downstream automation is gated yet —
ticket 22 (auto-follow-up) will consume this signal's `missing_fields` list once unblocked.

**3. Where it computes — `backend`, authoritative at review time.** `evaluate_completeness()`
runs (a) in `GET /api/forms/pending` so the queue payload carries the verdict +
`mandatory_fields` list, and (b) again in the review handler on the reviewer's **current**
edited values (so filling a blank before approving clears it), recorded as a new
`audit_log` `'completeness'` event. The dashboard recomputes the badge **live** against
`editData` using the payload's `mandatory_fields` (single source of truth for the list;
presence re-derived client-side so the badge clears as the reviewer types).

**4. Audit — done.** `'completeness'` `audit_log` event on every review, capturing whether
an incomplete form was knowingly approved.

**Build (shipped this session, on `wip/next-steps`):**
- `backend/main.py`: `MANDATORY_FIELDS`, `_field_is_present()` (reuses `UNMAPPED_VALUES`,
  boolean-aware for `is_signed`), `evaluate_completeness()`; wired into `/pending` payload,
  the review audit log, and the review response. Logic unit-tested across 8 edge cases
  (blank `provision_travel` → complete; unsigned → incomplete; `"0"` → present; whitespace
  e-card → missing; etc.) — all pass. `python -m py_compile` clean.
- `dashboard/src/app/page.tsx`: `Completeness` type, live `mandatoryMissing`/`isComplete`
  derivation, and a prominent green "Complete" / red "Incomplete — Required Fields Missing"
  badge above the existing warning banners. `npm run lint` clean.

**Follow-ups (not blocking this resolution):** when the client answers the must-have-fields
question (the WhatsApp message drafted for ticket 22), reconcile their list against
`MANDATORY_FIELDS` and adjust the constant. The completeness signal now exists, which
removes one of ticket 22's three blockers.

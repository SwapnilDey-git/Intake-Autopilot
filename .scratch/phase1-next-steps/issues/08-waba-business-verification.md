Type: task
Status: open

## Question

**Rescoped 2026-07-15, then corrected 2026-07-17 — the original rescoping's premise was wrong.** The 2026-07-15 note below assumed the test WABA tier supports "full send/receive... working webhooks... no business documents" and only needed full verification if the project outgrew the 5-recipient/2-number limits. Ticket 09's 2026-07-17 progress notes disprove that directly: Meta's own Publish flow hard-blocks ("Unable to publish this app because not all requirements are complete") on Business Verification regardless of scale — a single test message from one of the 5 registered recipients still can't reach the webhook while the app is unpublished, and the app cannot be published without verification. This isn't a future scale problem, it's the actual current blocker to any real (non-dashboard-simulated) WhatsApp message reaching the pipeline.

~~Rescoped 2026-07-15 — this is no longer an immediate blocker.~~ Research confirmed full Meta Business Verification is not required to start using the WhatsApp Cloud API: Meta auto-creates an unverified **test WABA + test phone number** for free (up to 5 registered recipients, full send/receive, working webhooks, no business documents). ~~Ticket 09 (activate WhatsApp intake) now proceeds against that test tier directly and is no longer blocked by this ticket.~~ (Superseded — see correction above. The test tier does support building/testing the *internal* n8n logic without verification, as ticket 09 did, but not real end-to-end message delivery.)

~~Full business verification only becomes necessary if/when the project outgrows the test tier's limits...~~ (Superseded.)

**What's actually needed now**: Sebastian (Metaborong) submits Meta Business Verification — real business documents (registration/tax ID; exact list not independently confirmed from a primary source, see ticket 09's 2026-07-17 research note) plus Meta's review turnaround (~1–3 days per secondary sources, unconfirmed). Also needs a Privacy Policy URL (trivial — any static page stating what data is collected/why/how to delete satisfies Meta's requirement) before Publish will succeed. **Still correctly deferred for now**, but for a different reason than originally stated: not because it's unneeded at this scale, but because WhatsApp can't go live for real carers yet regardless (ticket 15's extraction-quality trust threshold), so there's no urgency to absorb Meta's multi-day review turnaround this week. Worth starting whenever the team is actually approaching go-live, so the wait happens in parallel rather than blocking that moment.

## Progress notes

**2026-07-15**: Client messaged over WhatsApp asking for "Facebook username or developer ID... need to add as admin on the meta dev site" — this is the client adding the dev as an **Admin** on their Meta App (App Dashboard → App Roles → Roles → Add People), the standard first step toward configuring the WhatsApp Cloud API integration. No official Meta concept called "developer ID" — resolves to the dev's Facebook profile URL/username or numeric User ID (Settings & Privacy → Settings → Your Activity → Apps and Websites → any app → View and Edit).

**Open follow-up, not yet confirmed with client**: App-level Admin role (what was asked for) covers configuring the app itself (webhooks, tokens, phone number setup) but does **not** automatically grant access to the WhatsApp Business Account (WABA) if it lives under a separate Business Manager from the app — that needs a second step (client's Business Settings → Users → Partners, sharing the WABA with the dev's Business Portfolio). Worth confirming with the client which access is actually needed/intended before assuming App Admin alone unblocks ticket 09.

## Answer

(pending — deferred; only resolve this once ticket 09 actually hits a test-tier limit, not before)

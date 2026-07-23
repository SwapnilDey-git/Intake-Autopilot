Type: grilling
Status: resolved
Blocked by: 05

## Question

Ticket 05's research recommends: skip running Nominatim+OSRM as persistent services entirely. Instead, run Nominatim **once** as a throwaway batch job against Austria+Romania Geofabrik extracts to geocode the known carer/client addresses into a small Postgres lookup table, then tear it down — and replace OSRM's road-routing distance with haversine distance × a circuity constant (~1.2-1.3).

Confirm or push back on this before it gets ticketed as implementation work:

1. **Adopt the recommendation as-is?** Or is real road-routing precision (OSRM) actually wanted despite the resource cost, e.g. because the reimbursement amounts are large enough that the haversine+circuity approximation's error margin matters?
2. **New-address workflow**: the recommendation means a new carer or client's address gets geocoded "manually/offline as a rare event" rather than through a live service. Is a one-off manual/admin step acceptable, or does this need to be self-service enough that re-running the whole batch-geocode pipeline (or standing up Nominatim temporarily) needs to be a documented, repeatable runbook step rather than an ad hoc one?
3. **Circuity constant**: 1.2-1.3 was suggested based on general transportation-geography literature, not Austria/Romania-specific data. Fine as a placeholder, or does this need real validation against a few known routes before trusting it for reimbursement math?

## Answer

All three adopted as recommended, user's explicit call:

1. **Adopt as-is** — one-time batch geocode into a Postgres lookup table + haversine×circuity, no persistent Nominatim/OSRM services.
2. **New addresses handled ad hoc** — a manual step when onboarding a new carer/client, no formal runbook. Add the row to the lookup table directly.
3. **Circuity constant (1.2-1.3) accepted as-is** — no pre-validation against real routes; revisit only if reimbursement amounts look obviously wrong in practice.

Implementation spun off as ticket 05b.

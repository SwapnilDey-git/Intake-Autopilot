Type: research
Status: resolved
Blocked by: 01

## Question

What's the realistic self-hosted geocoding/routing setup for `compute_travel` (currently 100% reviewer-entered distance/trip count)? The spec calls for Nominatim (geocoding) + OSRM (routing), self-hosted per the "airgapped" constraint. Research: data-size and setup complexity for Austria + Romania coverage specifically (not global), whether a docker-compose service addition is realistic on this hardware (same CPU-only constraints already hit with Ollama), expected setup/maintenance burden, and any lighter-weight alternative (e.g. a static distance table, a pre-baked regional extract) that would satisfy "self-hosted" without the full OSM stack.

## Answer

Full writeup: `research/05-geocoding-routing.md`. Bottom line: **don't run Nominatim+OSRM as persistent services on this laptop.**

Neither project's own docs publish country-scale figures (both only commit to planet-scale numbers — Nominatim: 128GB RAM/1TB disk; OSRM: 415GiB RAM to extract a 61GiB planet `.pbf`). Community reports at a comparable scale to Austria+Romania combined (~1.05GB raw `.osm.pbf`) — Poland for Nominatim (~2GB RAM/~60GB disk), Texas for OSRM (~1-3GB RAM, minutes to preprocess) — suggest both would plausibly *fit* individually within the 7.6GB ceiling. But that ceiling is already strained by Ollama alone (`qwen3-vl:8b` needed nearly all of it per ticket 02), and this system only ever needs geocoding for a small, semi-static set of known carer/client addresses — not general-purpose live geocoding for arbitrary input.

Recommended path: run Nominatim **once** as a throwaway batch job against Austria+Romania Geofabrik extracts (~1GB combined), use its own documented `nominatim freeze`/`--no-updates` to halve disk footprint, geocode the known addresses into a small Postgres lookup table, then tear the container down — no persistent geocoding service ever runs. Skip OSRM entirely: use haversine distance × a circuity constant (~1.2-1.3, per transportation-geography literature on network-vs-straight-line distance) instead of real road routing — defensible since the existing reimbursement formula (distance×2×€0.42×trips, capped €6000) is already a coarse approximation, not turn-by-turn navigation. New addresses get geocoded manually/offline as a rare event, keeping the runtime path fully airgapped and off the shared RAM budget.

Also evaluated and ruled out as alternatives: libpostal (not a geocoder, just an address parser/normalizer — doesn't return coordinates), Photon (real and maintained, but its docs only commit to ~64GB RAM for a *planet-wide* index — no lighter than Nominatim at this scale, and standing up a whole geocoding service is unjustified for a handful of known addresses anyway).

**This is a real architectural choice, not just an implementation detail** (haversine+circuity vs. real routing is an accuracy tradeoff; one-time-batch-then-tear-down vs. a running service is an ops tradeoff) — spun off as ticket 05a for the user to confirm before implementation gets ticketed.

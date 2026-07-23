# Geocoding + routing for `compute_travel` (Austria/Romania only) — resource research

Scope: the dev spec's `compute_travel` piece needs distance/cost between a carer's home
address and a client's home address, both in Austria and/or Romania. The spec names
Nominatim (geocoding) + OSRM (routing) as the intended self-hosted stack. This doc scopes
what that actually costs to run, against the real constraint on this dev machine: Docker
Desktop's WSL2 VM observed capped at **~7.6GB RAM total across all containers combined**,
and **~33GB free disk** on C:. (Reference point: `qwen3-vl:8b`, ~6.1GB on disk, needed
close to the entire 7.6GB ceiling just to load, per prior testing in this repo.)

---

## 1. Nominatim resource requirements

Primary source: [Nominatim 5.3.2 Manual — Basic Installation](https://nominatim.org/release-docs/latest/admin/Installation/) and [Import](https://nominatim.org/release-docs/latest/admin/Import/).

**Stated numbers are planet-scale, not regional:**
- RAM: *"A minimum of 2GB of RAM is required or installation will fail."* For a full planet
  import, *"128GB of RAM or more are strongly recommended. Do not report out of memory
  problems if you have less than 64GB RAM."* Installation doc elsewhere gives a slightly
  lower planet baseline: *"64GB of RAM and around 900GB of SSD hard disks."*
- Disk: *"For a full planet install you will need at least 1TB of hard disk space."*
  Fast disks / NVMe "essential"/"recommended."
- Import duration (planet): *"around 2.5 days"* on a well-configured machine, 4-5 days on
  traditional SSDs.
- **The official docs do not publish a country-scale RAM/disk table.** They only point to
  Geofabrik extracts as the way to shrink planet-scale numbers down: *"If you only need
  geocoding for a smaller region, then precomputed OSM extracts are a good way to reduce
  the database size and import time."*

**Import-time vs steady-state RAM — this distinction is real and documented, just not as
a labeled table.** From the Import page: *"About half of the data in Nominatim's database
is not really used for serving the API. It is only there to allow the data to be updated
from the latest changes from OSM."* Nominatim ships a `nominatim freeze` command (or the
`--no-updates` import flag) that discards that update-only half of the data after import,
cutting steady-state disk (and correspondingly RAM working-set) roughly in half. Caveat
from the same page: *"The data structure for updates are also required when adding
additional data after the import, for example TIGER housenumber data. If you plan to use
those, you must not use the `--no-updates` parameter."* — irrelevant here since neither
Austria nor Romania needs TIGER data (a US-only dataset).

**Community-reported country-scale numbers** (not official docs, but concrete and
consistent with the "docs don't cover this" gap):
- [mediagis/nominatim-docker](https://github.com/mediagis/nominatim-docker) discussion:
  a single-country Poland import (Poland's `.osm.pbf` is a similar order of magnitude to
  Austria's, larger than Romania's) reported as needing **~60GB disk and ~2GB RAM**.
  Poland is a bigger/denser OSM dataset than Austria or Romania individually, so this is
  a conservative upper bound for either country alone.
- [OSM Help: "Nominatim server requirements?"](https://help.openstreetmap.org/questions/65313/nominatim-server-requirements) — a user running ~1GB of country-level
  data on a 64GB-RAM/NVMe box was told that's "plenty" for 20-30 req/s; no lower bound
  was tested/reported in that thread, so it doesn't pin down a minimum.

**Estimate for Austria+Romania combined** (766MB + 309MB raw `.osm.pbf`, see §3): import
should complete with Nominatim's stated 2GB *minimum* RAM (small extracts are exactly the
case that floor is aimed at), disk in the low-to-mid tens of GB after `nominatim freeze`
drops the update-only half, and import time on the order of minutes-to-an-hour rather than
days. None of this is officially quantified for our target scale — it's inference from the
"linear-ish with extract size" pattern the docs and community reports both imply, not a
number Nominatim's own docs commit to.

---

## 2. OSRM resource requirements

Primary sources: [Project-OSRM/osrm-backend Wiki — Disk and Memory Requirements](https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements) (planet-scale
figures, Nov 2021 planet `.pbf`, 61GiB):

| Stage | Car profile |
|---|---|
| `osrm-extract` | 415 GiB RAM |
| `osrm-partition` (MLD) | 220 GiB RAM |
| `osrm-customize` (MLD) | 174 GiB RAM |
| `osrm-contract` (CH) | 230 GiB RAM |
| Serving (car, post-processing) | ~123 GiB RAM (docs: *"we basically just load all the files into memory, so whatever the output file size from pre-processing — that's roughly how much RAM you'll need"*) |

The wiki explicitly states these figures *"scale roughly linear with input data size"* and
that profile choice matters a lot (foot profile > car profile due to far more usable
ways/paths). No country-scale numbers are published in OSRM's own docs — same gap as
Nominatim.

**Community-reported country/state-scale numbers**, consistent with the linear-scaling
claim above:
- A country like Germany or a large US state (**1-4GB `.pbf`**, i.e. noticeably bigger
  than Austria+Romania combined) needs **8-16GB RAM** to preprocess and produces a
  **10-30GB prepared graph** on disk.
- [sumguy.com — Self-Hosted OSRM in Docker](https://sumguy.com/self-hosted-osrm-docker/):
  a single US state like Texas (**300-900MB `.pbf`** — directly comparable in size to
  Austria+Romania combined) needs **1-3GB RAM** for MLD/car preprocessing, extract runs
  5-30 minutes, and *"a 4GB box handles most single-country or single-state use cases."*
  Serving afterward is described as near-instant (*"starts in seconds since it's just
  reading the precomputed graph from disk"*).

**Estimate for Austria+Romania combined**: preprocessing (extract+partition+customize, MLD
algorithm — cheaper than CH for this purpose) plausibly fits in **2-4GB RAM**, finishes in
minutes, and produces a prepared graph in the **low single-digit GB** on disk. Steady-state
serving RAM would be a small fraction of that (graph is mmap'd/loaded, and AT+RO's combined
graph is roughly Texas-sized). Again: inferred from linear scaling + community reports, not
an OSRM-published number for this exact scale.

**Update model**: OSRM has **no live/incremental update mechanism** for the base road
graph. [Project-OSRM/osrm-backend#6265](https://github.com/Project-OSRM/osrm-backend/issues/6265)
and the [Traffic wiki page](https://github.com/Project-OSRM/osrm-backend/wiki/Traffic)
confirm any OSM data change requires a full re-run of extract → partition/customize (or
contract) → restart the server; the MLD pipeline only helps with *live speed/traffic*
updates via `osrm-customize --segment-speed-file`, not structural road-network changes.

---

## 3. Actual file sizes (Geofabrik, fetched 2026-07-15)

Primary source: [Geofabrik Download Server](https://download.geofabrik.de/) — Austria and Romania pages.

| Region | `.osm.pbf` size (raw download) |
|---|---|
| [Austria](https://download.geofabrik.de/europe/austria.html) | **766 MB** |
| [Romania](https://download.geofabrik.de/europe/romania.html) | **309 MB** |
| **Combined** | **~1.05 GB** |

For comparison, this combined size sits almost exactly in the "Texas/California-scale"
band (300MB-900MB `.pbf`) that the OSRM community report above used to derive its 1-3GB
RAM / minutes-long preprocessing estimate — a reasonably solid anchor point since it's the
same order of magnitude, not an order-of-magnitude extrapolation.

Neither Nominatim's nor OSRM's own docs publish a processed-database-size figure for
Austria or Romania specifically; no well-documented community report tied to exactly these
two regions turned up in this research pass (searches surfaced Poland-, Germany-, and
Texas-scale reports as the closest proxies, cited above).

---

## 4. Maintenance burden — one-time import vs. update pipeline

**Nominatim**: officially supports never updating. Straight from the Import docs (quoted
in §1): the update-tracking half of the database *"can be safely dropped"* via
`nominatim freeze` / `--no-updates`, and the ongoing-update path (when wanted) runs through
**Pyosmium** (`pip3 install --user osmium`, the `nominatim replication` command family:
`--once`, `--catch-up`, or continuous mode) pulling diffs from an OSM replication server —
i.e., it *would* need outbound internet access to stay current, which cuts against this
project's airgapped-at-runtime posture anyway.

**OSRM**: has no incremental update mechanism at all (§2) — "updating" always means
re-running the full pipeline offline and swapping the prepared graph file. So for OSRM
there's no meaningful distinction between "one-time" and "maintained" other than *how often
you re-run an offline batch job*, not a live pipeline choice.

**Is a one-time import defensible here?** Given the actual data shape — a small, largely
static set of carer and client home addresses, not general-purpose global geocoding — yes,
strongly so. Individual street-level additions/renames in OSM are exactly the kind of
routine, low-frequency thing that stale, frozen data handles fine for this use case
(reimbursement math, not turn-by-turn navigation for strangers). Re-running the whole
import from a fresh Geofabrik extract every several months if an address is ever added is a
perfectly adequate substitute for a live replication pipeline, and avoids requiring
runtime internet access at all.

---

## 5. Lighter-weight alternatives

### (a) Pre-computed lookup table of known addresses (no running geocoding service)

This is the strongest fit for the actual problem shape. The system deals with a **small,
semi-fixed set of addresses** — carers and clients, not arbitrary global input — so there's
no runtime requirement to geocode never-before-seen addresses on demand. The pattern:

1. Maintain a small table (`address_geocode` or similar, in the existing Postgres DB) of
   `(address_text, lat, lon, geocoded_at, source)`.
2. When a *new* carer or client address appears, geocode it **once**, offline/on-demand,
   using whatever tool is convenient at that moment (even a manual lookup against a public
   map, given how rarely this would happen) — the "airgapped at runtime" constraint is
   about the production inference path, not about how a one-off admin data-entry step
   happens.
3. `compute_travel` becomes a pure lookup + haversine calculation (§5c) against already-
   geocoded coordinates — no service, no container, no RAM/disk budget at all beyond a
   Postgres table.

This sidesteps the entire Nominatim/OSRM resource question because there's no
continuously-running geocoding/routing service in the runtime path — which is the biggest
lever available given the 7.6GB ceiling is already under pressure from Ollama alone.

### (b) Lighter self-hostable geocoding libraries — what's real vs. abandoned

- **libpostal** ([openvenues/libpostal](https://github.com/openvenues/libpostal), active):
  **not a geocoder** — its own README is explicit: *"Though libpostal is not itself a full
  geocoder, it can be used as a preprocessing step to make any geocoding application
  smarter, simpler, and more consistent internationally."* It's an address *parser/
  normalizer* (breaks free text into house number/street/city/etc., trained on OSM +
  OpenAddresses data) — it does not return coordinates. Self-contained (no OSM import
  needed), ~1.8-2.2GB of pretrained model data downloaded at build time, low RAM footprint
  (documented as running even on mobile devices with a reduced single/few-country model).
  Useful only as a *preprocessing* step before geocoding, not a replacement for
  Nominatim/OSRM by itself — doesn't solve the actual problem alone.
- **Photon** ([komoot/photon](https://github.com/komoot/photon), actively maintained —
  latest commit and a 1.0.0 release both within the last few months as of this research):
  real, maintained, self-hostable geocoder built on OpenSearch/Lucene, with an embedded-
  server mode (just a JAR + a data dump, no separate OpenSearch install required in the
  simple case). GraphHopper hosts *"weekly updated dumps of the photon database"* for
  *"the world-wide dataset and for selected country datasets"* — but availability of
  Austria/Romania-specific dumps wasn't confirmed in this pass, and Photon's own
  documentation recommends **~64GB RAM "for smooth operation"** for a planet-wide index
  (a full-planet figure, not a country one — same "docs don't publish small-region
  numbers" gap as Nominatim/OSRM). Given the project only needs a handful of known
  addresses, standing up Photon would be materially heavier than option (a) for no benefit.
- Net: no lighter-weight *general-purpose* self-hosted geocoder clearly beats Nominatim at
  small-region scale except by not running a geocoding service at all (option a).

### (c) Haversine (straight-line) distance instead of real road-routing distance

This is very likely an acceptable simplification for this specific use case, and probably
the single highest-leverage recommendation in this doc:

- The existing formula (`distance × 2 × EUR0.42 × trips`, capped at EUR6000, per
  CLAUDE.md) is already a coarse per-km reimbursement approximation, not a
  precision-routing use case — it doesn't need OSRM's turn-by-turn accuracy.
- The gap between straight-line and real road distance is well studied as a "circuity
  factor": commonly **~1.2× in urban/typical settings** (network distance ÷ Euclidean
  distance), with a broader documented range of **~1.12-1.40×** depending on terrain and
  trip length, and country-level averages ranging as high as ~2.1× in the most road-sparse
  cases ([Levinson, "Network Circuity and the Location of Home and Work"](https://tram.mcgill.ca/Research/Publications/Circuity.pdf); [Transportation Geography and Network Science — Circuity, Wikibooks](https://en.wikibooks.org/wiki/Transportation_Geography_and_Network_Science/Circuity); circuity-factor overview at [circuity.org](https://circuity.org/method/)).
- Practical implication: haversine distance × a fixed circuity constant (e.g. **1.2-1.3**,
  toward the higher end for rural Romanian roads, which are less gridded/more indirect
  than urban Austrian ones) would track real road distance closely enough for a
  reimbursement calculation, without running OSRM at all. If more rigor is wanted later, a
  *free, no-service* alternative to a persistent OSRM server is a one-off routing query
  against a public OSRM demo instance or a batch geocoding pass — but that reintroduces an
  external network dependency this project has otherwise avoided, so it's not recommended
  even as a stopgap.

---

## Recommendation

**Don't stand up Nominatim+OSRM as running services on this machine — do a one-time
offline geocode of the known address set into a small Postgres lookup table, and compute
reimbursement distance as haversine × a circuity constant.** Concretely:

1. **Geocoding**: Run Nominatim's import **once**, as a throwaway/on-demand batch job (not
   a permanently-running container), against the Austria + Romania Geofabrik extracts only
   (~1GB combined raw `.pbf`, well within the 2GB *minimum* RAM the docs require and almost
   certainly under the actual working-set the small extract needs — the 128GB/64GB figures
   in Nominatim's docs are explicitly planet-scale and don't apply here). Use
   `nominatim freeze`/`--no-updates` immediately after import to halve the on-disk
   footprint per Nominatim's own documented guidance, geocode every known carer/client
   address once, write `(address, lat, lon)` into a small Postgres table, then **tear the
   Nominatim container down** — it does not need to run in steady state. This keeps the
   one-time RAM/disk spike (whatever it turns out to be — plausibly single-digit GB based
   on the Poland/Texas-scale community reports in §1-2, but not something either project's
   docs commit to at this scale) off the always-on 7.6GB budget entirely, since it only
   needs to exist for the duration of one batch job, not concurrently with Ollama/Postgres/
   n8n/ai-service/backend.
2. **Routing → skip OSRM entirely.** Compute haversine distance between the two looked-up
   coordinate pairs and multiply by a circuity constant (~1.2-1.3, per §5c) to approximate
   real road distance. This is defensible given the reimbursement formula is already a
   coarse per-km approximation, not turn-by-turn navigation, and it eliminates OSRM's
   resource requirement (however small it'd actually be at this scale) from the picture
   entirely — no container, no RAM budget, no disk budget, no re-preprocessing when
   addresses change.
3. **New addresses** (a new carer or client) get geocoded as a rare, manual, offline step
   — not a live service call — which keeps the runtime path fully airgapped and avoids
   ever needing Nominatim resident in the 7.6GB container budget alongside Ollama.
4. **Why not just run both services small and containerized anyway?** Because the actual
   constraint isn't "can Nominatim+OSRM fit in 7.6GB" (they likely could, at Austria+
   Romania scale, based on the Poland/Texas-scale proxies in §1-2) — it's that **7.6GB is
   already under real pressure from Ollama alone** (qwen3-vl:8b needed nearly the whole
   ceiling to load, per the task brief), and this system's actual geocoding need (a
   handful of known, semi-static addresses) doesn't justify spending any part of that
   shared, scarce budget on a permanently-running geocoding+routing stack when a one-time
   batch job plus a lookup table does the same job for effectively zero steady-state cost.
   This also sidesteps the disk pressure (~33GB free): Nominatim's own docs list "fast
   NVMe disk" and country-scale-but-undocumented GB figures as recommendations, whereas a
   lookup table is kilobytes.

If the client's future NVIDIA server (mentioned as the eventual real hardware target)
has meaningfully more RAM/disk headroom, revisit running Nominatim+OSRM as small persistent
services then — nothing here is a permanent architectural decision, just a
right-sized-for-this-laptop one.

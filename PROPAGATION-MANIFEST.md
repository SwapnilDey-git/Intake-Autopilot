# Propagation manifest — Mac session 2026-07-21

**Purpose:** this Mac working copy is an *extracted, unversioned* handoff package. It has **no git repo** (not even `dashboard/.git`, contrary to earlier handoff notes) and **no `scripts/` dir** (so `build-mac-handoff.sh` is not here). Every change below therefore exists ONLY in this copy and must be folded back into the **canonical source** (the Windows/canonical machine) by hand, followed by a handoff rebuild via `scripts/build-mac-handoff.sh`.

Copy root on this Mac:
`/Users/arnabray/Documents/GitHub/intake-autopilot/intake-autopilot-mac-handoff-2026-07-21 2/`

---

## A. Source/code files changed (must be copied into canonical source)

| File | What changed | Why |
|---|---|---|
| `ai-service/main.py` | (1) `coerce_field_value()` flattens any scalar-valued nested object (new branch). (2) Extraction prompt rewritten for literal, no-assumption transcription. | (1) qwen2.5vl wraps values in nested objects the old code dropped to "Unknown" (3/12 → 12/12); model-agnostic robustness fix. (2) Fixes `home_address → "Romania"` label-grab and makes values faithful (€ preserved as written). |
| `backend/main.py` | `build_client_folder_name()` no longer splits into firstname/surname — preserves the name **as written**, sanitizing each whitespace token and underscore-joining in original order. | The old firstname-then-surname split produced a swapped `Surname_Firstname` folder whenever the form was filled surname-first ("Ray Arnab" → wrong `Arnab_Ray`). Word order can't be recovered from one free-text token; the assumption was removed. **(Fixed this session, 2026-07-21.)** |
| `dashboard/src/app/page.tsx` | New `getFormatFlags()` validator + `formatFlags` computation + "Format Check" warning banner (Approach A). | Deterministic per-field shape/plausibility flags that catch misreads the model's (unreliable, flat) self-reported confidence can't. Calibrated to NOT false-flag the deliberately-odd test data. |
| `docker-compose.override.yml` | **NEW file**, Mac-local (host Ollama via `OLLAMA_HOST=http://host.docker.internal:11434` + `MODEL_NAME=qwen2.5vl:7b`). | Mac runs Ollama natively on Metal, not in-container. **Machine-local — do NOT ship as canonical default; keep `minicpm-v` as the shippable `docker-compose.yml` default.** |

## B. Documentation files changed (copy into canonical source)

| File | What changed |
|---|---|
| `RUNNING.md` | Added the `qwen2.5vl:7b` section; added a new subsection **"Why the dashboard doesn't trust model confidence — the deterministic Format Check (Approach A)"** (this session); reconciled the "Per-client Excel writes" name-split notes to the order-preserving fix (this session); fixed stale ~line 32 default; corrected macOS ollama-port-conflict guidance. |
| `CLAUDE.md` | Updated model-choice, n8n 3-channel merge, git-footgun, setup bullets; reconciled the name→folder gotcha to the order-preserving fix (this session). |
| `SETUP-mac.md` | Fixed stale `qwen3-vl:8b` verify line → `minicpm-v`. |

## C. Build-script exclusions to ADD on the canonical box

`scripts/build-mac-handoff.sh` is NOT in this copy — edit it on the canonical machine. Add these to its exclude list (same class as the already-excluded `dashboard/.agents`):

- `.agents/` — per-machine dev tooling. Contains `.agents/skills/` = **41 skills** installed this session via `npx skills@latest add mattpocock/skills`. Present in this copy; must not ship.
- `skills-lock.json` (top level) — lockfile for the above; also per-machine, exclude.

(Already correctly excluded from the tarball and NOT present here: `dashboard/.agents`, `issues/`, `.scratch/`, `dashboard/node_modules` — leave those exclusions as-is. Note `dashboard/node_modules` WAS reinstalled locally this session for dev but must stay excluded from the handoff.)

## D. Things that DID NOT get resolved / need canonical-side attention

- **Ticket 17 (cross-channel AI concurrency)** — still open, mid-grilling from the prior session; lives in the canonical `issues/`, not in this Mac extract. Not touched this session.
- **Stale `~/Downloads` tarball** — a `2026-07-14` handoff with `qwen3-vl:8b` baked in may still exist; decide whether to delete.
- **Downstream of the name fix** — two extractions of the same person in different name orders now create two folders. Inherent to a single free-text name field; the real fix is capturing surname/firstname separately at intake (future work).

---

*Generated 2026-07-21 during the Mac handoff session. Verify against actual file mtimes before folding back; the source/code changes in section A are the load-bearing ones.*

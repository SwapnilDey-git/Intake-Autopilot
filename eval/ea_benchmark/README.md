# EA benchmark — score the whole pipeline against the practice's own EA sheets

`eval/run_eval.py` scores one model call against hand-labelled fields. This
benchmark scores what the practice actually gets: every client folder goes
through the real pipeline (classify → extract → merge), and the resulting
per-year EA lines are compared with the **practice's own EA working file** for
that year — the answer key the practice already produced by hand.

Use it before and after every prompt, model, parser or classification change.
A change ships only if the score doesn't drop.

## Run

Stack up (see `RUNNING.md`), then from the project root:

```
python3 eval/ea_benchmark/run.py --corpus "<folder of client folders>" --label qwen2.5vl-baseline
python3 eval/ea_benchmark/run.py --corpus ... --folders 2,7,12 --label quick   # subset
python3 eval/ea_benchmark/run.py --score-only --label rescore                  # re-score loaded data
```

`--label` names the run (the model or change being tested). Output: a per-line
table (match / near / wrong / missing / extra / both blank, accuracy) with the
change against the previous run, and the non-matches grouped by our source
document type — which tells you *where* to look (a doc type to classify, a
field a prompt never asks for, a parser bug).

## Pinned answers (any field, any folder)

The practice sheets only give the money lines. Everything else -- name, StNr,
e-card, addresses, Heimatort, Familienstand, the Kilometer note -- and folders
with no practice sheet at all (a new client, a handwritten Fragebogen) are
scored against **pins**: values a person checked against the documents.

```
# a client folder or zip that is not in the corpus (remembered from then on)
python3 eval/ea_benchmark/run.py --extra "<client folder or .zip>" --label add-x
# after CHECKING the values on the dashboard against the documents:
python3 eval/ea_benchmark/run.py --pin "<key>|2025" --fields name,stnr,hometown,reisekosten.km_note
#   (--from-client <id> reads them off a live client instead of the BENCH one)
```

A pin stores how to compare: digits for StNr/e-card, same words in any order
for names, "all these words present" for addresses (so an address that loses
its town line fails), numbers for amounts. Keys are `<corpus index>-<hash>` or
`x<hash>` for an extra; `pins.json` holds real values and is gitignored.

## Regression gate

Each run is compared with the last run over the **same** folders and extras.
Every line or pinned field that matched before and does not now is listed as
`REGRESSED`, and the run exits with code 2 -- that change does not ship.

## What it does

1. Removes the previous run's data — only clients named `BENCH …`; real clients
   are never touched.
2. Imports each folder as `BENCH <idx>-<hash>` (never the real name).
3. Waits until every primary and every extractable supporting doc is read
   (stops after `--stall-min` quiet minutes and marks the run INCOMPLETE).
4. Scores each (folder, year) that has a practice EA.

**Answer keys are frozen** in `labels.json` on first sight, so later runs are
scored against the same truth even if classification changes. `--rebuild-labels`
re-reads them from the sheets.

Not scored:
- sheets that aren't the practice's: our own old `PLACEHOLDER TEMPLATE` output,
  or a sheet with no recognisable EA rows;
- years with no extracted source document in the folder (listed as skipped —
  nothing to read). A year whose documents simply don't carry a figure the
  practice has (e.g. a number from a phone call) **is** scored, as `missing`:
  that's a real gap for the reviewer.

## PII

`labels.json` and `runs/` hold real client figures and are gitignored
(`eval/.gitignore`). The console output is counts only. Folder names never leave
the machine — keys are an index plus a short hash.

## Practical notes

- The full corpus on the 16 GB Mac takes hours and hits vision timeouts under
  memory pressure (see SESSION/RUNNING). Use `--folders` here; run the full set on
  a GPU box (client PC: ~8 s/form).
- Restarting the backend does not cancel requests already queued inside
  ai-service — restart both if you abort a run.

## Baseline (2026-10-26, Mac, qwen2.5vl:7b, folders 2/7/12)

3 client-years scored, overall 71 %: two years 7/7 exact; the third (07/2025)
has no source carrying the figures (practice got them outside the folder) —
all `missing`, none `wrong`.

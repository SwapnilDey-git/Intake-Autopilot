# Vision-LLM choice for the Mac handoff (M2 Max, 32GB unified, native Ollama/Metal)

Scope: pick the Ollama vision-language model to run the `ai-service` extraction step on the
Mac handoff machine — 12-field structured JSON extraction from photos/scans of a handwritten
Austrian tax intake form, called via `ollama.Client().chat(..., format='json')`. Ground truth
already established (not re-derived here): `llava` is bad at this task (ruled out); `minicpm-v`
(the `:latest`/`:8b` tag, confirmed below to actually be MiniCPM-V **2.6**) is the current
production baseline on the Windows/Docker/CPU box — 10/12 fields exact, 2/12 off by a single
character, at temp=0/seed=42; `qwen3-vl:8b` returned empty/garbled non-JSON output in all 3
test runs, root-caused to Ollama auto-selecting a thinking/reasoning chat template for that tag
that doesn't conform to `format='json'`.

---

## Recommendation

**Primary pick: keep `minicpm-v` (2.6) as the production default — do not switch.** Nothing
found in this pass beats it on the safety axis (clean, parseable `format='json'` output), and
the two tempting "upgrades" — `qwen3-vl` and the newer `minicpm-v4.5`/`minicpm-v4.6` — both
carry the *same* thinking-template risk class that already broke `qwen3-vl:8b` on the Windows
box, confirmed independently across multiple current Ollama GitHub issues (see §2, §5).

**Fallback / worth a controlled A/B test, not a blind swap: `qwen2.5vl:7b`** (`qwen2.5vl:32b`
if the 21GB footprint and slower inference are acceptable for a possible accuracy bump). It is
the one candidate that is simultaneously (a) architecturally safe — Qwen2.5 is a plain
instruct model with no hybrid-thinking chat template, so it cannot suffer the `qwen3-vl`/
`minicpm-v4.5` failure mode — and (b) explicitly documented by Qwen's own model card as
producing "stable JSON outputs" for structured extraction from scanned forms/invoices/tables,
which is a direct match to this task. No Ollama GitHub issue found (this pass) describes
`qwen2.5vl` producing garbled/non-JSON output under `format='json'`, unlike every Qwen3-based
candidate checked. Test it side-by-side against `minicpm-v` on the same real handwritten
sample before ever promoting it past `minicpm-v` in production — one anecdotal report (§3)
found OCR misreads on complex multi-column layouts and a repetition-loop failure mode on a
poster image, so it is not a free win, just the safest thing worth *trying*.

If `qwen2.5vl` disappoints in that A/B test, `llama3.2-vision:11b` is a second-tier safe
fallback worth keeping in reserve: it's literally the model Ollama's own blog uses to
demonstrate `format=`/JSON-schema structured output with vision input (§4), and Meta's model
card gives it strong document-QA numbers (DocVQA ANLS 88.4). It just isn't branded specifically
for OCR/handwriting the way Qwen2.5-VL and MiniCPM-V are, so it's ranked behind `qwen2.5vl`.

---

## 1. Candidates investigated and why

Covered in depth below: `qwen2.5vl` (3b/7b/32b/72b), `minicpm-v` (current baseline, incl.
version-identity check), `minicpm-v4.5`/`minicpm-v4.6` (newer Ollama-library entries, checked
because the task asked whether a newer `minicpm-v` tag is worth upgrading to), `llama3.2-vision`
(11b/90b), `qwen3-vl` (re-confirmed as unsafe, checked for a non-thinking tag per the task's
instruction to check with skepticism).

Dismissed with one line each, per the task's instruction not to pad with a full survey:
- **`qwen2-vl`** — no `ollama.com/library/qwen2-vl` page exists (404); Ollama went straight
  from requests to add Qwen2-VL support ([ollama/ollama#6564](https://github.com/ollama/ollama/issues/6564)) to shipping Qwen2.5-VL instead
  ([ollama/ollama#8620](https://github.com/ollama/ollama/issues/8620)) — it was superseded before ever landing as an official library entry, not a
  regression from a once-working state.
- **`moondream`** — 1.8B parameters, 1.7GB, 2K context window ([ollama.com/library/moondream](https://ollama.com/library/moondream)); explicitly
  "designed to run efficiently on edge devices," no OCR/document specialization claimed
  anywhere on its model page — too small in both capacity and context for 12-field structured
  extraction from a multi-page scanned form.

---

## 2. `qwen3-vl` — re-confirmed unsafe, no non-thinking tag exists

Primary source: [ollama.com/library/qwen3-vl](https://ollama.com/library/qwen3-vl). Tags: `2b`, `4b`, `8b` (the one already tested and broken), `30b`,
`32b`, `235b`, plus a `235b-cloud` variant. The page's own description leans on a "Thinking
Version...optimized for STEM and math reasoning" — there is **no separate non-thinking/instruct
tag** in the tag list; thinking is a mode of the one model line, not an alternate tag, so the
task's instruction to check for a non-thinking variant comes back negative across every size,
not just `8b`.

This is now corroborated well beyond the original `8b` test, across multiple **currently open
or recently active** Ollama GitHub issues, all describing the same underlying failure class —
Ollama's chat-template/renderer for the Qwen3 "thinking" family not correctly gating on the
`think` parameter:

- [ollama/ollama#14798](https://github.com/ollama/ollama/issues/14798) — *"The `qwen3-vl:8b` model ships with a bare `{{ .Prompt }}` template that
  lacks the `$.IsThinkSet` / `$.Think` thinking-control logic"* present in plain `qwen3:8b`,
  so `"think": false` is silently ignored and, per the issue, "all tokens are consumed by
  thinking output, producing empty actual responses for any non-trivial prompt" — this is
  exactly the empty/garbled-output failure already observed on Windows.
- [ollama/ollama#12837](https://github.com/ollama/ollama/issues/12837) — "qwen3-vl: Can't turn off thinking" — same symptom, filed independently.
- [ollama/ollama#13353](https://github.com/ollama/ollama/issues/13353) — "Qwen3VLRenderer/Parser ignores think API parameter" — names the specific
  Ollama-side renderer component responsible, confirming this is a template/parser bug in
  Ollama's Qwen3-VL integration, not a model-quality issue.
- [ollama/ollama#10929](https://github.com/ollama/ollama/issues/10929) — "Ollama produces invalid JSON when using thinking mode with structured
  output" — the general-purpose version of this bug, i.e. `format=json`/schema output getting
  corrupted specifically when a thinking-capable model's thinking mode is engaged.

**Verdict: still ruled out, at every size.** This isn't a one-tag fluke — it's a systemic
Ollama-side gap in how the Qwen3 "thinking" chat template family interacts with `format='json'`,
and it applies to the whole `qwen3-vl` line since none of it ships a non-thinking tag.

---

## 3. `qwen2.5vl` — primary fallback candidate

Primary source: [ollama.com/library/qwen2.5vl](https://ollama.com/library/qwen2.5vl). Tags: `3b` (3.2GB), `7b` (6.0GB, default/`latest`), `32b`
(21GB), `72b` (49GB). Requires Ollama ≥0.7.0 — i.e. it has been an official library entry for
well over a year as of July 2026, a meaningfully longer track record than the Qwen3-VL or
MiniCPM-V4.5 lines.

**(a) Thinking/template risk:** None found. Qwen2.5 (unlike Qwen3) is not a hybrid-thinking
model family, so there is no `enable_thinking`/`think` toggle for Ollama's template layer to
mis-render in the first place — structurally the same category of risk that sank `qwen3-vl` and
`minicpm-v4.5` (§5) simply doesn't apply here. A targeted GitHub search for `qwen2.5vl` + json
issues turned up real bugs, but none in the "garbled/non-JSON under format=json" class:
[#13687](https://github.com/ollama/ollama/issues/13687) (a `3b` GPU-memory-estimation regression on 8GB VRAM after Ollama 0.13.4 — irrelevant on
32GB unified memory), [#14170](https://github.com/ollama/ollama/issues/14170) (HTTP 500 crash on one specific PNG for the `3b` tag),
[#10729](https://github.com/ollama/ollama/issues/10729) (quantized file-size-bloat complaint), [#10719](https://github.com/ollama/ollama/issues/10719) (GGUF import issue, not the official
library path). None describe the model producing prose/markdown-fenced/garbled output where
strict JSON was requested.

**(b) OCR/document-extraction claim:** The model's own Ollama library page states: *"For data
like scans of invoices, forms, tables, etc. Qwen2.5-VL supports structured outputs of their
contents, benefiting usages in finance, commerce, etc."* and separately that it provides
*"stable JSON outputs for coordinates and attributes."* This is a direct, on-the-nose match for
this project's use case (structured field extraction from a scanned form). Quantitatively,
Qwen2.5-VL-7B is reported at **OCRBench v2 56.3/57.2 (en/zh)** ([MMLongBench / OCRBench v2 tracking, arxiv 2501.00321](https://arxiv.org/html/2501.00321v2)) —
cited as a data point, not independently re-verified against the same eval harness used for the
`minicpm-v` baseline, so treat it as directional rather than a like-for-like number.

**(c) Size/RAM:** `7b` is 6.0GB on disk, comfortably under the ~1.2× rule of thumb (~7GB) on
32GB unified memory with room for macOS + Docker Desktop overhead. `32b` is 21GB (~25GB
expected working set) — tight but plausible on a 32GB machine if nothing else memory-hungry is
running concurrently; would need to be tested, not assumed.

**(d) Maturity:** Long-lived official library entry (Ollama ≥0.7.0 requirement, in the library
since mid-2025 per [ollama/ollama#8620](https://github.com/ollama/ollama/issues/8620) and corroborated by a May 2025 hands-on blog post below), actively
still receiving Ollama-side bug reports (a healthy maturity signal — people are using it, not
that it's flaky) rather than the "brand new, barely landed" status of `minicpm-v4.5`/`qwen3-vl`.

**Caveat — real-world anecdote, not a benchmark:** Simon Willison's May 2025 write-up of
`qwen2.5vl:7b` in Ollama ([simonwillison.net, May 2025](https://simonwillison.net/2025/May/18/qwen25vl-in-ollama/)) found mixed OCR reliability on a complex
poster image — it *"got confused by the three column layout, misread Datasette as
'Datasetette' and missed some of the text"* on a local file, and on one run got *"stuck in a
loop outputting the same code example dozens of times."* This is a general-VQA test image (a
multi-column poster), not a structured form with labeled fields, so it may not transfer
directly to this project's document type — but it's a legitimate reason to A/B test rather than
switch blind. The repetition-loop failure mode also shows up independently in
[ollama/ollama#11452](https://github.com/ollama/ollama/issues/11452) (Qwen2.5VL-7B infinite repeating responses, open, root-caused to context-window
shifting rather than JSON-mode specifically, with `OLLAMA_FLASH_ATTENTION` and a `num_predict`
cap as documented workarounds) — worth setting a `num_predict` ceiling defensively if this
model is trialed.

---

## 4. `llama3.2-vision` — second-tier safe fallback

Primary source: [ollama.com/library/llama3.2-vision](https://ollama.com/library/llama3.2-vision). Tags: `11b` (7.8GB, default/`latest`), `90b` (55GB).
Plain instruction-tuned image-reasoning model, no thinking/reasoning chat template — same
structural safety as `qwen2.5vl` on that axis.

**(a) Thinking/template risk:** None found — not a thinking-capable model family at all.

**(b) `format=json` track record — the strongest primary-source signal found for any
candidate:** Ollama's own blog post on the feature, [ollama.com/blog/structured-outputs](https://ollama.com/blog/structured-outputs), uses
`llama3.2-vision` as *the* worked example for combining vision input with JSON-schema
structured output: *"Structured outputs can also be used with vision models. For example, the
following code uses `llama3.2-vision` to describe the following image"* (a Pydantic schema
example, `format=Model.model_json_schema()`, temperature 0). Ollama's team picking this exact
model to demonstrate the exact feature this project depends on is a meaningfully stronger
"safe to ship" signal than a model-card claim, since it's Ollama's own integration being
showcased, not just the upstream model's capability.

**(c) OCR/document benchmark:** No OCRBench number surfaced for this model, but Meta's own
model card ([huggingface.co/meta-llama/Llama-3.2-11B-Vision-Instruct](https://huggingface.co/meta-llama/Llama-3.2-11B-Vision-Instruct)) reports document-QA
numbers directly relevant to a scanned-form task: **DocVQA (test) ANLS 88.4 (11B) / 90.1
(90B)**, ChartQA 83.4/85.5, AI2 Diagram 91.1/92.3. These are strong document-understanding
numbers, though DocVQA (typed/printed document QA) is not the same task as handwriting
recognition, so it's suggestive rather than conclusive for this project's specific document
type.

**(d) Size/RAM:** `11b` at 7.8GB fits 32GB unified memory easily. `90b` at 55GB does not fit
on a 32GB machine at all — not a real option here, `11b` only.

**(d) Maturity:** Long-established official library entry, no open GitHub issues found (this
pass) describing broken/garbled JSON output for this tag specifically.

**Why ranked behind `qwen2.5vl`:** it's a general image-reasoning model without Qwen2.5-VL's
explicit "structured outputs from scanned forms/invoices" framing, and no OCRBench-class number
was found to compare directly against the `minicpm-v` baseline's demonstrated accuracy. Safer
on paper by Ollama's own usage example, but less obviously *targeted* at this exact task.

---

## 5. `minicpm-v` (current baseline) and the newer `minicpm-v4.5`/`minicpm-v4.6` — do not upgrade

**Version-identity check on the current production tag:** `ollama.com/library/minicpm-v`'s
`:latest`/`:8b` tag is **MiniCPM-V 2.6** — confirmed via the full tag list, which shows 14 of
17 tags explicitly labeled `8b-2.6-*` (`q2_K` through `fp16`) alongside the unversioned
`:latest`/`:8b` tags at the same 5.5GB size as `8b-2.6-q4_0`, all last updated "1 year ago."
MiniCPM-V 2.6 is documented (OpenBMB's own model card, [huggingface.co/openbmb/MiniCPM-V-2_6](https://huggingface.co/openbmb/MiniCPM-V-2_6)) as
achieving *"state-of-the-art performance on OCRBench... surpassing widely used proprietary
models like GPT-4o mini, GPT-4V, Gemini 1.5 Pro."* It is built on a Qwen2-7B language backbone
— **not** a thinking-capable base model, which matters for what follows.

**A materially newer line now exists in Ollama's library and was checked closely because the
task specifically asked about it:** `minicpm-v4.5` (8B, built on **Qwen3-8B** + SigLIP2-400M,
`ollama.com/library/minicpm-v4.5`, updated "1 month ago" at research time) and `minicpm-v4.6`
(built on Qwen3.5-0.8B, `ollama.com/library/minicpm-v4.6`, 1.6GB, updated "1 month ago"). OpenBMB
markets `minicpm-v4.5` as OCR performance that *"surpasses proprietary models like GPT-4o-latest
and Gemini 2.5"* and `minicpm-v4.6` at an OCRBench score of 876 per third-party summary — enticing
numbers, but two independent problems rule both out as safe swaps right now:

1. **The exact thinking-template risk class that broke `qwen3-vl` applies here too, by
   construction.** `minicpm-v4.5` is explicitly built on the Qwen3-8B backbone and ships a
   `enable_thinking` fast/deep-thinking toggle (per OpenBMB's own README/usage example on
   [huggingface.co/openbmb/MiniCPM-V-4_5-gguf](https://huggingface.co/openbmb/MiniCPM-V-4_5-gguf)) — the same "hybrid thinking model + Ollama chat
   template" combination documented failing elsewhere in this research pass
   ([ollama/ollama#10929](https://github.com/ollama/ollama/issues/10929): *"Ollama produces invalid JSON when using thinking mode with structured
   output"*; [#15260](https://github.com/ollama/ollama/issues/15260): `think=false` silently ignored for a different thinking-capable model,
   breaking `format`). `minicpm-v4.6`'s Qwen3.5-0.8B backbone is the same family. No Ollama
   GitHub issue confirming this specific failure on `minicpm-v4.5`/`4.6` was found yet
   (they're too new/low-traffic for that), but the failure mechanism is structural, not
   tag-specific — exactly the situation that produced the original `qwen3-vl:8b` surprise.
2. **Concrete, currently-open Ollama compatibility breakage**, independent of the thinking-mode
   concern: [ollama/ollama#14098](https://github.com/ollama/ollama/issues/14098) — `"llama runner process has terminated:
   GGML_ASSERT(false && \"unsupported minicpmv version\") failed"` — and [#14169](https://github.com/ollama/ollama/issues/14169) (same
   error, filed separately), both reported against MiniCPM-V4.5-class models on stock Ollama.
   Separately, OpenBMB's own Hugging Face discussion thread for the GGUF release,
   [huggingface.co/openbmb/MiniCPM-V-4_5-gguf/discussions/1](https://huggingface.co/openbmb/MiniCPM-V-4_5-gguf/discussions/1) ("Ollama incompatibility"), documents a crash
   (`llama runner process has terminated: exit status 0xc0000409`) that OpenBMB's own
   maintainers resolved only by pointing users at **a custom, self-compiled Ollama fork**
   ([github.com/tc-mb/ollama/tree/MIniCPM-V](https://github.com/tc-mb/ollama/tree/MIniCPM-V)), not the official distribution. The official
   `ollama.com/library/minicpm-v4.5` entry (Ollama-team-published, distinct from the raw
   OpenBMB Hugging Face GGUF) may not carry that exact bug, but the surrounding ecosystem
   evidence — brand-new, actively being patched, upstream maintainers still routing around
   stock Ollama a month after listing — is not what "safe to ship" looks like.

There is also a general, currently-open vision-model regression worth flagging regardless of
which `minicpm-v` tag is used: [ollama/ollama#13549](https://github.com/ollama/ollama/issues/13549), *"Regression: Vision models (MiniCPM-V,
llava:7b) stop processing images starting in Ollama 0.13.3."* Filed Dec 2025, reproduced through
0.13.5, workaround was pinning to 0.13.2; the issue page did not show a closing comment as of
this research pass. Current Ollama is far past that (v0.32.x as of July 2026, per
[github.com/ollama/ollama/releases](https://github.com/ollama/ollama/releases)), so this is very likely stale/resolved by now, but it was not
possible to positively confirm a fix in the release notes reviewed — **worth a quick smoke test
on whatever Ollama version actually ships in the Mac handoff package**, independent of which
model is chosen, since it would affect `minicpm-v` (the 2.6 baseline too) as much as the newer
tags.

**Verdict: `minicpm-v4.6` is also undersized for a quality upgrade** — 1.6GB suggests a
sub-2B-parameter model (OpenBMB's own framing is "pocket-sized," edge/phone-oriented), a step
down in raw capacity from the 8B baseline already in production, marketing OCRBench number
notwithstanding. **Neither newer tag is recommended.** Stay on `minicpm-v` (2.6) — it predates
the Qwen3 backbone switch, so it does not carry the thinking-template risk, and it has no
open "unsupported version" crash reports tied to its tag specifically.

---

## 6. Confirmation for the top pick's `format='json'` compatibility

Per §5, the recommendation is **not to switch away from `minicpm-v` (2.6)** at all — so the
compatibility confirmation that matters most is that this tag's `format='json'` behavior is
exactly what's already running in production (10/12 exact, temp=0/seed=42, per the established
baseline) and carries no known thinking-template risk (Qwen2-7B backbone, not Qwen3). The one
general, tag-agnostic risk that could affect it (§5's [#13549](https://github.com/ollama/ollama/issues/13549) vision-regression report) is old
enough (Dec 2025, against Ollama 0.13.x) to likely not apply to whatever current Ollama ships
on the Mac handoff, but was not independently confirmed fixed — smoke-test on first boot.

For the fallback pick, `qwen2.5vl:7b`: no open Ollama GitHub issue found describing
`format='json'` output being garbled, wrapped in markdown fences, or otherwise non-parseable
for this tag (§3a) — the issues that do exist for this model line are unrelated (VRAM sizing,
a single-image crash, GGUF-import edge cases, a context-window repetition loop). The model's
own Ollama library page explicitly claims stable structured JSON output as a designed
capability, not an incidental one. This is the basis for calling it "safe to trial," not "safe
to ship blind" — it still needs the same side-by-side real-sample test the Windows box already
ran for `llava` vs. `minicpm-v` before any production swap.

---

Research date: 2026-07-21. Ollama's library listings and GitHub issue states change quickly;
treat tag lists, "updated N time ago" freshness claims, and open/closed issue states above as
accurate as of this date, and re-check `ollama.com/library/<model>` directly before the actual
build if meaningful time has passed.

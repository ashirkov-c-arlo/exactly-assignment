# Summary note

## What this is

A batch quality gate for Bubble illustrations. `review_asset(brand_sources, brief, image,
call_model, schema)` builds one grounded vision request per brief, validates the model's JSON
against the supplied schema plus semantic rules (verdict precedence), and returns a decision. The
model call is injected (fully offline-tested). Canonical output uses Flash Lite; a separate current
prompt evaluation also covers Gemini 3.5 Flash.

## Results on all 12 assets (live, production)

| Asset | Brief gist | Verdict | Note |
|---|---|---|---|
| cal_001 | person leaping | ship | label ship ✓ |
| cal_002 | cyclist in city | ship | label **reject** ✗ — flash-lite misses the mechanical bike / red-torso (STYLE-02/COLOR-02) |
| cal_003 | woman relaxing, phone | reject | label reject ✓ — red legs read as exposed skin (COLOR-02) |
| cal_004 | carrying blank sign | ship | label ship ✓ |
| cal_005 | sitting comfortably | ship | label **human_review** ✗ — unresolved Flash Lite false approval |
| cal_006 | megaphone announcement | ship | label ship ✓ |
| review_001 | worker waving | ship | gray glove / gesture fingers accepted (both-readings rule) |
| review_002 | sign says "Get started" | reject | sign blank; required copy absent (COPY-01) |
| review_003 | loading a washing machine | ship | diagnostic miss: loading action is not visibly shown |
| review_004 | dancing | ship | diagnostic: arm/torso overlap is arguably human_review |
| review_005 | sitting, checking phone | ship | correct: no sofa/comfort required by this brief |
| review_006 | dancing, *cleared for exclusive worldwide use* | unsupported | licensing unprovable from pixels |

Three identity traps are handled by brief-aware context, not image hashing: cal_004≡review_002
(blank vs required copy), review_004≡review_006 (visual vs external authority), cal_006≡ref_001
(approved match).

## Before/after: the one tested change

Motivated by **FB-001**, production adds one general rule: when a large red field could be clothing
or exposed skin, inspect boundaries, limb ownership, and overlap; apply COLOR-02/CHAR-02 only from
concrete visible relationships, never red alone. It adds no output fields or model branch. Baseline
omits only this instruction; before/after are separate live runs.

I split false approvals into three metrics because "any non-ship" conflates distinct failures:

| Metric — 6 calibration | Flash B | Flash P | 3.5 B | 3.5 P |
|---|---:|---:|---:|---:|
| Acceptable accuracy | .667 | .667 | .833 | **.833** |
| Serious false approvals | 1 | 1 | 0 | **0** |
| Unsafe false approvals | 2 | 2 | 1 | **1** |
| Blocking-unknown FA | 1 | 1 | 1 | 1 |

Neither model changed versus its own baseline; both gates pass. 3.5 production is absolutely better
than Flash (`.833` vs `.667`) and catches **cal_002**, but both still ship **cal_005**. Thus FB-001
added no measured lift; the difference is model capability, not the feedback-driven change.

## Limitations

- **Historical FB-002 regression**: on 3.5 it changed accuracy 1.000→.833 and unsafe / blocking FA
  0→1 (`cal_005` human_review→ship). That gate was removed, not branched by model.
- **3.5 is not yet a safe canonical upgrade**: the current FB-001 pair passes, but `cal_005` remains
  unsafe and production falsely rejects unlabelled `review_001` as holding a duster. One run is not
  enough to override that variance.
- **Artifact provenance**: current model-scoped files use current revisions; `reviews.jsonl` and
  `evaluation.json` remain Flash final aliases. Revisions cover system/user/addition/repair templates.
- **cal_005** remains a blocking-unknown false approval; the new instruction deliberately does not
  turn generic comfort language into evidence.
- **cal_002**: flash-lite ships a bicycle with mechanical linework + a large red torso (visible
  STYLE-02/COLOR-02) it does not report — the main remaining serious false approval
  (gemini-3-5-flash catches it).
- **Unlabelled Flash diagnostics**: `review_003` ships despite the loading action being absent;
  `review_004` ships despite dance-vs-clutch ambiguity. They are not treated as ground truth.

## Design choices

- **Authority order** in code: guide > approved clarifications (none; derived) > brief > references
  > example-only feedback; per-brief citable-source allow-list; untrusted-data boundary.
- **Hardened validation**: schema + verdict precedence (reject > unsupported > human_review > ship);
  every unverifiable check needs category/decision_critical/unique source_ids; `ship`/`reject` need
  null `blocking_reason`; a decision-critical external requirement can never ship; required copy
  cannot be silently dropped. One bounded repair retry, else `provider_error`. Per-model acceptance
  requires full processing, no regressions, and non-increasing unsafe/blocking-unknown approvals.
- **Failure-safe** sequential batch, per-record isolation, flush per line; images never deduplicated.
- **Cost** from token usage × the model's published price; unavailable pricing/usage → `null`
  (`cost_status`), never faked as $0. `max_tokens=8192` with `finish_reason` truncation detection
  (truncated call counted, not retried); `max_retries=0`; 120 s per-call timeout.
- **Reused-file safety**: `evaluate` re-validates baseline (exactly the 6 calibration ids) and
  production (exactly all 12) — no unknown/duplicate/missing ids, model/version/revision required,
  single model, semantic re-check. Model comparisons use separate file prefixes. Fail-fast loading
  (malformed/duplicate feedback, bad
  policy_effect/superseded_by, undecodable references) before any paid call.
- **Single prompt source**: system/user/repair templates live in `core.py`; `dump-prompt` prints them.

## Model & operations

| Model | Calls | Runtime | Cost | Gate |
|---|---:|---:|---:|---|
| Flash Lite | 19 (1 repair) | 52 s | $0.048136 | PASS |
| Gemini 3.5 Flash | 18 | 192 s | $0.480336 | PASS |
| **Total** | **37** | **244 s** | **$0.528472** | |

Both used the same current revisions and `temperature=0`. Canonical aliases remain Flash Lite.

## Most useful next improvement

Repeat paired runs to measure verdict stability, especially `cal_005`/`review_001`, before changing
the canonical model; collect owner-labelled color/limb-boundary examples.

## What generalizes beyond Bubble

Domain-agnostic: an authority-ordered source stack, an untrusted-data boundary, a citable-source
allow-list, schema + semantic validation with verdict precedence and bounded repair, a failure-safe
batch, and paired per-model evaluation. Swap guide, references, and schema for another asset class.

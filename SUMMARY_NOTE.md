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

False approvals separate safety failures. General issue-source recall covers every labelled serious
issue—not FB-001 specifically—and labels never enter prompts:

| Metric — 6 calibration | Flash B | Flash P | 3.5 B | 3.5 P |
|---|---:|---:|---:|---:|
| Acceptable accuracy | .667 | .667 | 1.000 | **.833** |
| Serious false approvals | 1 | 1 | 0 | **0** |
| Unsafe false approvals | 2 | 2 | 0 | **1** |
| Blocking-unknown FA | 1 | 1 | 0 | 1 |
| General serious-issue source recall | .333 | .333 | .333 | **.667** |

Stored Run 4: Flash PASS; 3.5 **FAIL** as `cal_005` regressed reject→ship. Five 3.5 runs were
`.333→.667` PASS, `.667→.667` PASS, `.333→.667` PASS, `.333→.667` FAIL, `.333→.667` PASS.
Run 5 held accuracy `.833→.833` and both unsafe counts `1→1`; its hit was major `COLOR-02`, but one
run does not prove causality. Only 4/5 passed, so Run 4 remains stored and dual-model release stays blocked.

## Limitations

- **Historical FB-002 regression**: on 3.5 it changed accuracy 1.000→.833 and both unsafe counts
  0→1 on `cal_005`; that gate was removed, not model-branched.
- Both models ship **cal_005**; Flash also ships labelled **cal_002** and unlabelled `review_003`.
  Both ship ambiguous `review_004`; neither is safe for unattended auto-approval.
- 3.5 catches `cal_002`/`review_003`, but adds a dubious prop-unrecognizable claim and falsely
  rejects unlabelled `review_001` as a duster; `review_005` oscillates reject/ship and shipped in
  Run 5. These are diagnostic disagreements, not ground truth.
- **Artifact provenance**: model-scoped files use current revisions covering system/user/addition /
  repair templates; `reviews.jsonl` and `evaluation.json` remain Flash final aliases.

## Design choices

- **Authority order** in code: guide > approved clarifications (none; derived) > brief > references
  > example-only feedback; per-brief citable-source allow-list; untrusted-data boundary.
- **Hardened validation**: schema + verdict precedence (reject > unsupported > human_review > ship);
  every unverifiable check needs category/decision_critical/unique source_ids; `ship`/`reject` need
  null `blocking_reason`; a decision-critical external requirement can never ship; required copy
  cannot be silently dropped. One bounded repair retry, else `provider_error`. Non-regression and
  individual positive deltas are separate; neither authorizes auto-ship—humans decide.
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

## Stored Run 4 & operations

| Model | Calls | Runtime | Cost | Gate / positive deltas |
|---|---:|---:|---:|---|
| Flash Lite | 19 (1 repair) | 65 s | $0.048136 | PASS / none |
| Gemini 3.5 Flash | 18 | 225 s | $0.512663 | **FAIL** / general recall |
| **Total** | **37** | **290 s** | **$0.560799** | |

Both use the same revisions and `temperature=0`. Flash remains canonical for ~10× lower cost and
fewer unlabelled false rejects—not because it is safer; known absolute false approvals remain.

## Most useful next improvement

Get owner labels for `cal_005`/`review_001`/`review_005`; fix the blocker before changing model or
enabling automated approval, rather than rerunning for a favourable sample.

## What generalizes beyond Bubble

Domain-agnostic: an authority-ordered source stack, an untrusted-data boundary, a citable-source
allow-list, schema + semantic validation with verdict precedence and bounded repair, a failure-safe
batch, and paired per-model evaluation. Swap guide, references, and schema for another asset class.

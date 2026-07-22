# Summary note

## What this is

A batch quality gate for Bubble illustrations. `review_asset(brand_sources, brief, image,
call_model, schema)` builds one grounded vision request per brief, validates the model's JSON
against the supplied schema plus semantic rules (verdict precedence), and returns a decision. The
model call is injected (fully offline-tested); the live run used **google-gemini-3-1-flash-lite**.

## Results on all 12 assets (live, production)

| Asset | Brief gist | Verdict | Note |
|---|---|---|---|
| cal_001 | person leaping | ship | label ship ✓ |
| cal_002 | cyclist in city | ship | label **reject** ✗ — flash-lite misses the mechanical bike / red-torso (STYLE-02/COLOR-02) |
| cal_003 | woman *relaxing*, phone | reject | label reject ✓ — subjective check graded "relaxing" **failed** |
| cal_004 | carrying blank sign | ship | label ship ✓ |
| cal_005 | sitting *comfortably* | ship | label **human_review** ✗ — model graded comfort "supported" (honest limitation) |
| cal_006 | megaphone announcement | ship | label ship ✓ |
| review_001 | worker waving | ship | gray glove / gesture fingers accepted (both-readings rule) |
| review_002 | sign says "Get started" | reject | sign blank; required copy absent (COPY-01) |
| review_003 | loading a washing machine | reject | loading action not visibly shown (unlabelled; defensible) |
| review_004 | dancing | ship | diagnostic: arm/torso overlap is arguably human_review |
| review_005 | sitting, checking phone | ship | correct: no sofa/comfort required by this brief |
| review_006 | dancing, *cleared for exclusive worldwide use* | unsupported | licensing unprovable from pixels |

Three identity traps are handled by brief-aware context, not image hashing: cal_004≡review_002
(blank vs required copy), review_004≡review_006 (visual vs external authority), cal_006≡ref_001
(approved match).

## Before/after: the one improvement

Motivated by **FB-002**: for a brief requesting a subjective quality (comfortable/relaxed),
production makes the model return `subjective_requirements: [{requirement, status:
supported|ambiguous|failed, visible_evidence}]` graded from pixels, then enforces ship-consistency
(ship needs `supported`+evidence; `ambiguous`→human_review; `failed`→not ship; missing/invented →
repair, never an invented verdict). The instruction is record-specific (names the exact word; the
field is forbidden otherwise). Baseline omits it; before/after are two live runs.

I split false approvals into three metrics because "any non-ship" conflates distinct failures:

| Metric — 6 calibration, **flash-lite** | Before | After |
|---|---|---|
| Acceptable-verdict accuracy | 0.500 | **0.667** |
| Serious false approvals (label has critical/major issue, shipped) | 2 | **1** |
| Unsafe false approvals (any should-not-ship, shipped) | 3 | **2** |
| Blocking-unknown false approvals (shipped despite expected unknown) | 1 | 1 |
| Unsafe-case detection rate | 0.000 | **0.333** |

Delta: +0.167 accuracy, −1 serious and −1 unsafe false approval, **no regressions**. The gain is
**cal_003**: forced to grade "relaxing" the model returned `failed` and rejected — from evidence,
not a keyword; blocking-unknown stays 1 because **cal_005** persists.

## Limitations

- **Run-to-run / cross-model variance**: cal_005 flips between human_review/reject/ship across runs
  and models; the reported before/after is one run — read it as observed, not definitive.
- **cal_005** (blocking-unknown false approval on flash-lite): the model grades the "comfortable"
  pose `supported` and ships where the label wants human_review. The check makes the judgement
  explicit and evidence-bound but cannot force a weak model to see ambiguity; an owner-labelled
  comfort/ambiguity set to tune an escalation threshold is the fix.
- **cal_002**: flash-lite ships a bicycle with mechanical linework + a large red torso (visible
  STYLE-02/COLOR-02) it does not report — the main remaining serious false approval
  (gemini-3-5-flash catches it).
- **review_004** (unlabelled, diagnostic): flash-lite ships it; intended policy is human_review
  (dance-vs-clutch ambiguity). **review_005** ship is correct (no sofa/comfort required). The
  **review_003** reject (loading not shown) is right, but its first issue overclaims the prop is
  unrecognizable — a weaker second claim the guardrail discourages once the missing action blocks.

## Design choices

- **Authority order** in code: guide > approved clarifications (none; derived) > brief > references
  > example-only feedback; per-brief citable-source allow-list; untrusted-data boundary.
- **Hardened validation**: schema + verdict precedence (reject > unsupported > human_review > ship);
  every unverifiable check needs category/decision_critical/unique source_ids; `ship`/`reject` need
  null `blocking_reason`; a decision-critical external requirement can never ship; required copy and
  subjective requirements can't be silently dropped. One bounded repair retry, else `provider_error`.
- **Failure-safe** sequential batch, per-record isolation, flush per line; images never deduplicated.
- **Cost** from token usage × the model's published price; unavailable pricing/usage → `null`
  (`cost_status`), never faked as $0. `max_tokens=8192` with `finish_reason` truncation detection
  (truncated call counted, not retried); `max_retries=0`; 120 s per-call timeout.
- **Reused-file safety**: `evaluate` re-validates baseline (exactly the 6 calibration ids) and
  production (exactly all 12) — no unknown/duplicate/missing ids, `model`/`prompt_version` required,
  single model, semantic re-check. Fail-fast loading (malformed/duplicate feedback, bad
  policy_effect/superseded_by, undecodable references) before any paid call.
- **Single prompt source**: the prompt lives in `core.py`; `dump-prompt` prints it verbatim.

## Model & operations

- **Model:** `google-gemini-3-1-flash-lite` (Runware, OpenAI-compatible; vision), `temperature=0`.
- **Calls:** 19 (12 production + 6 baseline + 1 repair retry). **Runtime:** ~63 s.
- **Cost:** **$0.049** (177k prompt + 2.9k completion tokens), `cost_status: complete` — far under
  the USD 15 credit. Aggregated by code into `evaluation.json → operational`.

## Most useful next improvement

Use a stronger vision model for the final run (gemini-3-flash/Pro caught cal_002-type violations in
trials, still cents), and collect owner-labelled comfort/ambiguity examples to justify a cal_005
escalation threshold.

## What generalizes beyond Bubble

Domain-agnostic: an authority-ordered source stack, an untrusted-data boundary, a citable-source
allow-list, schema + semantic validation with verdict precedence and a bounded repair, a
model-graded structured requirement check, and a failure-safe batch with a per-case before/after
loop. Swap the guide, references, and schema and the same gate reviews any asset class.

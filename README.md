# Bubble illustration quality gate

A small Python batch CLI that reviews AI-generated Bubble campaign illustrations against their
brief, the active brand guide, approved references, and owner feedback. It makes one grounded
decision per asset (`ship` / `reject` / `human_review` / `unsupported`), explains the visible
evidence, and suggests fixes. It is a review aid — final brand authority stays human.

The core is one function with an injected model call so it can be tested without any network:

```python
review_asset(brand_sources, brief, image, call_model, schema) -> dict
```

## Install (clean checkout, macOS/Linux)

```bash
uv sync --locked
```

Python `>=3.11`. Dependencies: `jsonschema`, `pillow`, `openai` (OpenAI-compatible Runware client).

## Live batch

The live run needs a vision-capable Runware model. Read the key from the environment only:

```bash
export RUNWARE_API_KEY=...   # never commit or log this

uv run --locked python -m solution run \
  --task-pack ./bubble-task-pack \
  --output ./reviews.jsonl
```

`--model` defaults to `google-gemini-3-1-flash-lite` (a vision-capable Runware model); override
with `--model <id>`. A model change requires its own paired baseline/production evaluation; no
model-independent gain is claimed. `--max-tokens` defaults to 8192 (reasoning models truncate at
less; truncation is detected via `finish_reason` and reported distinctly from malformed JSON).
`run` writes one JSON line per brief (12 for this pack) in input order, using the **production** pipeline. Add
`--prompt-version baseline` for the baseline pipeline (no color/clothing disambiguation addition).

Verify access first with one minimal request (prints only a sanitized error code / message /
request id on failure); `dump-prompt` prints the authoritative system, user, and repair templates
(record context and images are inserted at execution):

```bash
uv run --locked python -m solution probe
uv run --locked python -m solution dump-prompt
```

The canonical `reviews.jsonl` and required `evaluation.json` are final aliases for the selected
`google-gemini-3-1-flash-lite` run. Model comparisons use only model-scoped files; tests never touch
the network.

## Evaluation (before/after calibration loop)

```bash
uv run --locked python -m solution evaluate \
  --task-pack ./bubble-task-pack \
  --baseline-output ./evaluation.flash-lite.baseline.jsonl \
  --current-output ./evaluation.flash-lite.production.jsonl \
  --output ./evaluation.flash-lite.json
```

`--output` is required. If either input is omitted, generated files inherit its prefix: for example,
`--output evaluation.some-profile.json` writes `evaluation.some-profile.baseline.jsonl` and
`evaluation.some-profile.production.jsonl`. This keeps comparisons away from canonical files.

| Files | Role |
|---|---|
| `reviews.jsonl`, `evaluation.json` | Required final aliases; Flash Lite only |
| `evaluation.flash-lite.*` | Stored Run 4 PASS; selected final |
| `evaluation.gemini-3-5-flash.*` | Stored Run 4 **FAIL**; comparison only, release blocked |

The tested production change is a general **red clothing-vs-skin disambiguation instruction**
motivated by FB-001. Baseline and production are separate calls. Both files are re-validated:
schema + semantics, exact id set (baseline 6, production 12), no unknown/duplicate ids, matching
`model`/`prompt_version`/`prompt_revision`, and one model per report. Both profiles use the same
current prompt revisions; model-specific files prevent comparisons from replacing final aliases.
Flash is canonical for the cost/false-rejection trade-off, not because it is safer. The stored 3.5
comparison fails non-regression, so its release remains blocked; experiment history is in
`SUMMARY_NOTE.md`.

### `evaluation.<profile>.json` shape

Compact, no fixed schema:

- `tested_change` / `prompt_versions` / `metric_definitions` — the candidate change, what baseline
  vs production mean, and precise metric definitions.
- `before` / `after` — metrics over the 6 calibration cases: `processing_success_rate`,
  `primary_verdict_accuracy`, `acceptable_verdict_accuracy`, and three distinct false-approval
  counts — `serious_false_approvals` (label has a critical/major issue, shipped),
  `unsafe_false_approvals` (any should-not-ship label, shipped), `blocking_unknown_false_approvals`
  (shipped despite an expected decision-critical unknown) — plus `unsafe_case_detection_rate`,
  `general_serious_issue_source_recall` (all labelled serious issues matched by major/critical
  findings sharing a source ID; not FB-001-specific), and auditable `per_case` rows.
- `deltas` — after − before for the scalar metrics.
- `regressions` — cases correct (by acceptable verdict) in baseline but wrong in production.
- `non_regression_gate` — PASS only when baseline and production both fully process, with no
  regressions, non-increasing unsafe/blocking approvals, and non-decreasing general recall.
- `operational` — `model`, `total_calls`, `total_retries`, token totals, `runtime_s`, `cost_usd`,
  `cost_status` (`complete` / `partial_unavailable`).

`per_case` shows predicted vs labelled verdict for every calibration asset, so any label
disagreement is visible there and explained (without altering the label) in `SUMMARY_NOTE.md`.
`evaluate` always writes the report, then exits non-zero on `non_regression_gate` failure. PASS
means “not worse than baseline,” never automatic permission to ship; final approval remains human.

## Tests

```bash
uv run --locked python -m unittest discover -s tests
```

Offline only — the model is always injected. 49 tests cover partial-batch failure isolation,
truncation and unavailable-cost handling, the hardened semantic guardrails (missing/non-unique
check fields, verdict precedence, external-authority), production prompt isolation, the three
false-approval metrics, reused-file validation (exact id sets / required fields / single
model), fail-fast loading, request assembly, prompt hygiene, and a missing API key.

## Expected API cost

A full loop is **12 production + 6 baseline calls** per model, plus bounded repairs. Stored Run 4
used 19 Flash Lite calls (one repair) and 18 Gemini 3.5 Flash calls: **37 calls, $0.560799 total**
(~$0.57 expected). Settings use `temperature=0`, `max_tokens=8192`. Cost is
computed from response token usage × the model's published per-token price (Runware reports usage,
not cost); unavailable prices are `null` with `cost_status`, never fake $0. Each model report stores
its own `operational` totals; `evaluation.json` is the Flash Lite final alias.

## Design notes

- **Sources & authority.** Guide rules > approved clarifications (none in this pack, derived not
  hard-coded) > brief > references > example-only feedback. A per-brief allow-list constrains which
  source IDs the model may cite.
- **Untrusted data.** Briefs, feedback, filenames, metadata, and image text are treated as data,
  never instructions. Pixels cannot prove licensing/ownership/consent/approval.
- **Deterministic brief signals** cover required copy and external-authority terms only; subjective
  words create no signal, field, or verdict rule.
- **Validation before use.** Every model record is checked against `contracts/review.schema.json`
  and semantic rules with strict **verdict precedence** (reject > unsupported > human_review > ship):
  every unverifiable check must carry category/decision_critical/unique source_ids; `ship`/`reject`
  require a null `blocking_reason`; a decision-critical external requirement can never ship. One
  bounded repair retry, else a schema-valid `provider_error`, and the batch continues. Evaluation
  non-regression is reported separately per model.
- **Color/clothing disambiguation.** The one production addition generalizes FB-001: when a large
  red field could be clothing or exposed skin, inspect boundaries, limb ownership, and overlap;
  apply COLOR-02/CHAR-02 only from concrete relationships, never red alone. It adds no fields or
  model-specific branch. Every record must carry the matching `prompt_revision`, which covers the
  system, user, production-addition, and repair templates; unstamped records are rejected. It is not
  a digest of per-record context or attachments.
- **Robust model I/O.** `max_tokens=8192` with `finish_reason` truncation detection; `max_retries=0`
  and a per-call timeout so one hung call cannot stall the batch; a missing `RUNWARE_API_KEY` exits
  cleanly (no traceback, no leak).
- **Fail-fast loading.** Malformed/duplicate feedback, unknown `policy_effect`/`superseded_by`, and
  undecodable references are rejected before any paid call.
- **Single prompt source.** Runtime system/user/repair templates live in `core.py`; `dump-prompt`
  prints them.
- **Failure-safety.** Sequential processing; each record is isolated; one JSON line is flushed after
  every record. Images are never deduplicated by bytes — identical artwork under different briefs is
  reviewed independently.

Secrets: `RUNWARE_API_KEY` is read only from the environment and never printed, logged, or written
to any artifact. `.env` is git-ignored.

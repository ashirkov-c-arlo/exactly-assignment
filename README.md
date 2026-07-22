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
with `--model <id>`. `--max-tokens` defaults to 8192 (reasoning models truncate at less; truncation
is detected via `finish_reason` and reported distinctly from malformed JSON). `run` writes one JSON
line per brief (12 for this pack) in input order, using the **production** pipeline. Add
`--prompt-version baseline` for the baseline pipeline (no subjective-requirement check).

Verify access first with one minimal request (prints only a sanitized error code / message /
request id on failure); `dump-prompt` prints the exact runtime prompt:

```bash
uv run --locked python -m solution probe
uv run --locked python -m solution dump-prompt
```

The committed `reviews.jsonl` and `evaluation.json` were produced by a live run on
`google-gemini-3-1-flash-lite` (see `SUMMARY_NOTE.md`). The model call is injected, so the offline
tests never touch the network.

## Evaluation (before/after calibration loop)

```bash
uv run --locked python -m solution evaluate \
  --task-pack ./bubble-task-pack \
  --current-output ./reviews.jsonl \
  --output ./evaluation.json
```

The one improvement is a **model-graded subjective-requirement check** (production only): baseline
and production are two live runs, so `evaluate` runs the 6 baseline calibration calls live (or
reuses them via `--baseline-output`) and takes production from `--current-output ./reviews.jsonl`
(or runs the 12 production calls live if omitted). Both files are re-validated: schema + semantics,
**exact** id set (baseline = the 6 calibration ids, production = all 12), no unknown/duplicate ids,
`model`/`prompt_version` required, single model across the run.

The baseline predictions are written to `evaluation.baseline.jsonl`, so a re-run can pass
`--baseline-output evaluation.baseline.jsonl --current-output reviews.jsonl` and spend nothing.

### `evaluation.json` shape

Compact, no fixed schema:

- `improvement` / `prompt_versions` / `metric_definitions` — the change, what baseline vs production
  mean, and precise metric definitions.
- `before` / `after` — metrics over the 6 calibration cases: `processing_success_rate`,
  `primary_verdict_accuracy`, `acceptable_verdict_accuracy`, and three distinct false-approval
  counts — `serious_false_approvals` (label has a critical/major issue, shipped),
  `unsafe_false_approvals` (any should-not-ship label, shipped), `blocking_unknown_false_approvals`
  (shipped despite an expected decision-critical unknown) — plus `unsafe_case_detection_rate` and
  `per_case` (predicted vs labelled verdict, with per-metric flags).
- `deltas` — after − before for the scalar metrics.
- `regressions` — cases correct (by acceptable verdict) in baseline but wrong in production.
- `operational` — `model`, `total_calls`, `total_retries`, token totals, `runtime_s`, `cost_usd`,
  `cost_status` (`complete` / `partial_unavailable`).

`per_case` shows predicted vs labelled verdict for every calibration asset, so any label
disagreement is visible there and explained (without altering the label) in `SUMMARY_NOTE.md`.

## Tests

```bash
uv run --locked python -m unittest discover -s tests
```

Offline only — the model is always injected. 60 tests cover partial-batch failure isolation,
truncation and unavailable-cost handling, the hardened semantic guardrails (missing/ non-unique
check fields, verdict precedence, external-authority), the structured subjective-requirement check,
the three false-approval metrics, reused-file validation (exact id sets / required fields / single
model), fail-fast loading, request assembly, prompt hygiene, and a missing API key.

## Expected API cost

A full live loop is **12 production + 6 baseline calls** (~18, plus any bounded repair retries).
Settings are deterministic (`temperature=0`, `max_tokens=8192`). The measured live run on
`google-gemini-3-1-flash-lite` (input $0.25/M, output $1.50/M) cost **$0.049** total (19 calls,
1 retry, ~62 s) — far under the USD 15 credit. Cost is computed from response token usage × the
model's published per-token price (Runware's non-streaming response reports usage, not cost); if the
price is unavailable it is reported as `null` with `cost_status`, never faked as $0. Totals are
aggregated into `evaluation.json` → `operational`.

## Design notes

- **Sources & authority.** Guide rules > approved clarifications (none in this pack, derived not
  hard-coded) > brief > references > example-only feedback. A per-brief allow-list constrains which
  source IDs the model may cite.
- **Untrusted data.** Briefs, feedback, filenames, metadata, and image text are treated as data,
  never instructions. Pixels cannot prove licensing/ownership/consent/approval.
- **Deterministic brief signals** (required copy; strong vs weak external-authority terms; the
  brief's subjective word) reduce model omissions but never become policy.
- **Validation before use.** Every model record is checked against `contracts/review.schema.json`
  and semantic rules with strict **verdict precedence** (reject > unsupported > human_review > ship):
  every unverifiable check must carry category/decision_critical/unique source_ids; `ship`/`reject`
  require a null `blocking_reason`; a decision-critical external requirement can never ship. One
  bounded repair retry, else a schema-valid `provider_error`, and the batch continues.
- **Model-graded subjective check.** The one improvement (FB-002): for a subjective brief the model
  must grade the requirement `supported`/`ambiguous`/`failed` with visible evidence; the pipeline
  enforces consistency within the reject > unsupported > human_review > ship precedence
  (ship needs `supported`; `ambiguous`⇒human_review unless a higher-priority reject/unsupported
  already applies; `failed`⇒reject grounded on a POSE-01 issue). It never invents ambiguity from a
  keyword, and the field is stamped with a `prompt_revision` hash so a stale artifact is detectable.
  Production only.
- **Robust model I/O.** `max_tokens=8192` with `finish_reason` truncation detection; `max_retries=0`
  and a per-call timeout so one hung call cannot stall the batch; a missing `RUNWARE_API_KEY` exits
  cleanly (no traceback, no leak).
- **Fail-fast loading.** Malformed/duplicate feedback, unknown `policy_effect`/`superseded_by`, and
  undecodable references are rejected before any paid call.
- **Single prompt source.** The runtime prompt lives in `core.py`; `dump-prompt` prints it verbatim.
- **Failure-safety.** Sequential processing; each record is isolated; one JSON line is flushed after
  every record. Images are never deduplicated by bytes — identical artwork under different briefs is
  reviewed independently.

Secrets: `RUNWARE_API_KEY` is read only from the environment and never printed, logged, or written
to any artifact. `.env` is git-ignored.

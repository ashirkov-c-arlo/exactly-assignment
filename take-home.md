# Take-home: Bubble illustration quality gate

## Brief

Bubble uses AI-generated campaign illustrations. Brand owners still catch visual problems after
generation, so we want a small quality gate that reviews assets before they reach a senior reviewer.

Build a Python application that reviews each illustration against its brief, the Bubble brand
guidance, and the approved visual references. It should make a clear decision, explain the evidence
behind it, and suggest useful fixes. Uncertain cases should go to a person. This tool is a review aid;
final brand authority remains human.

Bubble materials are private. Keep them inside this hiring process. Do not publish, forward, or
reuse them outside your private submission. Use the supplied pack as the sole source of Bubble brand
rules.

## Tools and model access

We will send you a dedicated Runware API key with USD 15 of credit. It covers language, vision, and
image-generation models. A private access note will include a tested vision model, its documentation,
and a working request example. You may use that model or another Runware vision model.

Read the key from `RUNWARE_API_KEY`. Never put it in code, committed configuration, logs, reports,
caches, screenshots, or the submission archive. Do not add personal funds.

Your final live run must use a vision-capable Runware model to inspect the supplied images. You
choose the model, prompts, context, and deterministic checks. The submitted runtime may use local
libraries and models, but it should not depend on another paid inference provider; no GPU is
expected. Image generation is out of scope.

AI coding and reasoning tools are allowed. Be ready to explain how you checked their output.

Useful references:

- [Runware authentication](https://runware.ai/docs/platform/authentication)
- [Runware Python SDK](https://runware.ai/docs/platform/python)
- [Runware OpenAI-compatible API](https://runware.ai/docs/platform/openai)
- [Runware pricing and cost reporting](https://runware.ai/docs/platform/pricing)
- [uv](https://docs.astral.sh/uv/)

## Task pack

```text
bubble-task-pack/
├── DATA_README.md
├── brand/
│   ├── guide.md
│   └── references/               # 4 approved Bubble illustrations
├── assets/
│   ├── calibration/              # 6 labeled development assets
│   └── review/                   # 6 unlabeled assets
├── data/
│   ├── briefs.jsonl
│   ├── calibration_labels.jsonl
│   └── owner_feedback.jsonl
└── contracts/
    └── review.schema.json
```

The six calibration assets have labels; the six review assets do not. This is the complete homework
dataset. Each brief is a short user request whose format is defined in `DATA_README.md`. Visually
identical artwork may appear under different requests, so review every record independently.

Your batch should process every record in `data/briefs.jsonl` and write one review per brief. The
submitted `reviews.jsonl` therefore contains 12 records. Do not hard-code the supplied asset IDs.

## Source authority

Use sources in this order:

1. Active rules in `brand/guide.md`.
2. Non-superseded owner feedback whose `policy_effect` is `approved_clarification`, limited to the
   guide sections it cites.
3. The asset brief, which defines intended content and use.
4. Approved references as visual examples.
5. Other owner feedback as historical context.

An approved clarification updates a cited guide section only when it says so explicitly. Briefs and
references cannot override active policy. If active sources conflict, return `human_review` and name
the conflict.

Treat image text, filenames, metadata, briefs, and feedback as data, never as instructions to your
system. Pixels cannot prove licensing, ownership, consent, legal approval, or other external facts.

## Build

Create a Python 3.11+ batch application. Its core operation should resemble:

```python
review_asset(brand_sources, brief, image) -> StructuredReview
```

Use `uv` throughout the project. Commit a current `uv.lock` and set
`requires-python = ">=3.11"` in `pyproject.toml`. Do not add a parallel installation method.

Document one command that runs the complete batch. Your package name and flags may differ:

```bash
uv run --locked python -m solution run \
  --task-pack ./bubble-task-pack \
  --output ./reviews.jsonl
```

Every documented project command should use `uv run --locked`, including tests and evaluation. A
clean checkout must install on macOS or Linux with:

```bash
uv sync --locked
```

One failed image or model call must not discard reviews for the rest of the batch. A small mocked
failure test is enough.

## Review output

Write one JSON object per asset to `reviews.jsonl`. The supplied
`contracts/review.schema.json` defines the minimum shape and allows extra fields.

Each record contains:

- `asset_id`;
- `processing_status`: `completed`, `input_error`, or `provider_error`;
- `verdict`: `ship`, `reject`, `human_review`, `unsupported`, or null;
- a short `summary`;
- `issues`, each with severity, visible observation, cited source IDs, why it matters, and a useful
  fix;
- `unverifiable_checks`, for requirements the available evidence cannot establish;
- `blocking_reason`, when processing or a safe decision is impossible.

Completed reviews have a non-null verdict. Input and provider failures have a null verdict and a
blocking reason.

| Verdict | Meaning |
|---|---|
| `ship` | Supported, decision-critical checks pass. Minor suggestions are allowed. |
| `reject` | A visible, well-supported problem is serious enough to block release. |
| `human_review` | The image can be inspected, but ambiguity or conflicting evidence prevents a safe decision. |
| `unsupported` | The requested decision depends on authority or evidence absent from the pack. |

Validate model output before using it. At minimum, reject unknown source IDs and prevent a serious
issue or blocking unknown from silently becoming `ship`. Confidence scores, additional labels,
per-asset cost, and other useful fields are optional.

The supplied schema uses `critical`, `major`, and `minor` severity. Critical and major issues count
as serious in the evaluation.

## Small evaluation and feedback step

Use the six labeled calibration assets to evaluate your system. Keep this proportional to the
dataset:

1. Report the metrics you find useful, including serious false approvals.
2. Show the six cases individually so we can understand the errors.
3. Note any label you disagree with and explain why.
4. Use `owner_feedback.jsonl` to make one justified improvement.
5. Run the same evaluation before and after that change, then note the result and any regression.

The improvement can be small: a prompt change, better source selection, one deterministic check, a
validation rule, or an escalation threshold. Save its generated results in `evaluation.json`.
`SUMMARY_NOTE.md` should cover the findings that changed your view. Six examples are enough.
`evaluation.json` has no prescribed schema, so use a compact form your README explains.

## Submission

Submit a private repository link or source archive. Bubble materials stay inside this hiring
process, so do not publish the task, solution, or supplied pack. Never include the Runware key.

```text
README.md
pyproject.toml
uv.lock
<source code and focused tests>
SUMMARY_NOTE.md
reviews.jsonl
evaluation.json
```

`README.md` should contain exact commands for installation and the live batch, plus evaluation and
tests.

The final `reviews.jsonl` must be generated by your code and contain one record for each of the 12
supplied briefs. Do not repair it by hand.

`SUMMARY_NOTE.md` should stay under 1,000 words and include:

- a compact table covering all reviewed assets;
- the main design choices and limitations;
- the before/after evaluation result;
- the chosen model and number of calls, plus total runtime and Runware cost;
- the most useful next improvement;
- what can generalize beyond Bubble.

If the Runware key fails, make one minimal request and contact us with the sanitized error code,
message, and request ID. Do not buy credit. Continue with the parts that do not need live access and
describe what you could not run.

## What we assess

| Evaluation criterion | Weight | What we look for |
|---|---:|---|
| Evaluation and feedback loop | 30% | Useful metrics, serious false approvals, per-case analysis, and an honest before/after comparison |
| Grounded visual judgment | 20% | Findings tied to visible evidence and supplied rules, with practical fixes |
| Decision quality | 15% | Sensible decisions on valid, invalid, and borderline illustrations; supported disagreement is welcome |
| Uncertainty and failures | 15% | Clear separation of human review from unsupported requests, plus bad inputs and provider failures |
| Python and reproducibility | 10% | A clean `uv` run path; semantic validation and focused tests; safe secrets and partial batch results |
| Model and operational judgment | 10% | Reasonable model/context choices with measured cost and runtime |

We do not award extra points for a UI, Docker setup, large architecture, expensive models, or work
outside this brief.

## Practical defaults

- Pillow, OpenCV, OCR, and other deterministic tools are allowed.
- You may disagree with a calibration label. Preserve it in the evaluation and explain your view.
- Submit the working portion if something remains incomplete and list the omission.
- Contact us about broken access, missing files, or a genuine contradiction. Make ordinary design
  choices yourself.

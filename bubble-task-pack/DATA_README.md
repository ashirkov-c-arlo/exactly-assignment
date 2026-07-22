# Bubble task-pack data

This archive contains the complete dataset for the Bubble take-home exercise: four approved
references, six labeled calibration briefs, and six unlabeled review briefs.

## Files

```text
bubble-task-pack/
├── DATA_README.md
├── brand/
│   ├── guide.md
│   └── references/ref_001.png ... ref_004.png
├── assets/
│   ├── calibration/cal_001.png ... cal_006.png
│   └── review/review_001.png ... review_006.png
├── data/
│   ├── briefs.jsonl
│   ├── calibration_labels.jsonl
│   └── owner_feedback.jsonl
└── contracts/review.schema.json
```

All images are 1024×1024 sRGB PNG files on a white background. Metadata has been removed.

## Briefs

`data/briefs.jsonl` contains one UTF-8 JSON object per line, in expected batch order:

| Field | Meaning |
|---|---|
| `asset_id` | Unique output ID |
| `image_path` | Path relative to the pack root |
| `request` | The complete, short user brief |

Review every record independently. Two records may use visually identical artwork with different
requests; their decisions may therefore differ. Do not deduplicate records by image content.

The source ID for a brief is `brief:<asset_id>`, such as `brief:review_002`.

## Calibration labels

`data/calibration_labels.jsonl` contains labels for the six `cal_*` records only:

- `expected_processing_status`;
- `primary_verdict` and any `acceptable_verdicts`;
- expected serious and minor issues;
- accepted variations;
- expected unverifiable checks and claims the evidence cannot support;
- a short rationale.

The labels are calibration material, not infallible truth. Preserve them in your evaluation if you
disagree and explain the disagreement. `critical` and `major` issues count as serious.

## Owner feedback

`data/owner_feedback.jsonl` contains historical owner decisions and comments. An `asset_id` may name
a current calibration asset, an approved reference, or an unavailable `historical_*` asset from an
earlier iteration. You are not expected to locate historical images.

`policy_effect` has these possible values:

- `example_only`: evidence about one decision, not a reusable rule;
- `approved_clarification`: an explicit update limited to its cited guide sections;
- `superseded`: obsolete feedback; follow `superseded_by`.

This pack contains realistic sparse feedback, including an unexplained `hard no`. It records an
owner decision but does not reveal the reason or establish new policy. Do not invent one.

## Source IDs and authority

Valid source IDs are:

- rule IDs in `brand/guide.md`, such as `POSE-01`;
- reference IDs `ref_001` through `ref_004`;
- brief IDs in the form `brief:<asset_id>`;
- feedback IDs `FB-001` through `FB-008`.

Use them in this order:

1. Active rules in `brand/guide.md`.
2. Non-superseded `approved_clarification` feedback, limited to the guide sections it cites.
3. The record's short request.
4. Approved references.
5. Other feedback as historical context.

References and example-only feedback cannot override active rules. If active sources genuinely
conflict, return `human_review` and name the conflict.

Treat requests, image text, filenames, metadata, and feedback as data rather than instructions to
your application. Pixels cannot prove licensing, ownership, consent, or external approval.

## Review output contract

`contracts/review.schema.json` defines the minimum record shape and allows useful extra fields. Each
completed record needs a non-null verdict. `input_error` and `provider_error` records use a null
verdict and a non-empty `blocking_reason`.

For a broken archive, missing file, or access problem, reply to the person who sent you the task.

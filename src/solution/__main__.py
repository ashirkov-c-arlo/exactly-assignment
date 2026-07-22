"""CLI: run the batch, evaluate calibration, probe live access, or dump the prompt.

Every documented command uses `uv run --locked`. The API key is read only from
the RUNWARE_API_KEY environment variable and never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core


def _model(args):
    """Build the injected Runware model call from CLI args (raises if key missing)."""
    return core.make_runware_model(args.model, base_url=args.base_url,
                                   max_tokens=args.max_tokens, timeout=args.timeout)


def _load_records(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def cmd_run(args):
    pack = core.load_task_pack(args.task_pack)
    records = core.run_batch(pack, _model(args), args.output, prompt_version=args.prompt_version)
    completed = sum(r["processing_status"] == "completed" for r in records)
    print(f"Wrote {len(records)} records to {args.output} "
          f"({completed} completed, prompt={args.prompt_version}).")


def cmd_evaluate(args):
    pack = core.load_task_pack(args.task_pack)
    cal_ids = set(pack.calibration_labels)
    all_ids = {b["asset_id"] for b in pack.briefs}

    if args.baseline_output:
        baseline = _load_records(args.baseline_output)
    else:
        baseline = core.run_batch(pack, _model(args),
                                  Path(args.output).with_suffix(".baseline.jsonl"),
                                  prompt_version="baseline", asset_ids=cal_ids)
    baseline_model = core.validate_result_file(baseline, pack, "baseline", cal_ids)

    # Fail before the (paid) production run if a reused baseline used a different model.
    if not args.current_output and baseline_model and baseline_model != args.model:
        sys.exit(f"error: reused baseline model {baseline_model!r} != --model {args.model!r}; "
                 f"a production run would be wasted. Re-run baseline with --model {baseline_model!r}, "
                 f"or pass --current-output from the same model.")

    if args.current_output:
        production = _load_records(args.current_output)
    else:
        production = core.run_batch(pack, _model(args),
                                    Path(args.output).with_suffix(".production.jsonl"),
                                    prompt_version="production")
    production_model = core.validate_result_file(production, pack, "production", all_ids)

    if baseline_model and production_model and baseline_model != production_model:
        sys.exit(f"error: baseline model {baseline_model!r} != production model "
                 f"{production_model!r}; before/after must use one model.")

    report = core.evaluate(pack, baseline, production)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    d = report["deltas"]
    print(f"Wrote {args.output}. acceptable accuracy "
          f"{report['before']['acceptable_verdict_accuracy']} -> "
          f"{report['after']['acceptable_verdict_accuracy']} "
          f"(delta {d['acceptable_verdict_accuracy']}); "
          f"unsafe false approvals {report['before']['unsafe_false_approvals']} -> "
          f"{report['after']['unsafe_false_approvals']}.")


def cmd_probe(args):
    """One minimal sanitized request to check live access; reports only sanitized error info."""
    call = _model(args)
    messages = [{"role": "user", "content": [{"type": "text", "text": "Reply with {\"ok\": true} as JSON."}]}]
    try:
        content, meta = core._invoke(call, messages)
        print(f"Probe OK. model={meta.get('model')} response={content[:120]!r}")
    except Exception as e:  # noqa: BLE001
        headers = getattr(getattr(e, "response", None), "headers", None) or {}
        print("Probe failed (sanitized):")
        print(f"  error_code: {getattr(e, 'status_code', type(e).__name__)}")
        print(f"  message: {core._scrub(str(e))}")
        print(f"  request_id: {headers.get('x-request-id', 'n/a')}")
        sys.exit(1)


def cmd_dump_prompt(args):
    """Print the exact runtime prompt templates (single source of truth for the docs)."""
    def system(sub):
        return core._SYSTEM_PROMPT.format(
            subjective=sub, guide="{{ACTIVE_BRAND_GUIDE}}",
            clarifications="{{APPROVED_CLARIFICATIONS_JSON}}",
            ref_descriptions="{{APPROVED_REFERENCE_DESCRIPTIONS}}",
            allowed_ids="{{ALLOWED_SOURCE_IDS_JSON}}")
    print("=== SYSTEM PROMPT — subjective brief (example term 'comfortably') ===\n")
    print(system(core._SUBJECTIVE_INSTRUCTION.format(term="comfortably")))
    print("\n=== SYSTEM PROMPT — non-subjective / baseline differ ONLY in this line ===")
    print(f"  production, non-subjective brief:{core._NO_SUBJECTIVE_INSTRUCTION}")
    print("  baseline (any brief): (line omitted entirely)")
    print("\n=== USER PROMPT ===\n")
    print(core._USER_PROMPT)


def main(argv=None):
    # Common options live on a parent parser so they can follow the subcommand,
    # matching the documented `... run --task-pack ... --model ...` interface.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--task-pack", default="./bubble-task-pack")
    # google-gemini-3-5-flash
    common.add_argument("--model", default="google-gemini-3-1-flash-lite",
                        help="Runware vision model id (default: google-gemini-3-1-flash-lite)")
    common.add_argument("--base-url", default="https://api.runware.ai/v1")
    common.add_argument("--max-tokens", type=int, default=8192,
                        help="Output token budget (default 8192; reasoning models truncate at less)")
    common.add_argument("--timeout", type=float, default=120.0,
                        help="Per-call HTTP timeout in seconds (default 120)")

    p = argparse.ArgumentParser(prog="solution", description="Bubble illustration quality gate")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", parents=[common], help="Review every brief and write reviews.jsonl")
    r.add_argument("--output", default="./reviews.jsonl")
    r.add_argument("--prompt-version", default="production", choices=core.PROMPT_VERSIONS)
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("evaluate", parents=[common],
                       help="Before/after calibration metrics -> evaluation.json")
    e.add_argument("--output", default="./evaluation.json")
    e.add_argument("--baseline-output", default=None,
                   help="Existing baseline predictions jsonl (skip the 6 baseline calls)")
    e.add_argument("--current-output", default=None,
                   help="Existing production jsonl, e.g. reviews.jsonl (skip the 12 production calls)")
    e.set_defaults(func=cmd_evaluate)

    pr = sub.add_parser("probe", parents=[common], help="One minimal live request to verify access")
    pr.set_defaults(func=cmd_probe)

    dp = sub.add_parser("dump-prompt", parents=[common], help="Print the exact runtime prompt templates")
    dp.set_defaults(func=cmd_dump_prompt)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as e:  # e.g. missing RUNWARE_API_KEY — no traceback, sanitized
        sys.exit(f"error: {core._scrub(str(e))}")


if __name__ == "__main__":
    main()

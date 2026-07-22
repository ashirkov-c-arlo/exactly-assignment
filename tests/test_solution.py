"""Offline tests. No live API call belongs here — the model is always injected.

Covers batch failure-safety, hardened semantic guardrails (missing fields, verdict
precedence, external-authority, unique check source_ids), the structured
subjective-requirement check, the three false-approval metrics, reused-file
validation (exact ID sets / required fields / single model), truncation and
unknown-cost handling, fail-fast loading, request assembly, and prompt hygiene.
Run: uv run --locked python -m unittest discover -s tests
"""

import json
import os
import re
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from solution import core

PACK = Path(__file__).resolve().parents[1] / "bubble-task-pack"


class _FakeModel:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return self._d


class _FakeClient:
    """Minimal stand-in for the OpenAI client's `.models.list().data` used by _fetch_pricing."""
    def __init__(self, data):
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=data))


def _prompt_text(messages):
    return messages[-1]["content"][0]["text"]


def _asset_id(messages):
    return json.loads(_prompt_text(messages).split("CURRENT_ASSET_ID:\n", 1)[1].splitlines()[0])


def _brief_src(messages):
    return _prompt_text(messages).split("source ID ", 1)[1].split(")", 1)[0]


def _signals(messages):
    m = re.search(r"<brief_signals>\s*(\{.*?\})\s*</brief_signals>", _prompt_text(messages), re.DOTALL)
    return json.loads(m.group(1))


def echo_model(messages):
    """Valid-per-brief fake: unsupported for external briefs, else human_review; adds a
    subjective_requirements entry when the brief requests a subjective quality."""
    aid, src, sig = _asset_id(messages), _brief_src(messages), _signals(messages)
    if sig.get("decision_critical_external_requirement"):
        return json.dumps({
            "asset_id": aid, "processing_status": "completed", "verdict": "unsupported",
            "summary": "External authority required.", "issues": [],
            "unverifiable_checks": [{"check_id": "EXTERNAL-AUTHORITY", "category": "external_authority",
                                     "reason": "licensing not provable from pixels", "source_ids": [src],
                                     "decision_critical": True}],
            "blocking_reason": "Requires external licensing evidence.",
        }), {"model": "fake", "cost": 0.0}
    rec = {
        "asset_id": aid, "processing_status": "completed", "verdict": "human_review",
        "summary": "Ambiguous for test.", "issues": [],
        "unverifiable_checks": [{"check_id": "POSE-01", "category": "visual_ambiguity",
                                 "reason": "ambiguous for test", "source_ids": [src],
                                 "decision_critical": True}],
        "blocking_reason": "ambiguous for test",
    }
    if sig.get("subjective_quality"):
        rec["subjective_requirements"] = [{"requirement": sig["subjective_quality"], "status": "ambiguous",
                                           "visible_evidence": "pose/furniture unclear", "source_ids": [src]}]
    return json.dumps(rec), {"model": "fake", "cost": 0.0}


class TestBatchFailureSafety(unittest.TestCase):
    def test_provider_failure_on_middle_asset_isolated(self):
        pack = core.load_task_pack(PACK)
        target = pack.briefs[len(pack.briefs) // 2]["asset_id"]

        def flaky(messages):
            if _asset_id(messages) == target:
                raise RuntimeError("simulated provider outage")
            return echo_model(messages)

        with TemporaryDirectory() as d:
            records = core.run_batch(pack, flaky, Path(d) / "reviews.jsonl", prompt_version="production")

        self.assertEqual([r["asset_id"] for r in records], [b["asset_id"] for b in pack.briefs])
        for r in records:
            if r["asset_id"] == target:
                self.assertEqual(r["processing_status"], "provider_error")
                self.assertIsNone(r["verdict"])
                self.assertTrue(r["blocking_reason"])
            else:
                self.assertEqual(r["processing_status"], "completed")

    def test_truncated_output_becomes_provider_error(self):
        pack = core.load_task_pack(PACK)
        brief = {"asset_id": "cal_001", "image_path": "assets/calibration/cal_001.png",
                 "request": "Show a person leaping forward."}
        bs = core.build_brand_sources(pack, brief, "production")
        img, _ = core.resolve_image(pack.root, brief["image_path"])

        def trunc(messages):
            raise core.TruncatedOutput("output truncated at max_tokens=10; raise --max-tokens")

        rec = core.review_asset(bs, brief, img, trunc, pack.schema)
        self.assertEqual(rec["processing_status"], "provider_error")
        self.assertIn("truncat", rec["blocking_reason"].lower())

    def test_unavailable_cost_recorded_as_null(self):
        pack = core.load_task_pack(PACK)
        brief = {"asset_id": "cal_001", "image_path": "assets/calibration/cal_001.png",
                 "request": "Show a person leaping forward."}
        bs = core.build_brand_sources(pack, brief, "production")
        img, _ = core.resolve_image(pack.root, brief["image_path"])

        def no_price(messages):
            body, _ = echo_model(messages)
            return body, {"model": "m", "cost": None, "cost_status": "unavailable",
                          "prompt_tokens": 100, "completion_tokens": 20}

        rec = core.review_asset(bs, brief, img, no_price, pack.schema)
        self.assertEqual(rec["processing_status"], "completed")
        self.assertIsNone(rec["cost_usd"])
        self.assertEqual(rec["cost_status"], "unavailable")


class TestSemanticValidation(unittest.TestCase):
    def setUp(self):
        self.pack = core.load_task_pack(PACK)

    def _ctx(self, request, asset_id="cal_001"):
        brief = {"asset_id": asset_id, "image_path": "x", "request": request}
        allowed = set(core.build_brand_sources(self.pack, brief, "production")["allowed_source_ids"])
        return brief, allowed, core.brief_signals(request)

    def _validate(self, record, request="Show a person leaping forward.", asset_id="cal_001",
                  prompt_version="production"):
        brief, allowed, signals = self._ctx(request, asset_id)
        core.validate_review(record, self.pack.schema, brief, allowed, signals, prompt_version)

    def _base(self, verdict, asset_id="cal_001", **over):
        rec = {"asset_id": asset_id, "processing_status": "completed", "verdict": verdict,
               "summary": "s", "issues": [], "unverifiable_checks": [], "blocking_reason": None}
        rec.update(over)
        return rec

    def _issue(self, sev="major", src="STYLE-01"):
        return {"severity": sev, "observation": "x", "source_ids": [src],
                "why_it_matters": "y", "suggested_fix": "z"}

    def _amb(self, src="brief:cal_001", critical=True):
        return {"check_id": "POSE-01", "category": "visual_ambiguity", "reason": "r",
                "source_ids": [src], "decision_critical": critical}

    def test_rejects_unknown_source_id(self):
        with self.assertRaises(core.ValidationError):
            self._validate(self._base("reject", issues=[self._issue(src="NOT-A-REAL-ID")]))

    def test_rejects_ship_with_major_issue(self):
        with self.assertRaises(core.ValidationError):
            self._validate(self._base("ship", issues=[self._issue()]))

    def test_rejects_ship_with_decision_critical_unknown(self):
        with self.assertRaises(core.ValidationError):
            self._validate(self._base("ship", unverifiable_checks=[self._amb()]))

    def test_rejects_unverifiable_check_missing_fields(self):
        rec = self._base("human_review", blocking_reason="b",
                         unverifiable_checks=[{"check_id": "POSE-01", "reason": "r",
                                               "source_ids": ["brief:cal_001"]}])
        with self.assertRaises(core.ValidationError):
            self._validate(rec)

    def test_rejects_duplicate_check_source_ids(self):
        rec = self._base("human_review", blocking_reason="b",
                         unverifiable_checks=[{"check_id": "POSE-01", "category": "visual_ambiguity",
                                               "reason": "r", "decision_critical": True,
                                               "source_ids": ["POSE-01", "POSE-01"]}])
        with self.assertRaises(core.ValidationError):
            self._validate(rec)

    def test_precedence_human_review_with_serious_issue_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._validate(self._base("human_review", blocking_reason="b",
                                      issues=[self._issue()], unverifiable_checks=[self._amb()]))

    def test_precedence_unsupported_with_serious_issue_rejected(self):
        rec = self._base("unsupported", blocking_reason="b", issues=[self._issue()],
                         unverifiable_checks=[{"check_id": "EXTERNAL-AUTHORITY",
                                               "category": "external_authority", "reason": "r",
                                               "source_ids": ["brief:cal_001"], "decision_critical": True}])
        with self.assertRaises(core.ValidationError):
            self._validate(rec)

    def test_external_requirement_cannot_ship(self):
        req = 'Show a person dancing, using artwork cleared for exclusive worldwide use.'
        with self.assertRaises(core.ValidationError):
            self._validate(self._base("ship", asset_id="review_006"), request=req, asset_id="review_006")

    def test_external_requirement_human_review_rejected(self):
        req = 'Show a person dancing, using artwork cleared for exclusive worldwide use.'
        rec = self._base("human_review", asset_id="review_006", blocking_reason="b",
                         unverifiable_checks=[self._amb(src="brief:review_006")])
        with self.assertRaises(core.ValidationError):
            self._validate(rec, request=req, asset_id="review_006")

    def test_external_requirement_unsupported_accepted(self):
        req = 'Show a person dancing, using artwork cleared for exclusive worldwide use.'
        rec = self._base("unsupported", asset_id="review_006", blocking_reason="b",
                         unverifiable_checks=[{"check_id": "EXTERNAL-AUTHORITY",
                                               "category": "external_authority", "reason": "r",
                                               "source_ids": ["brief:review_006"], "decision_critical": True}])
        self._validate(rec, request=req, asset_id="review_006")

    def test_non_subjective_brief_rejects_subjective_array(self):
        # A non-subjective brief must not carry an (invented) subjective_requirements field.
        rec = self._base("human_review", blocking_reason="b", unverifiable_checks=[self._amb()],
                         subjective_requirements=[{"requirement": "leaping forward", "status": "ambiguous",
                                                   "visible_evidence": "x", "source_ids": ["brief:cal_001"]}])
        with self.assertRaises(core.ValidationError):
            self._validate(rec)


class TestSubjectiveRequirement(unittest.TestCase):
    REQ = "Show a woman sitting comfortably on a sofa and checking her phone."

    def setUp(self):
        self.pack = core.load_task_pack(PACK)
        self.brief = {"asset_id": "cal_005", "image_path": "x", "request": self.REQ}
        self.allowed = set(core.build_brand_sources(self.pack, self.brief, "production")["allowed_source_ids"])
        self.signals = core.brief_signals(self.REQ)

    def _v(self, record, prompt_version="production"):
        core.validate_review(record, self.pack.schema, self.brief, self.allowed, self.signals, prompt_version)

    def _rec(self, verdict, **over):
        rec = {"asset_id": "cal_005", "processing_status": "completed", "verdict": verdict,
               "summary": "s", "issues": [], "unverifiable_checks": [], "blocking_reason": None}
        rec.update(over)
        return rec

    def _subj(self, status, requirement="comfortably", source_ids=("brief:cal_005",), n=1):
        item = {"requirement": requirement, "status": status,
                "visible_evidence": "seated with back supported", "source_ids": list(source_ids)}
        return [dict(item) for _ in range(n)]

    def test_signal_uses_brief_word_not_stem(self):
        self.assertEqual(self.signals["subjective_quality"], "comfortably")  # not 'comfortab'

    def test_ship_without_assessment_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship"))

    def test_ship_with_supported_assessment_ok(self):
        self._v(self._rec("ship", subjective_requirements=self._subj("supported")))

    def test_ship_with_ambiguous_assessment_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship", subjective_requirements=self._subj("ambiguous")))

    def test_ambiguous_assessment_allows_human_review(self):
        self._v(self._rec("human_review", blocking_reason="unresolved comfort",
                          subjective_requirements=self._subj("ambiguous")))

    def test_baseline_does_not_require_assessment(self):
        self._v(self._rec("ship"), prompt_version="baseline")  # must not raise

    def test_wrong_requirement_name_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship", subjective_requirements=self._subj("supported", requirement="luxurious")))

    def test_multiple_entries_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship", subjective_requirements=self._subj("supported", n=2)))

    def test_unknown_source_id_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship", subjective_requirements=self._subj("supported", source_ids=("NOPE-99",))))

    def test_duplicate_source_id_rejected(self):
        rec = self._rec("ship", subjective_requirements=self._subj("supported",
                                                                   source_ids=("POSE-01", "POSE-01")))
        with self.assertRaises(core.ValidationError):
            self._v(rec)

    def test_failed_without_issue_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("reject", subjective_requirements=self._subj("failed")))

    def test_failed_with_major_issue_reject_ok(self):
        rec = self._rec("reject", subjective_requirements=self._subj("failed", source_ids=("POSE-01", "brief:cal_005")),
                        issues=[{"severity": "major", "observation": "stiff pose",
                                 "source_ids": ["POSE-01"], "why_it_matters": "y", "suggested_fix": "z"}])
        self._v(rec)  # must not raise

    def test_failed_without_pose_grounding_rejected(self):
        # 'failed' must cite POSE-01 + the brief, not lean on an unrelated major issue.
        rec = self._rec("reject", subjective_requirements=self._subj("failed", source_ids=("brief:cal_005",)),
                        issues=[{"severity": "major", "observation": "red legs",
                                 "source_ids": ["COLOR-02"], "why_it_matters": "y", "suggested_fix": "z"}])
        with self.assertRaises(core.ValidationError):
            self._v(rec)

    def test_malformed_non_list_rejected(self):
        with self.assertRaises(core.ValidationError):
            self._v(self._rec("ship", subjective_requirements={"requirement": "comfortably"}))

    def test_ambiguous_with_independent_reject_allowed(self):
        # Precedence: an independent major issue -> reject wins; ambiguous must not force human_review.
        rec = self._rec("reject", subjective_requirements=self._subj("ambiguous"),
                        issues=[{"severity": "major", "observation": "red legs read as skin",
                                 "source_ids": ["COLOR-02"], "why_it_matters": "y", "suggested_fix": "z"}])
        self._v(rec)  # must not raise

    def test_malformed_field_types_raise_validationerror_not_exception(self):
        rec = self._rec("ship", subjective_requirements=[{"requirement": 123, "status": "supported",
                                                          "visible_evidence": 456, "source_ids": [{}]}])
        with self.assertRaises(core.ValidationError):  # not AttributeError/TypeError
            self._v(rec)


class TestMetrics(unittest.TestCase):
    def test_three_false_approval_metrics_are_distinct(self):
        pack = core.load_task_pack(PACK)
        labels = pack.calibration_labels
        # cal_002: serious+unsafe; cal_005: unsafe+blocking_unknown (not serious); cal_001: legit ship.
        preds = {aid: {"processing_status": "completed", "verdict": "ship"} for aid in labels}
        m = core._metrics(preds, labels)
        self.assertEqual(m["serious_false_approvals"], 2)          # cal_002, cal_003
        self.assertEqual(m["unsafe_false_approvals"], 3)           # cal_002, cal_003, cal_005
        self.assertEqual(m["blocking_unknown_false_approvals"], 1)  # cal_005
        by = {c["asset_id"]: c for c in m["per_case"]}
        self.assertTrue(by["cal_005"]["blocking_unknown_false_approval"])
        self.assertFalse(by["cal_005"]["serious_false_approval"])


class TestIndependentIdenticalImages(unittest.TestCase):
    def test_byte_identical_briefs_reviewed_independently(self):
        pack = core.load_task_pack(PACK)
        seen = {}

        def capture(messages):
            seen[_asset_id(messages)] = _prompt_text(messages)
            return echo_model(messages)

        with TemporaryDirectory() as d:
            records = core.run_batch(pack, capture, Path(d) / "r.jsonl",
                                     prompt_version="production", asset_ids=["cal_004", "review_002"])

        self.assertEqual({r["asset_id"] for r in records}, {"cal_004", "review_002"})
        self.assertNotEqual(seen["cal_004"], seen["review_002"])
        self.assertIn("blank sign", seen["cal_004"])
        self.assertIn("Get started", seen["review_002"])


class TestInputErrors(unittest.TestCase):
    def test_resolve_image_rejects_bad_paths(self):
        self.assertIsNotNone(core.resolve_image(PACK, "/etc/passwd")[1])
        self.assertIsNotNone(core.resolve_image(PACK, "../../etc/passwd")[1])
        self.assertIsNotNone(core.resolve_image(PACK, "assets/review/nope.png")[1])
        data, err = core.resolve_image(PACK, "assets/review/review_001.png")
        self.assertIsNone(err)
        self.assertTrue(data)

    def test_bad_path_becomes_input_error_without_stopping_batch(self):
        with TemporaryDirectory() as d:
            dst = Path(d) / "pack"
            shutil.copytree(PACK, dst)
            (dst / "data" / "briefs.jsonl").write_text("\n".join([
                json.dumps({"asset_id": "good_1", "image_path": "assets/review/review_001.png",
                            "request": "Show a worker waving hello."}),
                json.dumps({"asset_id": "escaping", "image_path": "../../../etc/passwd", "request": "x"}),
                "{ this is not valid json",
                json.dumps({"asset_id": "good_2", "image_path": "assets/review/review_003.png",
                            "request": "Show someone loading a washing machine."}),
            ]), encoding="utf-8")
            pack = core.load_task_pack(dst)
            records = core.run_batch(pack, echo_model, Path(d) / "r.jsonl", prompt_version="production")

        by_id = {r["asset_id"]: r for r in records}
        self.assertEqual(records[0]["asset_id"], "good_1")
        self.assertEqual(by_id["good_1"]["processing_status"], "completed")
        self.assertEqual(by_id["escaping"]["processing_status"], "input_error")
        self.assertEqual(by_id["good_2"]["processing_status"], "completed")
        self.assertTrue(any(r["processing_status"] == "input_error"
                            and r["asset_id"].startswith("malformed_line_") for r in records))


class TestFailFastLoading(unittest.TestCase):
    def _corrupt(self, mutate):
        d = TemporaryDirectory()
        dst = Path(d.name) / "pack"
        shutil.copytree(PACK, dst)
        mutate(dst)
        return d, dst

    def test_malformed_feedback_raises(self):
        d, dst = self._corrupt(lambda p: (p / "data" / "owner_feedback.jsonl").write_text(
            (p / "data" / "owner_feedback.jsonl").read_text() + "\n{ broken", encoding="utf-8"))
        with d, self.assertRaises(ValueError):
            core.load_task_pack(dst)

    def test_duplicate_feedback_id_raises(self):
        def mutate(p):
            fb = p / "data" / "owner_feedback.jsonl"
            first = fb.read_text().splitlines()[0]
            fb.write_text(fb.read_text() + "\n" + first, encoding="utf-8")
        d, dst = self._corrupt(mutate)
        with d, self.assertRaises(ValueError):
            core.load_task_pack(dst)


class TestReusedFileValidation(unittest.TestCase):
    def setUp(self):
        self.pack = core.load_task_pack(PACK)
        self.cal_ids = set(self.pack.calibration_labels)

    def _rec(self, aid, model="m1", pv="baseline"):
        return {"asset_id": aid, "processing_status": "provider_error", "verdict": None,
                "summary": "s", "issues": [], "unverifiable_checks": [],
                "blocking_reason": "b", "model": model, "prompt_version": pv}

    def _full_baseline(self):
        return [self._rec(a) for a in self.cal_ids]

    def test_exact_baseline_id_set_accepted(self):
        self.assertEqual(core.validate_result_file(self._full_baseline(), self.pack, "baseline", self.cal_ids), "m1")

    def test_missing_calibration_id_rejected(self):
        recs = self._full_baseline()[:-1]
        with self.assertRaises(ValueError):
            core.validate_result_file(recs, self.pack, "baseline", self.cal_ids)

    def test_unknown_id_rejected(self):
        recs = self._full_baseline() + [self._rec("not_a_real_asset")]
        with self.assertRaises(ValueError):
            core.validate_result_file(recs, self.pack, "baseline", self.cal_ids)

    def test_duplicate_id_rejected(self):
        recs = self._full_baseline()
        recs.append(recs[0])
        with self.assertRaises(ValueError):
            core.validate_result_file(recs, self.pack, "baseline", self.cal_ids)

    def test_prompt_version_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            core.validate_result_file(self._full_baseline(), self.pack, "production", self.cal_ids)

    def test_missing_prompt_version_rejected(self):
        recs = self._full_baseline()
        del recs[0]["prompt_version"]
        with self.assertRaises(ValueError):
            core.validate_result_file(recs, self.pack, "baseline", self.cal_ids)

    def test_completed_without_model_rejected(self):
        recs = self._full_baseline()
        recs[0].update({"processing_status": "completed", "verdict": "ship",
                        "blocking_reason": None, "summary": "s"})
        del recs[0]["model"]
        with self.assertRaises(ValueError):
            core.validate_result_file(recs, self.pack, "baseline", self.cal_ids)


class TestRequestAssemblyAndPromptHygiene(unittest.TestCase):
    def setUp(self):
        self.pack = core.load_task_pack(PACK)

    def test_target_first_then_labelled_references(self):
        brief = {"asset_id": "cal_001", "image_path": "assets/calibration/cal_001.png",
                 "request": "Show a person leaping forward."}
        bs = core.build_brand_sources(self.pack, brief, "production")
        img, _ = core.resolve_image(self.pack.root, brief["image_path"])
        content = core.build_messages(bs, brief, img, core.brief_signals(brief["request"]))[1]["content"]
        images = [p for p in content if p.get("type") == "image_url"]
        self.assertEqual(len(images), 1 + len(self.pack.reference_ids))
        labels = [p["text"] for p in content if p.get("type") == "text"]
        self.assertTrue(any("TARGET_IMAGE" in t for t in labels))
        self.assertEqual(sum(t.startswith("REFERENCE_IMAGE") for t in labels), len(self.pack.reference_ids))

    def test_production_prompt_has_both_readings_rule_and_no_asset_ids(self):
        brief = {"asset_id": "review_001", "image_path": "assets/review/review_001.png",
                 "request": "Show a worker waving hello."}
        bs = core.build_brand_sources(self.pack, brief, "production")
        img, _ = core.resolve_image(self.pack.root, brief["image_path"])
        system = core.build_messages(bs, brief, img, core.brief_signals(brief["request"]))[0]["content"]
        self.assertIn("could plausibly be either an allowed body part", system)
        for leaked in ("cal_005", "review_002", "review_004", "feather duster", "feather_duster"):
            self.assertNotIn(leaked, system)

    def test_subjective_instruction_only_for_subjective_briefs(self):
        img, _ = core.resolve_image(self.pack.root, "assets/review/review_001.png")
        # Non-subjective brief: production forbids the field, no exact-word instruction.
        nb = {"asset_id": "review_001", "image_path": "x", "request": "Show a worker waving hello."}
        nb_sys = core.build_messages(core.build_brand_sources(self.pack, nb, "production"),
                                     nb, img, core.brief_signals(nb["request"]))[0]["content"]
        self.assertIn("Do NOT include a subjective_requirements", nb_sys)
        # Subjective brief: names the exact brief word.
        sb = {"asset_id": "cal_005", "image_path": "x",
              "request": "Show a woman sitting comfortably on a sofa and checking her phone."}
        sb_sys = core.build_messages(core.build_brand_sources(self.pack, sb, "production"),
                                     sb, img, core.brief_signals(sb["request"]))[0]["content"]
        self.assertIn('requests the subjective quality "comfortably"', sb_sys)
        # Baseline names neither.
        bl_sys = core.build_messages(core.build_brand_sources(self.pack, sb, "baseline"),
                                     sb, img, core.brief_signals(sb["request"]))[0]["content"]
        self.assertNotIn("subjective_requirements", bl_sys)


class TestModelBackend(unittest.TestCase):
    def test_usage_meta_no_usage_is_unavailable(self):
        m = core._usage_meta(None, "mdl", (0.1, 0.2))
        self.assertIsNone(m["cost"])
        self.assertEqual(m["cost_status"], "unavailable")

    def test_usage_meta_no_pricing_is_unavailable(self):
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        m = core._usage_meta(usage, "mdl", None)
        self.assertIsNone(m["cost"])
        self.assertEqual(m["cost_status"], "unavailable")

    def test_usage_meta_with_pricing_computes_cost(self):
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        m = core._usage_meta(usage, "mdl", (0.001, 0.002))
        self.assertAlmostEqual(m["cost"], 100 * 0.001 + 20 * 0.002)

    def test_fetch_pricing_missing_keys_returns_none(self):
        client = _FakeClient([_FakeModel({"id": "mdl", "pricing": {}})])
        self.assertIsNone(core._fetch_pricing(client, "mdl"))

    def test_fetch_pricing_partial_keys_returns_none(self):
        # only one price key present -> unavailable (never fake completion=0)
        client = _FakeClient([_FakeModel({"id": "mdl", "pricing": {"prompt": "0.1"}})])
        self.assertIsNone(core._fetch_pricing(client, "mdl"))

    def test_fetch_pricing_model_absent_returns_none(self):
        client = _FakeClient([_FakeModel({"id": "other", "pricing": {"prompt": "0.1", "completion": "0.2"}})])
        self.assertIsNone(core._fetch_pricing(client, "mdl"))

    def test_fetch_pricing_present_returns_prices(self):
        client = _FakeClient([_FakeModel({"id": "mdl", "pricing": {"prompt": "0.1", "completion": "0.2"}})])
        self.assertEqual(core._fetch_pricing(client, "mdl"), (0.1, 0.2))

    def test_truncated_call_is_counted_not_retried(self):
        pack = core.load_task_pack(PACK)
        brief = {"asset_id": "cal_001", "image_path": "assets/calibration/cal_001.png",
                 "request": "Show a person leaping forward."}
        bs = core.build_brand_sources(pack, brief, "production")
        img, _ = core.resolve_image(pack.root, brief["image_path"])

        def trunc(messages):
            raise core.TruncatedOutput("output truncated at max_tokens=10",
                                       {"model": "m", "prompt_tokens": 100, "completion_tokens": 50, "cost": 0.005})

        rec = core.review_asset(bs, brief, img, trunc, pack.schema)
        self.assertEqual(rec["processing_status"], "provider_error")
        self.assertEqual(rec["calls"], 1)      # counted
        self.assertEqual(rec["retries"], 0)    # not retried (identical request would truncate)
        self.assertEqual(rec["prompt_tokens"], 100)
        self.assertAlmostEqual(rec["cost_usd"], 0.005)


class TestMissingKey(unittest.TestCase):
    def test_missing_api_key_raises_runtimeerror(self):
        saved = os.environ.pop("RUNWARE_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                core.make_runware_model("google-gemini-3-1-flash-lite")
        finally:
            if saved is not None:
                os.environ["RUNWARE_API_KEY"] = saved


class TestFullBatch(unittest.TestCase):
    def test_batch_produces_valid_ordered_records(self):
        pack = core.load_task_pack(PACK)
        with TemporaryDirectory() as d:
            records = core.run_batch(pack, echo_model, Path(d) / "reviews.jsonl", prompt_version="production")
        self.assertEqual(len(records), 12)
        for brief, rec in zip(pack.briefs, records):
            self.assertEqual(rec["asset_id"], brief["asset_id"])
            self.assertEqual(rec["processing_status"], "completed")


if __name__ == "__main__":
    unittest.main()

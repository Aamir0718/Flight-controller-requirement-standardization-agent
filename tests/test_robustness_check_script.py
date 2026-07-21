"""Tests for scripts/robustness_check.py's logic, driven by fake LLM
clients -- no real Ollama needed. Verifies the crash/silent-failure
detection is correct, and that the 18 hand-written cases (including the
malformed/edge ones) survive the real pipeline machinery when the LLM
itself behaves reasonably -- the one thing this suite can't do in an
environment without a running Ollama instance is judge real model output
quality, which is exactly what scripts/robustness_check.py is for when
run for real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import robustness_check as rc  # noqa: E402

from llm.local_llm_client import LLMResult, OllamaUnavailableError  # noqa: E402
from pipeline.graph import build_graph  # noqa: E402


class _FakeReasonableClient:
    """A well-behaved model: echoes something plausible back for any
    input, including the malformed/edge ones (real models generally do
    produce *something*, even if it's low quality -- the point of this
    fake is to exercise the pipeline's handling of that output, not to
    simulate a model refusing to answer)."""

    temperature = 0.2

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        return LLMResult(
            pattern="Ubiquitous",
            rewritten_text="The system shall perform the required function within a specified tolerance.",
            vague_terms=[],
            confidence=0.5,
            notes="best-effort rewrite of unusual input",
            raw={},
        )


class _AlwaysCrashesClient:
    temperature = 0.2

    def generate_structured(self, *args, **kwargs):
        raise RuntimeError("simulated model crash")


class _FakeGraphReturning:
    """A minimal stand-in for a compiled LangGraph: .invoke(state) returns
    a canned {"result": ...} dict, letting tests drive check_case()
    against an exact, hand-picked result shape rather than whatever a
    real (or even fake-LLM-backed) graph run happens to produce."""

    def __init__(self, result: dict):
        self._result = result

    def invoke(self, state):
        return {"result": self._result}


def _well_formed_result(**overrides) -> dict:
    base = {
        "original_text": "The system shall respond.",
        "source_location": {"source": "inline"},
        "rule_flags": [],
        "ears_pattern": {"pattern": "Ubiquitous", "confidence": 0.8, "matched_keywords": [], "reason": "r"},
        "candidates": [
            {"index": 0, "rewritten_text": "A", "score": 90.0},
            {"index": 1, "rewritten_text": "B", "score": 80.0},
            {"index": 2, "rewritten_text": "C", "score": 70.0},
        ],
        "recommended_index": 0,
        "recommended_text": "A",
        "recommended_score": 90.0,
        "vague_term_suggestions": [],
        "compliance_threshold": 80.0,
        "needs_human_review": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# The case list itself
# ---------------------------------------------------------------------------


def test_between_15_and_20_cases():
    assert 15 <= len(rc.CASES) <= 20


def test_includes_malformed_and_normal_categories():
    categories = {c["category"] for c in rc.CASES}
    assert categories == {"normal", "malformed"}
    assert sum(1 for c in rc.CASES if c["category"] == "malformed") >= 5


def test_malformed_cases_cover_the_required_edge_cases():
    texts = [c["text"] for c in rc.CASES]
    assert "" in texts  # empty string
    assert any(t.strip() == "" and t != "" for t in texts)  # whitespace-only
    assert any(len(t) > 500 for t in texts)  # extremely long compound sentence
    assert any(any(ord(ch) > 0x2E80 for ch in t) for t in texts)  # non-English (CJK/Arabic range)
    assert any(
        any(ch.isdigit() for ch in t) and "shall" in t and not any(u in t for u in ["mm", "ms", "PSI", "Hz", "degrees", "feet", "pounds"])
        for t in texts
    )  # a number with no unit


def test_case_ids_are_unique():
    ids = [c["id"] for c in rc.CASES]
    assert len(ids) == len(set(ids))


def test_cases_are_not_copied_from_the_golden_dataset():
    rc._assert_cases_not_in_golden_dataset()  # must not raise


def test_assert_cases_not_in_golden_dataset_actually_detects_a_copy(monkeypatch):
    golden = json.loads((rc.GOLDEN_DIR / "fewshot.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        rc, "CASES", [{"id": "copied", "category": "normal", "text": golden[0]["bad_requirement"]}]
    )
    try:
        rc._assert_cases_not_in_golden_dataset()
    except AssertionError as exc:
        assert "copied" in str(exc)
    else:
        raise AssertionError("expected _assert_cases_not_in_golden_dataset to catch the copy")


# ---------------------------------------------------------------------------
# _is_well_formed
# ---------------------------------------------------------------------------


class TestIsWellFormed:
    def test_accepts_a_valid_result(self):
        assert rc._is_well_formed(_well_formed_result()) == []

    def test_flags_missing_keys(self):
        result = _well_formed_result()
        del result["needs_human_review"]
        problems = rc._is_well_formed(result)
        assert any("missing keys" in p for p in problems)

    def test_flags_wrong_candidate_count(self):
        result = _well_formed_result(candidates=_well_formed_result()["candidates"][:2])
        problems = rc._is_well_formed(result)
        assert any("3 candidates" in p for p in problems)

    def test_flags_out_of_range_recommended_index(self):
        result = _well_formed_result(recommended_index=5)
        problems = rc._is_well_formed(result)
        assert any("recommended_index" in p for p in problems)

    def test_flags_score_out_of_range(self):
        result = _well_formed_result(recommended_score=150.0)
        problems = rc._is_well_formed(result)
        assert any("out of [0, 100]" in p for p in problems)

    def test_flags_non_bool_needs_human_review(self):
        result = _well_formed_result(needs_human_review="yes")
        problems = rc._is_well_formed(result)
        assert any("needs_human_review is not a bool" in p for p in problems)


# ---------------------------------------------------------------------------
# check_case
# ---------------------------------------------------------------------------


class TestCheckCase:
    def test_pipeline_exception_is_recorded_not_raised(self):
        graph = build_graph(client=_AlwaysCrashesClient())
        record = rc.check_case(graph, {"id": "x", "category": "normal", "text": "The system shall act."})
        assert record["crashed"] is True
        assert "RuntimeError" in record["error"]
        assert record["produced_valid_output"] is False

    def test_normal_success_is_a_valid_output(self):
        graph = build_graph(client=_FakeReasonableClient())
        record = rc.check_case(graph, {"id": "x", "category": "normal", "text": "The system shall act."})
        assert record["crashed"] is False
        assert record["produced_valid_output"] is True

    def test_structurally_broken_result_is_not_a_valid_output(self):
        broken = _well_formed_result()
        del broken["needs_human_review"]
        graph = _FakeGraphReturning(broken)
        record = rc.check_case(graph, {"id": "x", "category": "normal", "text": "irrelevant"})
        assert record["crashed"] is False
        assert record["structural_problems"]
        assert record["produced_valid_output"] is False

    def test_empty_text_and_false_needs_human_review_is_the_silent_failure_case(self):
        silent_failure = _well_formed_result(recommended_text="", needs_human_review=False)
        graph = _FakeGraphReturning(silent_failure)
        record = rc.check_case(graph, {"id": "x", "category": "malformed", "text": ""})
        assert record["crashed"] is False
        assert record["produced_valid_output"] is False

    def test_empty_text_but_needs_human_review_true_is_not_a_silent_failure(self):
        honest_flag = _well_formed_result(recommended_text="", needs_human_review=True)
        graph = _FakeGraphReturning(honest_flag)
        record = rc.check_case(graph, {"id": "x", "category": "malformed", "text": ""})
        assert record["crashed"] is False
        assert record["produced_valid_output"] is True


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_all_handled_safely_when_nothing_crashed_or_silently_failed(self):
        records = [
            {"id": "a", "crashed": False, "produced_valid_output": True, "structural_problems": []},
            {"id": "b", "crashed": False, "produced_valid_output": True, "structural_problems": []},
        ]
        report = rc.build_report(records)
        assert report["all_cases_handled_safely"] is True
        assert report["crashed"] == 0
        assert report["silent_failures"] == 0

    def test_flags_crashes_and_silent_failures_separately(self):
        records = [
            {"id": "crashed-one", "crashed": True, "error": "boom", "produced_valid_output": False},
            {"id": "silent-one", "crashed": False, "produced_valid_output": False, "structural_problems": []},
            {"id": "ok-one", "crashed": False, "produced_valid_output": True, "structural_problems": []},
        ]
        report = rc.build_report(records)
        assert report["all_cases_handled_safely"] is False
        assert report["crashed_case_ids"] == ["crashed-one"]
        assert report["silent_failure_case_ids"] == ["silent-one"]


# ---------------------------------------------------------------------------
# End-to-end with a fake client, over the real 18 hand-written cases
# ---------------------------------------------------------------------------


def test_run_robustness_check_end_to_end_handles_every_real_case_safely():
    graph = build_graph(client=_FakeReasonableClient())
    report = rc.run_robustness_check(graph)

    assert report["total_cases"] == len(rc.CASES)
    assert report["crashed"] == 0
    assert report["all_cases_handled_safely"] is True


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMain:
    def test_fails_fast_and_writes_nothing_when_ollama_unreachable(self, tmp_path, monkeypatch):
        class _Unavailable:
            def check_reachable(self):
                raise OllamaUnavailableError("simulated")

        monkeypatch.setattr(rc, "LocalLLMClient", _Unavailable)
        output_path = tmp_path / "robustness_results.json"

        exit_code = rc.main(["--output", str(output_path)])

        assert exit_code == 1
        assert not output_path.exists()

    def test_writes_a_valid_report_when_reachable(self, tmp_path, monkeypatch):
        fake_client = _FakeReasonableClient()
        fake_client.check_reachable = lambda: None
        monkeypatch.setattr(rc, "LocalLLMClient", lambda: fake_client)
        output_path = tmp_path / "robustness_results.json"

        exit_code = rc.main(["--output", str(output_path)])

        assert exit_code == 0
        assert output_path.exists()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["total_cases"] == len(rc.CASES)
        assert report["all_cases_handled_safely"] is True

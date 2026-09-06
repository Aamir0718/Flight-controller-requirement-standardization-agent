"""Tests for scripts/evaluate.py's logic, driven entirely by a fake LLM
client -- no real LLM endpoint needed, so this always runs. The point is to
verify the metric computation (accuracy %, vague-term handling %,
scoring-comparison %, failure collection) is correct, since a live 60-example
x 3-candidate run isn't something this suite can exercise for real in an
environment without a reachable LLM endpoint.

scripts/ isn't an installed package (only src/ is, per pyproject.toml), so
these tests add it to sys.path directly, the same way evaluate.py adds
src/ to its own sys.path at import time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import evaluate  # noqa: E402

from llm.local_llm_client import LLMResult, LLMUnavailableError  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "golden"


class _FakeIdealClient:
    """Returns the example's own compliant_version as one candidate (so
    the recommender has a genuinely high-scoring, no-vague-terms option
    to pick) and the unmodified bad_requirement as the other two -- lets
    tests exercise real eval.json rows without a real model."""

    temperature = 0.2

    def __init__(self, examples_by_text: dict[str, dict]):
        self._examples_by_text = examples_by_text
        self.calls = 0

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        self.calls += 1
        # crude but sufficient: the original text is quoted verbatim in
        # the user_prompt by src/llm/prompts.py's build_prompt()
        original = next(
            (t for t in self._examples_by_text if t in user_prompt), None
        )
        example = self._examples_by_text.get(original)
        slot = (self.calls - 1) % 3
        if example and slot == 1:
            text = example["compliant_version"]
        else:
            text = original or "The system shall respond."
        return LLMResult(pattern="Ubiquitous", rewritten_text=text, vague_terms=[], confidence=0.8, notes="", raw={})


class _AlwaysFailsClient:
    temperature = 0.2

    def generate_structured(self, *args, **kwargs):
        raise RuntimeError("simulated model failure")


class _RaisesUnavailableClient:
    def check_reachable(self):
        raise LLMUnavailableError("LLM endpoint not reachable (simulated)")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def test_load_eval_examples_returns_all_60():
    examples = evaluate.load_eval_examples()
    assert len(examples) == 60


def test_load_eval_examples_respects_limit():
    examples = evaluate.load_eval_examples(limit=5)
    assert len(examples) == 5


# ---------------------------------------------------------------------------
# evaluate_example
# ---------------------------------------------------------------------------


class TestEvaluateExample:
    def test_deterministic_fields_are_populated_even_when_pipeline_fails(self):
        from pipeline.graph import build_graph

        example = evaluate.load_eval_examples()[0]
        graph = build_graph(client=_AlwaysFailsClient())

        record = evaluate.evaluate_example(graph, example)

        assert record["id"] == example["id"]
        assert "ears_pattern_correct" in record  # computed without the LLM
        assert "is_vague_term_example" in record
        assert "pipeline_error" in record
        assert "RuntimeError" in record["pipeline_error"]
        assert any("Pipeline raised" in issue for issue in record["issues"])

    def test_successful_run_populates_scoring_and_vague_term_fields(self):
        from pipeline.graph import build_graph

        examples = evaluate.load_eval_examples()
        by_text = {e["bad_requirement"]: e for e in examples}
        example = examples[0]
        graph = build_graph(client=_FakeIdealClient(by_text))

        record = evaluate.evaluate_example(graph, example)

        assert "pipeline_error" not in record
        assert isinstance(record["recommended_score"], float)
        # _FakeIdealClient returns the golden compliant_version, which
        # confirms on the very first attempt (src/pipeline/
        # candidate_generator.py's confirm-loop stops there) -- 0
        # alternates, not always 2, now that generation doesn't always
        # make 3 calls regardless of whether the first was already good.
        assert record["alternate_scores"] == []
        assert isinstance(record["recommended_has_highest_score"], bool)
        assert isinstance(record["needs_human_review"], bool)
        assert isinstance(record["has_invented_number"], bool)

    def test_never_raises_regardless_of_client_behavior(self):
        from pipeline.graph import build_graph

        example = evaluate.load_eval_examples()[0]
        graph = build_graph(client=_AlwaysFailsClient())
        evaluate.evaluate_example(graph, example)  # must not raise


# ---------------------------------------------------------------------------
# build_report (pure aggregation logic)
# ---------------------------------------------------------------------------


class TestBuildReport:
    def _record(self, **overrides):
        base = {
            "id": "X", "ears_pattern_correct": True, "is_vague_term_example": False,
            "issues": [],
        }
        base.update(overrides)
        return base

    def test_ears_accuracy_counts_correct_and_incorrect(self):
        records = [
            self._record(id="1", ears_pattern_correct=True),
            self._record(id="2", ears_pattern_correct=True),
            self._record(id="3", ears_pattern_correct=False, issues=["EARS pattern misclassified: ..."]),
        ]
        for r in records:
            r.update(recommended_score=90.0, alternate_scores=[80.0, 70.0],
                      recommended_has_highest_score=True, needs_human_review=False,
                      vague_term_suggestions=[], has_invented_number=False)

        report = evaluate.build_report(records)
        assert report["ears_pattern_classification"] == {"correct": 2, "total": 3, "pct_correct": 66.7}

    def test_vague_term_percentages_use_vague_examples_as_denominator(self):
        records = [
            self._record(id="1", is_vague_term_example=True, recommended_score=90.0,
                         alternate_scores=[80.0], recommended_has_highest_score=True,
                         needs_human_review=True, vague_term_suggestions=[{"term": "t", "suggestion": "s"}],
                         has_invented_number=False),
            self._record(id="2", is_vague_term_example=True, recommended_score=90.0,
                         alternate_scores=[80.0], recommended_has_highest_score=True,
                         needs_human_review=False, vague_term_suggestions=[],
                         has_invented_number=False),
            self._record(id="3", is_vague_term_example=False, recommended_score=100.0,
                         alternate_scores=[80.0], recommended_has_highest_score=True,
                         needs_human_review=False, vague_term_suggestions=[],
                         has_invented_number=False),
        ]
        report = evaluate.build_report(records)
        vague = report["vague_term_handling"]
        assert vague["total_vague_term_examples"] == 2
        assert vague["pct_with_suggestion"] == 50.0   # 1 of 2 vague examples
        assert vague["pct_with_needs_human_review"] == 50.0  # 1 of 2
        assert vague["pct_invented_numbers"] == 0.0  # 0 of 3 evaluated

    def test_invented_number_percentage_uses_all_evaluated_as_denominator(self):
        records = [
            self._record(id="1", recommended_score=90.0, alternate_scores=[80.0],
                         recommended_has_highest_score=True, needs_human_review=False,
                         vague_term_suggestions=[], has_invented_number=True),
            self._record(id="2", recommended_score=90.0, alternate_scores=[80.0],
                         recommended_has_highest_score=True, needs_human_review=False,
                         vague_term_suggestions=[], has_invented_number=False),
        ]
        report = evaluate.build_report(records)
        assert report["vague_term_handling"]["pct_invented_numbers"] == 50.0

    def test_recommended_not_highest_score_is_tracked_with_ids(self):
        records = [
            self._record(id="won", recommended_score=100.0, alternate_scores=[90.0, 80.0],
                         recommended_has_highest_score=True, needs_human_review=False,
                         vague_term_suggestions=[], has_invented_number=False),
            self._record(id="lost", recommended_score=80.0, alternate_scores=[100.0, 90.0],
                         recommended_has_highest_score=False, needs_human_review=True,
                         vague_term_suggestions=[], has_invented_number=False),
        ]
        report = evaluate.build_report(records)
        scoring = report["compliance_scoring"]
        assert scoring["pct_recommended_not_highest_score"] == 50.0
        assert scoring["not_highest_score_example_ids"] == ["lost"]
        assert scoring["avg_recommended_score"] == 90.0
        assert scoring["avg_alternate_score"] == 90.0  # mean of [90, 80, 100, 90]

    def test_failures_collects_every_record_with_at_least_one_issue(self):
        records = [
            self._record(id="clean", issues=[], recommended_score=100.0, alternate_scores=[90.0],
                         recommended_has_highest_score=True, needs_human_review=False,
                         vague_term_suggestions=[], has_invented_number=False),
            self._record(id="bad", issues=["something wrong"], recommended_score=50.0,
                         alternate_scores=[60.0], recommended_has_highest_score=False,
                         needs_human_review=True, vague_term_suggestions=[], has_invented_number=False),
        ]
        report = evaluate.build_report(records)
        assert [f["id"] for f in report["failures"]] == ["bad"]

    def test_pipeline_errors_excluded_from_scoring_but_counted_separately(self):
        records = [
            self._record(id="errored", issues=["Pipeline raised RuntimeError: x"], pipeline_error="RuntimeError: x"),
            self._record(id="ok", recommended_score=90.0, alternate_scores=[80.0],
                         recommended_has_highest_score=True, needs_human_review=False,
                         vague_term_suggestions=[], has_invented_number=False),
        ]
        report = evaluate.build_report(records)
        assert report["pipeline_errors"] == 1
        assert report["evaluated"] == 1
        assert report["compliance_scoring"]["avg_recommended_score"] == 90.0  # errored one excluded

    def test_empty_input_does_not_divide_by_zero(self):
        report = evaluate.build_report([])
        assert report["ears_pattern_classification"]["pct_correct"] is None
        assert report["vague_term_handling"]["pct_with_suggestion"] is None
        assert report["compliance_scoring"]["avg_recommended_score"] is None


# ---------------------------------------------------------------------------
# End-to-end with a fake client, over real eval.json rows
# ---------------------------------------------------------------------------


def test_run_evaluation_end_to_end_on_real_eval_examples_with_fake_client():
    from pipeline.graph import build_graph

    examples = evaluate.load_eval_examples(limit=6)
    by_text = {e["bad_requirement"]: e for e in examples}
    graph = build_graph(client=_FakeIdealClient(by_text))

    report = evaluate.run_evaluation(graph, examples)

    assert report["eval_set_size"] == 6
    assert report["evaluated"] == 6
    assert report["pipeline_errors"] == 0
    assert 0.0 <= report["ears_pattern_classification"]["pct_correct"] <= 100.0
    assert isinstance(report["failures"], list)


# ---------------------------------------------------------------------------
# main() CLI: fails fast without the LLM endpoint, writes a valid report when reachable
# ---------------------------------------------------------------------------


class TestMain:
    def test_fails_fast_and_writes_nothing_when_ollama_unreachable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(evaluate, "LocalLLMClient", _RaisesUnavailableClient)
        output_path = tmp_path / "eval_results.json"

        exit_code = evaluate.main(["--limit", "1", "--output", str(output_path)])

        assert exit_code == 1
        assert not output_path.exists()

    def test_writes_a_valid_report_when_reachable(self, tmp_path, monkeypatch):
        examples = evaluate.load_eval_examples(limit=3)
        by_text = {e["bad_requirement"]: e for e in examples}
        fake_client = _FakeIdealClient(by_text)
        fake_client.check_reachable = lambda: None

        monkeypatch.setattr(evaluate, "LocalLLMClient", lambda: fake_client)
        output_path = tmp_path / "eval_results.json"

        exit_code = evaluate.main(["--limit", "3", "--output", str(output_path)])

        assert exit_code == 0
        assert output_path.exists()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["eval_set_size"] == 3
        assert "elapsed_seconds" in report

"""Fast, offline tests for src/pipeline/graph.py -- node wiring, state
flow, error handling, and the needs_human_review threshold logic. Every
test here uses a fake LLM client (no network) so it always runs.

The real end-to-end test against a live Ollama instance (and against
requirements never seen in the golden dataset) lives in
tests/test_graph_integration.py and auto-skips when Ollama isn't running.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm.local_llm_client import LLMResult, VagueTermSuggestion
from pipeline.graph import PipelineState, build_graph, run_requirement, run_workbook

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CLEAN_TEXT = "The gateway shall log connection attempts."
# Already states "10 Hz" so COMPLIANT_REWRITE's "10 frames per second"
# below is the same fact restated, not an invented number (see
# src/pipeline/recommender.py's invented-number safeguard) -- these are
# graph-wiring tests, not safeguard tests (those live in
# tests/test_recommender.py::TestInventedNumberSafeguard).
VAGUE_TEXT = (
    "While in orbit, the star tracker shall track reference stars continuously "
    "at a minimum rate of 10 Hz."
)
COMPLIANT_REWRITE = (
    "While in orbit, the star tracker shall process star field patterns at a "
    "minimum rate of 10 frames per second."
)


class FakeLLMClient:
    """Always returns the same 3 canned rewrites, regardless of prompt --
    good enough for exercising graph wiring without needing real content
    variety (that's tested elsewhere, in test_candidate_generator.py)."""

    temperature = 0.2

    def __init__(self, texts=None):
        self._texts = texts or [VAGUE_TEXT, COMPLIANT_REWRITE, VAGUE_TEXT]
        self.calls: list[dict] = []

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt,
             "temperature": temperature, "seed": seed}
        )
        text = self._texts[(len(self.calls) - 1) % len(self._texts)]
        return LLMResult(
            pattern="State-driven", rewritten_text=text, vague_terms=[], confidence=0.8,
            notes="", raw={},
        )


def _graph(client=None, compliance_threshold=80.0):
    return build_graph(client=client or FakeLLMClient(), compliance_threshold=compliance_threshold)


class TestRunRequirementOutputShape:
    def test_output_has_all_required_fields(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert set(result.keys()) >= {
            "original_text", "source_location", "rule_flags", "ears_pattern",
            "candidates", "recommended_index", "vague_term_suggestions",
            "needs_human_review",
        }

    def test_original_text_is_preserved_verbatim(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert result["original_text"] == VAGUE_TEXT

    def test_default_source_location_when_none_given(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert result["source_location"] == {"source": "inline"}

    def test_custom_source_location_is_passed_through(self):
        loc = {"sheet_name": "Requirements", "cell_reference": "B7"}
        result = run_requirement(_graph(), VAGUE_TEXT, source_location=loc)
        assert result["source_location"] == loc

    def test_rule_flags_reflect_real_detector_output(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert any(f["violation_type"] == "vague_term" for f in result["rule_flags"])
        assert any("continuously" in f["span"] for f in result["rule_flags"])

    def test_clean_text_has_no_rule_flags(self):
        result = run_requirement(_graph(FakeLLMClient([CLEAN_TEXT] * 3)), CLEAN_TEXT)
        assert result["rule_flags"] == []

    def test_ears_pattern_reflects_real_classifier_output(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert result["ears_pattern"]["pattern"] == "State-driven"

    def test_exactly_3_candidates_by_default(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        assert len(result["candidates"]) == 3
        assert [c["index"] for c in result["candidates"]] == [0, 1, 2]

    def test_each_candidate_has_score_and_rule_breakdown(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        for c in result["candidates"]:
            assert isinstance(c["score"], float)
            assert isinstance(c["passed_rule_ids"], list)
            assert isinstance(c["failed_rules"], list)

    def test_recommended_index_points_at_the_best_scoring_candidate(self):
        result = run_requirement(_graph(), VAGUE_TEXT)
        scores = [c["score"] for c in result["candidates"]]
        assert result["candidates"][result["recommended_index"]]["score"] == max(scores)

    def test_vague_term_suggestions_come_from_the_recommended_candidate(self):
        client = FakeLLMClient([VAGUE_TEXT, COMPLIANT_REWRITE, VAGUE_TEXT])
        graph = build_graph(client=client, compliance_threshold=80.0)
        # patch in vague_terms on what will become the recommended candidate
        real_generate_structured = client.generate_structured

        def with_vague_terms(system_prompt, user_prompt, *, temperature=None, seed=None):
            result = real_generate_structured(system_prompt, user_prompt, temperature=temperature, seed=seed)
            if result.rewritten_text == COMPLIANT_REWRITE:
                result = LLMResult(
                    pattern=result.pattern,
                    rewritten_text=result.rewritten_text,
                    vague_terms=[VagueTermSuggestion(term="rate", suggestion="confirm units")],
                    confidence=result.confidence,
                    notes=result.notes,
                    raw=result.raw,
                )
            return result

        client.generate_structured = with_vague_terms
        result = run_requirement(graph, VAGUE_TEXT)
        assert result["vague_term_suggestions"] == [{"term": "rate", "suggestion": "confirm units"}]


class TestNeedsHumanReview:
    def test_false_when_recommended_score_meets_threshold(self):
        result = run_requirement(_graph(compliance_threshold=80.0), VAGUE_TEXT)
        assert result["recommended_score"] >= 80.0
        assert result["needs_human_review"] is False

    def test_true_when_recommended_score_below_threshold(self):
        # 100.5 is above the scorer's 0-100 range, so this is guaranteed to
        # trip needs_human_review regardless of which candidate wins.
        result = run_requirement(_graph(compliance_threshold=100.5), VAGUE_TEXT)
        assert result["recommended_score"] < 100.5
        assert result["needs_human_review"] is True

    def test_configurable_threshold_is_echoed_in_result(self):
        result = run_requirement(_graph(compliance_threshold=42.0), VAGUE_TEXT)
        assert result["compliance_threshold"] == 42.0

    def test_threshold_defaults_to_config_settings_yaml(self):
        from config import get_settings

        expected = get_settings()["pipeline"]["compliance_threshold"]
        graph = build_graph(client=FakeLLMClient())
        result = run_requirement(graph, VAGUE_TEXT)
        assert result["compliance_threshold"] == expected

    def test_true_when_every_candidate_invented_a_number_even_with_a_perfect_score(self):
        # All 3 candidates fabricate a different number nowhere in the
        # original text. recommender.py still has to pick one to rank
        # first (the highest scorer among them), but Finalize must not
        # trust it just because compliance_threshold is met -- see
        # src/pipeline/recommender.py's module docstring.
        no_numbers_original = "The star tracker shall track reference stars continuously."
        client = FakeLLMClient([
            "The star tracker shall track reference stars at a minimum rate of 12 Hz.",
            "The star tracker shall track reference stars at a minimum rate of 47 Hz.",
            "The star tracker shall track reference stars at a minimum rate of 99 Hz.",
        ])
        result = run_requirement(_graph(client, compliance_threshold=1.0), no_numbers_original)

        assert result["recommended_score"] >= 1.0  # would pass the threshold alone...
        assert result["candidates"][result["recommended_index"]]["has_invented_number"] is True
        assert result["needs_human_review"] is True  # ...but the safeguard overrides it

    def test_false_when_recommended_candidate_reuses_a_number_already_in_the_original(self):
        original_with_number = "The valve shall close within 100 milliseconds of the command."
        client = FakeLLMClient([
            "When commanded, the valve shall close within 100 ms.",
            "When commanded, the valve shall close within 100 ms.",
            "When commanded, the valve shall close within 100 ms.",
        ])
        result = run_requirement(_graph(client, compliance_threshold=80.0), original_with_number)

        assert result["candidates"][result["recommended_index"]]["has_invented_number"] is False
        assert result["needs_human_review"] is False


class TestErrorHandling:
    def test_raises_when_neither_requirement_text_nor_file_path_given(self):
        graph = _graph()
        with pytest.raises(ValueError, match="requirement_text.*file_path|file_path.*requirement_text"):
            graph.invoke({})

    def test_raises_on_ambiguous_multi_candidate_file_without_cell_reference(self):
        graph = _graph()
        with pytest.raises(ValueError, match="cell_reference"):
            graph.invoke({"file_path": str(FIXTURES_DIR / "messy_multi_sheet.xlsx")})

    def test_empty_string_requirement_text_is_not_mistaken_for_missing_input(self):
        # "" is falsy in Python; Parse must distinguish "key present but
        # empty" from "key not provided at all" and not fall through to
        # requiring file_path (regression: this used to raise ValueError).
        result = run_requirement(_graph(), "")
        assert result["original_text"] == ""
        assert isinstance(result["needs_human_review"], bool)


class TestParseNodeWithRealFile:
    """The Parse node's file_path branch genuinely drives
    src/ingestion/parser.py -- exercised here without needing Ollama."""

    def test_selects_the_requested_cell(self):
        graph = _graph()
        result = graph.invoke(
            {"file_path": str(FIXTURES_DIR / "messy_multi_sheet.xlsx"), "cell_reference": "C4"}
        )
        assert result["result"]["original_text"] == (
            "The flight control computer shall compute attitude at 50 Hz."
        )
        location = result["result"]["source_location"]
        assert location["column_letter"] == "C"
        assert location["row"] == 4

    def test_raises_for_a_cell_reference_with_no_candidate(self):
        graph = _graph()
        with pytest.raises(ValueError, match="ZZ999"):
            graph.invoke(
                {"file_path": str(FIXTURES_DIR / "messy_multi_sheet.xlsx"), "cell_reference": "ZZ999"}
            )


class TestRunWorkbook:
    def test_returns_one_result_per_candidate_requirement(self):
        graph = _graph()
        results = run_workbook(graph, FIXTURES_DIR / "messy_multi_sheet.xlsx")
        assert len(results) > 1
        for r in results:
            assert r["original_text"]
            assert len(r["candidates"]) == 3

    def test_known_requirement_text_appears_among_results(self):
        graph = _graph()
        results = run_workbook(graph, FIXTURES_DIR / "messy_multi_sheet.xlsx")
        texts = {r["original_text"] for r in results}
        assert "The flight control computer shall compute attitude at 50 Hz." in texts

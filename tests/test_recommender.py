"""Tests for src/pipeline/recommender.py.

The centerpiece test drives the real pipeline (candidate_generator ->
recommender) through a mocked LLM client that returns 3 fixed candidate
strings of known, verified-in-advance quality, and confirms the
deterministic INCOSE scorer (not another LLM call) picks the objectively
best one. Score numbers below were computed once with
src/rules/incose_scorer.score_requirement() directly and are asserted
again here so a future scorer change that silently reorders these
candidates fails loudly.
"""

from __future__ import annotations

from llm.local_llm_client import LLMResult, VagueTermSuggestion
from pipeline.candidate_generator import Candidate, generate_candidates
from pipeline.recommender import (
    RecommendationResult,
    ScoredCandidate,
    find_invented_numbers,
    recommend,
)
from rules.incose_scorer import score_requirement


def _result(text: str, vague_terms=None, confidence=0.8, pattern="State-driven") -> LLMResult:
    return LLMResult(
        pattern=pattern,
        rewritten_text=text,
        vague_terms=vague_terms or [],
        confidence=confidence,
        notes="",
        raw={},
    )


def _candidate(index: int, text: str, **kwargs) -> Candidate:
    return Candidate(index=index, result=_result(text, **kwargs), temperature=0.2, seed=index)


# Original requirement backing WORST_TEXT/MEDIUM_TEXT/BEST_TEXT below --
# note it already states "10 Hz", so BEST_TEXT's "10 frames per second" is
# not an invented number (it's the same fact restated), keeping these
# ranking/tie-break tests focused on score-based ranking rather than
# tripping the invented-number safeguard (that safeguard has its own
# dedicated tests further down).
ORIGINAL_TEXT = "While in orbit, the star tracker shall track reference stars at approximately 10 Hz."

# --- Three texts of known, pre-verified quality (see module docstring) ---
WORST_TEXT = (  # score 92.9: fails R7 (vague terms) and R19 (combinator 'and')
    "While in orbit, the star tracker shall track and calibrate reference stars "
    "continuously and adequately."
)
MEDIUM_TEXT = (  # score 96.4: fails R7 only ('continuously')
    "While in orbit, the star tracker shall track reference stars continuously."
)
BEST_TEXT = (  # score 100.0: passes every automatable rule
    "While in orbit, the star tracker shall process star field patterns at a "
    "minimum rate of 10 frames per second."
)


def test_known_quality_texts_score_as_expected():
    """Pins down the fixture quality claims made in the module docstring."""
    assert score_requirement(WORST_TEXT).score == 92.9
    assert score_requirement(MEDIUM_TEXT).score == 96.4
    assert score_requirement(BEST_TEXT).score == 100.0


class TestScorerPicksObjectivelyBestCandidate:
    def test_mocked_llm_client_end_to_end(self):
        """This is the required test: a mocked LLM client returns 3 fixed
        candidate strings of known quality (deliberately NOT returned in
        quality order, so a bug that just picks index 0 would fail this),
        and the deterministic scorer must recommend the best one."""

        class FakeLLMClient:
            temperature = 0.2

            def __init__(self):
                # Scrambled order: medium, worst, best.
                self._texts = [MEDIUM_TEXT, WORST_TEXT, BEST_TEXT]
                self.calls = 0

            def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
                text = self._texts[self.calls]
                self.calls += 1
                return _result(text)

        client = FakeLLMClient()
        candidates = generate_candidates(client, "irrelevant for this test", flags=[])
        assert client.calls == 3

        recommendation = recommend(candidates, ORIGINAL_TEXT)

        assert isinstance(recommendation, RecommendationResult)
        assert recommendation.recommended_index == 2  # BEST_TEXT was call #3 (index 2)
        assert recommendation.recommended.rewritten_text == BEST_TEXT
        assert recommendation.recommended.score == 100.0

    def test_recommend_directly_on_candidates_without_generation(self):
        candidates = [
            _candidate(0, MEDIUM_TEXT),
            _candidate(1, WORST_TEXT),
            _candidate(2, BEST_TEXT),
        ]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        assert recommendation.recommended_index == 2

    def test_ranking_order_matches_score_order(self):
        candidates = [
            _candidate(0, WORST_TEXT),
            _candidate(1, BEST_TEXT),
            _candidate(2, MEDIUM_TEXT),
        ]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        by_index = {c.index: c.score for c in recommendation.candidates}
        assert by_index == {0: 92.9, 1: 100.0, 2: 96.4}
        assert recommendation.recommended_index == 1


class TestTieBreaking:
    def test_prefers_fewer_flagged_vague_terms_on_score_tie(self):
        # Same text -> identical score AND identical length, isolating the
        # vague_terms tie-break from the length tie-break.
        candidates = [
            _candidate(
                0, BEST_TEXT,
                vague_terms=[VagueTermSuggestion(term="rate", suggestion="clarify units")],
            ),
            _candidate(1, BEST_TEXT, vague_terms=[]),  # fewer vague terms
        ]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        assert recommendation.recommended_index == 1

    def test_prefers_shorter_text_when_score_and_vague_term_count_tie(self):
        short_text = "The gateway shall log connection attempts."
        long_text = (
            "The gateway shall log connection attempts to the non-volatile audit "
            "trail located in the secondary storage partition."
        )
        assert score_requirement(short_text).score == 100.0
        assert score_requirement(long_text).score == 100.0

        candidates = [
            _candidate(0, long_text, vague_terms=[]),
            _candidate(1, short_text, vague_terms=[]),
        ]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        assert recommendation.recommended_index == 1

    def test_stable_index_tie_break_when_everything_else_ties(self):
        candidates = [_candidate(0, BEST_TEXT), _candidate(1, BEST_TEXT)]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        assert recommendation.recommended_index == 0  # first one wins, deterministically


class TestOutputFormat:
    def test_all_candidates_present_with_scores_and_rule_breakdown(self):
        candidates = [
            _candidate(0, WORST_TEXT),
            _candidate(1, MEDIUM_TEXT),
            _candidate(2, BEST_TEXT),
        ]
        recommendation = recommend(candidates, ORIGINAL_TEXT)

        assert len(recommendation.candidates) == 3
        for c in recommendation.candidates:
            assert isinstance(c, ScoredCandidate)
            assert isinstance(c.score, float)
            assert isinstance(c.passed_rule_ids, list)
            assert isinstance(c.failed_rules, list)
            assert len(c.passed_rule_ids) + len(c.failed_rules) == c.total_rules

        assert 0 <= recommendation.recommended_index < len(recommendation.candidates)

    def test_failed_rules_carry_id_and_reasons_matching_the_scorer_directly(self):
        candidates = [_candidate(0, WORST_TEXT)]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        scored = recommendation.candidates[0]

        direct = score_requirement(WORST_TEXT)
        assert {f.id for f in scored.failed_rules} == {f.id for f in direct.failed}
        assert scored.passed_rule_ids == direct.passed

    def test_to_dict_is_json_serializable(self):
        import json

        candidates = [_candidate(0, WORST_TEXT), _candidate(1, BEST_TEXT)]
        recommendation = recommend(candidates, ORIGINAL_TEXT)
        payload = recommendation.to_dict()

        assert set(payload.keys()) == {"candidates", "recommended_index"}
        assert len(payload["candidates"]) == 2
        json.dumps(payload)  # must not raise

    def test_recommend_rejects_empty_candidate_list(self):
        import pytest

        with pytest.raises(ValueError):
            recommend([], ORIGINAL_TEXT)


class TestInventedNumberSafeguard:
    """src/llm/prompts.py instructs the model to never invent a specific
    number for a flagged vague term -- only to describe what's missing.
    Nothing stops a model from ignoring that, so recommend() must catch it
    downstream: a candidate with a number not present anywhere in the
    original text must never be preferred over one without, even if the
    invented-number candidate scores higher on the INCOSE checks (a fake
    number satisfies R6/R33/R34 just as well as a real one)."""

    ORIGINAL = "While in orbit, the star tracker shall track reference stars continuously."

    def test_find_invented_numbers_ignores_numbers_already_in_original(self):
        original = "The valve shall close within 100 milliseconds."
        candidate = "The valve shall close within 100 ms of the command."
        assert find_invented_numbers(original, candidate) == []

    def test_find_invented_numbers_flags_a_new_number(self):
        original = "The star tracker shall track reference stars continuously."
        candidate = "The star tracker shall track reference stars at 10 Hz."
        assert find_invented_numbers(original, candidate) == ["10"]

    def test_find_invented_numbers_ignores_reformatted_same_value(self):
        original = "The heater shall maintain 50 degrees."
        candidate = "The heater shall maintain 50.0 degrees."
        assert find_invented_numbers(original, candidate) == []  # same value, not invented

    def test_candidate_with_invented_number_is_never_preferred_over_a_clean_one(self):
        # The invented-number candidate scores perfectly (a fake number
        # satisfies the numeric-precision rules); the honest candidate
        # that just flags the vague term instead scores worse, because it
        # still contains "continuously", AND has more flagged vague terms
        # (the normal tie-break would also favor the fabricated one).
        # Without the safeguard, ranking would pick the fabricated one on
        # every criterion.
        hallucinated = _candidate(
            0, "While in orbit, the star tracker shall track reference stars at a minimum rate of 47 Hz."
        )
        honest = _candidate(
            1,
            self.ORIGINAL,  # unchanged -- can't fix the vague term without a real number
            vague_terms=[VagueTermSuggestion(
                term="continuously",
                suggestion="specify the required star-tracking sample rate",
            )],
        )

        assert score_requirement(hallucinated.result.rewritten_text).score == 100.0  # looks perfect...
        assert score_requirement(honest.result.rewritten_text).score < 100.0  # ...and honest doesn't

        recommendation = recommend([hallucinated, honest], self.ORIGINAL)

        assert recommendation.candidates[0].has_invented_number is True
        assert recommendation.candidates[0].invented_numbers == ["47"]
        assert recommendation.recommended_index == 1  # ...but the honest one wins anyway
        assert recommendation.recommended.has_invented_number is False

    def test_top_ranked_candidate_still_flags_invented_number_when_all_3_have_one(self):
        candidates = [
            _candidate(0, "While in orbit, the star tracker shall track reference stars at 12 Hz."),
            _candidate(1, "While in orbit, the star tracker shall track reference stars at 47 Hz."),
            _candidate(2, "While in orbit, the star tracker shall track reference stars at 99 Hz."),
        ]
        recommendation = recommend(candidates, self.ORIGINAL)
        # No clean candidate exists to prefer -- the highest scorer among
        # the bad ones wins the ranking, but callers (graph.py's Finalize)
        # must still see has_invented_number = True and treat it as a hard
        # needs_human_review trigger, not a normal recommendation.
        assert recommendation.recommended.has_invented_number is True

    def test_invented_numbers_and_flag_appear_in_to_dict(self):
        candidates = [
            _candidate(0, "While in orbit, the star tracker shall track reference stars at 47 Hz."),
        ]
        recommendation = recommend(candidates, self.ORIGINAL)
        payload = recommendation.candidates[0].to_dict()
        assert payload["invented_numbers"] == ["47"]
        assert payload["has_invented_number"] is True

    def test_clean_candidate_has_no_invented_numbers_in_to_dict(self):
        candidates = [_candidate(0, self.ORIGINAL)]
        recommendation = recommend(candidates, self.ORIGINAL)
        payload = recommendation.candidates[0].to_dict()
        assert payload["invented_numbers"] == []
        assert payload["has_invented_number"] is False

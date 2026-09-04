"""Tests for src/consistency/analyzer.py -- specifically that contradiction
detection (the only part of consistency analysis that needs the LLM)
degrades gracefully when Ollama isn't reachable, rather than hanging or
crashing the whole analysis.

Duplicate/similarity detection is pure embeddings (sentence-transformers or
its TF-IDF fallback) and never touches the LLM at all -- these tests don't
need a real embedding model beyond whatever's already installed, and use
near-identical phrasing so similarity clears both thresholds regardless of
which embedding method is active.
"""

from __future__ import annotations

import pytest

from consistency.analyzer import ConsistencyAnalyzer, RelationshipType

# Near-identical wording so cosine similarity clears a permissive
# threshold under either sentence-transformers or the TF-IDF fallback --
# these tests care about contradiction-check behavior, not about tuning
# embedding similarity precisely.
TEXT_A = "The system shall log every connection attempt within 100 ms."
TEXT_B = "The system shall log every connection attempt within 100 milliseconds."

_PERMISSIVE_SETTINGS = {
    "consistency": {
        "duplicate_threshold": 0.999,  # so these pairs land in "medium" (contradiction-eligible), not "duplicate"
        "similarity_threshold": 0.5,
        "enable_contradiction_check": True,
    }
}


class _FakeUnreachableClient:
    def __init__(self):
        self.check_reachable_calls = 0

    def check_reachable(self):
        self.check_reachable_calls += 1
        raise RuntimeError("simulated: Ollama not reachable")


class _FakeReachableClient:
    def __init__(self, is_contradiction: bool = False):
        self.check_reachable_calls = 0
        self.generate_json_calls = 0
        self._is_contradiction = is_contradiction

    def check_reachable(self):
        self.check_reachable_calls += 1

    def generate_json(self, system_prompt, user_prompt, *, schema=None, required_keys=None, temperature=None):
        self.generate_json_calls += 1
        return {"is_contradiction": self._is_contradiction, "reason": "fake reason"}


def _analyzer(settings=None) -> ConsistencyAnalyzer:
    return ConsistencyAnalyzer(settings=settings or _PERMISSIVE_SETTINGS)


class TestLlmUnreachable:
    def test_duplicate_and_similarity_detection_still_works_without_llm(self):
        analyzer = _analyzer()
        analyzer._llm_client = _FakeUnreachableClient()

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": TEXT_A}, {"id": 2, "recommended_text": TEXT_B}],
        )

        # Similarity is still computed and a relationship still reported --
        # only the LLM-dependent contradiction check is affected.
        assert len(result.relationships) == 1
        assert result.relationships[0].relationship_type in (
            RelationshipType.SIMILAR,
            RelationshipType.DUPLICATE,
        )

    def test_contradiction_check_skipped_flag_is_set(self):
        analyzer = _analyzer()
        analyzer._llm_client = _FakeUnreachableClient()

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": TEXT_A}, {"id": 2, "recommended_text": TEXT_B}],
        )
        assert result.contradiction_check_skipped is True

    def test_check_reachable_is_called_at_most_once_per_run_not_per_pair(self):
        # The actual fix: this used to call check_reachable() once PER PAIR
        # inside _check_contradiction(), which meant a run with many
        # medium-similarity pairs would retry a doomed connection that many
        # times. Now it's checked once and cached for the whole run.
        analyzer = _analyzer()
        fake_client = _FakeUnreachableClient()
        analyzer._llm_client = fake_client

        # 4 near-identical requirements -> 6 pairs, all similar enough to
        # be contradiction-eligible under the permissive thresholds above.
        texts = [TEXT_A, TEXT_B, TEXT_A + " ", TEXT_B + " "]
        requirements = [{"id": i, "recommended_text": t} for i, t in enumerate(texts)]

        analyzer.analyze_requirements(run_id=1, requirements=requirements)

        assert fake_client.check_reachable_calls <= 1

    def test_no_relationships_at_all_never_touches_the_llm(self):
        # No pair reaches similarity_threshold -> _is_llm_reachable() is
        # never even called, and contradiction_check_skipped stays False
        # (nothing needed skipping, contradiction checking was simply
        # never attempted).
        analyzer = _analyzer(
            settings={
                "consistency": {
                    "duplicate_threshold": 0.999,
                    "similarity_threshold": 0.999,  # nothing will clear this
                    "enable_contradiction_check": True,
                }
            }
        )
        fake_client = _FakeUnreachableClient()
        analyzer._llm_client = fake_client

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[
                {"id": 1, "recommended_text": "The gateway shall log connections."},
                {"id": 2, "recommended_text": "The autopilot shall disengage on overforce."},
            ],
        )

        assert fake_client.check_reachable_calls == 0
        assert result.contradiction_check_skipped is False


class TestLlmReachable:
    def test_contradiction_check_runs_and_is_not_skipped(self):
        analyzer = _analyzer()
        analyzer._llm_client = _FakeReachableClient(is_contradiction=False)

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": TEXT_A}, {"id": 2, "recommended_text": TEXT_B}],
        )
        assert result.contradiction_check_skipped is False

    def test_llm_reported_contradiction_is_classified_as_such(self):
        analyzer = _analyzer()
        analyzer._llm_client = _FakeReachableClient(is_contradiction=True)

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": TEXT_A}, {"id": 2, "recommended_text": TEXT_B}],
        )
        assert len(result.relationships) == 1
        assert result.relationships[0].relationship_type == RelationshipType.CONTRADICTION


class TestContradictionCheckDisabled:
    def test_disabled_in_config_never_touches_the_llm_and_is_not_reported_as_skipped(self):
        analyzer = _analyzer(
            settings={
                "consistency": {
                    "duplicate_threshold": 0.999,
                    "similarity_threshold": 0.5,
                    "enable_contradiction_check": False,
                }
            }
        )
        fake_client = _FakeUnreachableClient()
        analyzer._llm_client = fake_client

        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": TEXT_A}, {"id": 2, "recommended_text": TEXT_B}],
        )

        assert fake_client.check_reachable_calls == 0
        # Disabled by configuration, not "skipped due to failure" -- an
        # important distinction for what message a human sees.
        assert result.contradiction_check_skipped is False

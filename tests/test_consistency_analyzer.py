"""Tests for src/consistency/analyzer.py:

- The mechanical negation-based contradiction check (_is_negation_
  contradiction) -- catches "same requirement, one side says 'not'"
  entirely without the LLM, so it works even when the LLM is unreachable.
- That LLM-based contradiction detection (for contradictions that AREN'T
  a simple negation, e.g. "enable" vs "disable") degrades gracefully when
  it isn't reachable, rather than hanging or crashing the whole analysis.

Duplicate/similarity detection is pure embeddings (sentence-transformers or
its TF-IDF fallback) and never touches the LLM at all -- these tests don't
need a real embedding model beyond whatever's already installed, and use
near-identical phrasing so similarity clears both thresholds regardless of
which embedding method is active.
"""

from __future__ import annotations

import pytest

from consistency.analyzer import ConsistencyAnalyzer, RelationshipType, _is_negation_contradiction

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

    def test_a_confirmed_contradiction_wins_even_above_duplicate_threshold(self):
        # The regression this guards against: a contradiction pair (same
        # sentence, one word flipped -- "shall switch" vs "shall not
        # switch") is often textually so close it clears
        # duplicate_threshold too. Classifying duplicate BEFORE checking
        # contradiction would mislabel it "Duplicate" and never even ask
        # the LLM -- silently hiding the more serious defect behind the
        # more benign one. Real duplicate_threshold (0.95) here, on purpose.
        analyzer = _analyzer(
            settings={
                "consistency": {
                    "duplicate_threshold": 0.95,
                    "similarity_threshold": 0.5,
                    "enable_contradiction_check": True,
                }
            }
        )
        analyzer._llm_client = _FakeReachableClient(is_contradiction=True)

        # Verified (see git history/commit message) to score ~0.956 under
        # this project's TF-IDF fallback -- comfortably above the 0.95
        # duplicate_threshold configured above, on purpose.
        text_high_similarity = (
            "The flight control computer shall log every parameter change event to the "
            "persistent flight data recorder for post-flight analysis."
        )
        text_negated = (
            "The flight control computer shall not log every parameter change event to the "
            "persistent flight data recorder for post-flight analysis."
        )
        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[
                {"id": 1, "recommended_text": text_high_similarity},
                {"id": 2, "recommended_text": text_negated},
            ],
        )
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.similarity_score >= 0.95  # confirms this pair really does clear duplicate_threshold
        assert rel.relationship_type == RelationshipType.CONTRADICTION


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


class TestNegationContradiction:
    """_is_negation_contradiction() -- the mechanical "same requirement,
    one side says 'not'" check. Runs before the LLM check in
    _classify_pair() specifically so it still works when the LLM is
    unreachable, which is exactly the situation this exists for: this
    shape of contradiction (a word inserted/removed) is also the one most
    likely to accidentally clear duplicate_threshold and get mislabeled
    "Duplicate" if nothing catches it first.
    """

    def test_detects_a_single_inserted_not(self):
        assert _is_negation_contradiction(
            "The aircraft shall return to the configured home position.",
            "The aircraft shall not return to the configured home position.",
        )

    def test_detects_never_and_no_and_cannot(self):
        assert _is_negation_contradiction("The valve shall open.", "The valve shall never open.")
        assert _is_negation_contradiction("The system shall log data.", "The system shall log no data.")
        assert _is_negation_contradiction(
            "The pump shall activate on failure.", "The pump shall cannot activate on failure."
        )

    def test_is_case_insensitive_and_whitespace_tolerant(self):
        assert _is_negation_contradiction(
            "The System SHALL Return Home.", "the system shall  not   return home."
        )

    def test_unrelated_texts_are_not_flagged(self):
        assert not _is_negation_contradiction(
            "The system shall log connections.", "The autopilot shall disengage on overforce."
        )

    def test_identical_texts_with_the_same_negation_are_not_flagged(self):
        # Same negation COUNT on both sides -- not a negation-based
        # difference (these are just duplicates, or identical).
        assert not _is_negation_contradiction(
            "The system shall not log connections.", "The system shall not log connections."
        )

    def test_a_different_value_is_not_a_negation_contradiction(self):
        # Both negated once, but they genuinely say different things
        # (50 psi vs 60 psi) -- not what this check is for.
        assert not _is_negation_contradiction(
            "The system shall never exceed 50 psi.", "The system shall never exceed 60 psi."
        )

    def test_a_different_word_is_not_a_negation_contradiction(self):
        # Both negated once, but "below"/"above" differ -- a real
        # contradiction, just not a negation-shaped one; that's the LLM
        # check's job, not this mechanical one's.
        assert not _is_negation_contradiction(
            "The valve shall not open below 10 psi.", "The valve shall not open above 10 psi."
        )

    def test_classified_as_contradiction_even_with_the_llm_unreachable(self):
        # The actual regression this guards against (see the screenshot
        # this was built from): "shall return" vs "shall not return" is
        # similar enough to clear duplicate_threshold, and with the LLM
        # unreachable there'd be nothing left to catch it as anything but
        # "Duplicate" without this mechanical check running first.
        analyzer = ConsistencyAnalyzer(
            settings={
                "consistency": {
                    "duplicate_threshold": 0.95,
                    "similarity_threshold": 0.65,
                    "enable_contradiction_check": True,
                }
            }
        )
        analyzer._llm_client = _FakeUnreachableClient()

        text = (
            "When communication with the ground station is lost for more than 15 seconds, "
            "the aircraft shall return to the configured home position."
        )
        negated = text.replace("shall return", "shall not return")
        result = analyzer.analyze_requirements(
            run_id=1,
            requirements=[{"id": 1, "recommended_text": text}, {"id": 2, "recommended_text": negated}],
        )

        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.similarity_score >= 0.65  # clears similarity_threshold -- the two are near-identical
        assert rel.relationship_type == RelationshipType.CONTRADICTION
        # The mechanical check resolves this pair before _is_llm_reachable()
        # is ever called -- with only this one pair in the run, the LLM
        # was never actually needed, so "skipped" (which specifically
        # means "needed it and it wasn't there") is correctly False, not
        # True. A run with OTHER pairs that DO need the LLM would still
        # report skipped=True for those (see
        # test_contradiction_check_skipped_flag_is_set) -- this pair
        # just never becomes one of them.
        assert result.contradiction_check_skipped is False

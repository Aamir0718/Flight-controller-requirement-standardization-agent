"""Tests for src/rules/incose_ai_scorer.py, using a fake LLM client (no
network) so the 14-rule AI-judged score and its combination with the
28-rule deterministic score can be checked deterministically.
"""

from __future__ import annotations

from rules.incose_ai_scorer import (
    _SET_OR_DOCUMENT_LEVEL_RULE_IDS,
    _non_automatable_rules,
    score_accurate,
    score_non_automatable_rules,
)

CLEAN_TEXT = "The flight control computer shall compute attitude at 50 Hz."

_JUDGED_IDS = [
    r["id"] for r in _non_automatable_rules() if r["id"] not in _SET_OR_DOCUMENT_LEVEL_RULE_IDS
]


class FakeClient:
    """Passes every judged rule except those in fail_ids."""

    def __init__(self, fail_ids: set[str] = frozenset()):
        self.fail_ids = fail_ids
        self.calls: list[dict] = []

    def generate_json(self, system_prompt, user_prompt, schema, required_keys, *, temperature=None, seed=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return {
            "rule_results": [
                {"id": rid, "passed": rid not in self.fail_ids, "reason": "test reason"}
                for rid in _JUDGED_IDS
            ]
        }


def test_non_automatable_rules_covers_exactly_the_14_rulebook_marks():
    assert len(_non_automatable_rules()) == 14


def test_all_judged_rules_pass_when_the_model_passes_everything():
    result = score_non_automatable_rules(CLEAN_TEXT, FakeClient())
    assert result.failed == []
    assert result.score == 100.0
    assert result.total_rules == 14


def test_set_or_document_level_rules_are_never_sent_to_the_model():
    client = FakeClient()
    score_non_automatable_rules(CLEAN_TEXT, client)
    user_prompt = client.calls[0]["user_prompt"]
    for rule_id in _SET_OR_DOCUMENT_LEVEL_RULE_IDS:
        assert rule_id not in user_prompt


def test_set_or_document_level_rules_count_as_passed_not_failed():
    result = score_non_automatable_rules(CLEAN_TEXT, FakeClient())
    for rule_id in _SET_OR_DOCUMENT_LEVEL_RULE_IDS:
        assert rule_id in result.passed
        assert rule_id in result.not_assessable
    assert not any(f.id in _SET_OR_DOCUMENT_LEVEL_RULE_IDS for f in result.failed)


def test_a_failed_rule_is_reported_with_its_reason():
    result = score_non_automatable_rules(CLEAN_TEXT, FakeClient(fail_ids={"R3"}))
    failed_ids = [f.id for f in result.failed]
    assert failed_ids == ["R3"]
    assert result.failed[0].reasons == ["test reason"]
    assert result.score < 100.0


def test_missing_verdict_for_a_rule_fails_closed():
    class DropsARule(FakeClient):
        def generate_json(self, *args, **kwargs):
            response = super().generate_json(*args, **kwargs)
            response["rule_results"] = [r for r in response["rule_results"] if r["id"] != "R12"]
            return response

    result = score_non_automatable_rules(CLEAN_TEXT, DropsARule())
    failed_ids = [f.id for f in result.failed]
    assert "R12" in failed_ids


def test_score_accurate_combines_28_deterministic_and_14_ai_rules():
    combined = score_accurate(CLEAN_TEXT, FakeClient())
    assert combined.deterministic.total_rules == 28
    assert combined.ai.total_rules == 14
    assert combined.combined_total_rules == 42
    expected = round(
        100.0 * (len(combined.deterministic.passed) + len(combined.ai.passed)) / 42, 1
    )
    assert combined.combined_score == expected


def test_score_accurate_is_lower_when_an_ai_judged_rule_fails():
    clean = score_accurate(CLEAN_TEXT, FakeClient())
    with_failure = score_accurate(CLEAN_TEXT, FakeClient(fail_ids={"R3"}))
    assert with_failure.combined_score < clean.combined_score

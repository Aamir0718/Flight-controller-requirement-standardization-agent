"""Tests for src/pipeline/candidate_generator.py, using a fake LLM client
(no network, no real LLM) so the confirm-loop's mechanics -- call count,
when it stops early, when/how it retries, temperature/seed variation --
can be checked deterministically.
"""

from __future__ import annotations

from llm.local_llm_client import LLMResult
from pipeline.candidate_generator import (
    MAX_ATTEMPTS,
    MAX_TEMPERATURE,
    SEEDS,
    generate_candidates,
)

# Confirms on the very first attempt: real "shall" statement, EARS-matched
# (Ubiquitous), scores 100/100 on the deterministic INCOSE checker.
GOOD_TEXT = "The system shall respond to the operator within 200 milliseconds."
# Never confirms: no "shall" at all, so classify_ears_pattern() always
# returns UNCLEAR_LABEL regardless of INCOSE score.
BAD_TEXT = "this is not a real requirement at all"

REQUIREMENT = "While in orbit, the star tracker shall track reference stars continuously."


def _result(text: str) -> LLMResult:
    return LLMResult(
        pattern="State-driven", rewritten_text=text, vague_terms=[], confidence=0.8, notes="", raw={},
    )


class FakeLLMClient:
    """Stands in for LocalLLMClient: records every generate_structured call
    and returns canned results in order, without touching the network."""

    def __init__(self, results: list[LLMResult], temperature: float = 0.2):
        self.temperature = temperature
        self._results = results
        self.calls: list[dict] = []

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": temperature, "seed": seed}
        )
        return self._results[len(self.calls) - 1]


def test_stops_after_one_call_when_the_first_attempt_already_confirms():
    client = FakeLLMClient([_result(GOOD_TEXT)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert len(candidates) == 1
    assert len(client.calls) == 1
    assert candidates[0].result.rewritten_text == GOOD_TEXT


def test_retries_when_the_first_attempt_does_not_confirm():
    client = FakeLLMClient([_result(BAD_TEXT), _result(GOOD_TEXT)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert len(candidates) == 2
    assert len(client.calls) == 2
    assert [c.result.rewritten_text for c in candidates] == [BAD_TEXT, GOOD_TEXT]
    assert [c.index for c in candidates] == [0, 1]


def test_stops_at_max_attempts_when_nothing_ever_confirms():
    client = FakeLLMClient([_result(BAD_TEXT) for _ in range(MAX_ATTEMPTS)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert len(candidates) == MAX_ATTEMPTS
    assert len(client.calls) == MAX_ATTEMPTS


def test_max_attempts_override():
    client = FakeLLMClient([_result(BAD_TEXT) for _ in range(5)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[], max_attempts=5)
    assert len(candidates) == 5


def test_first_attempt_uses_the_full_build_prompt_context():
    client = FakeLLMClient([_result(GOOD_TEXT)])
    generate_candidates(client, REQUIREMENT, flags=[], ears_pattern="Event-driven")
    system_prompt = client.calls[0]["system_prompt"]
    # build_prompt()'s system header + EARS-pattern block land here; the
    # only-relevant-pattern trim means the other 5 templates are absent.
    assert "Event-driven" in system_prompt
    assert "State-driven" not in system_prompt


def test_retry_uses_the_lean_correction_prompt_not_build_prompt_again():
    client = FakeLLMClient([_result(BAD_TEXT), _result(GOOD_TEXT)])
    generate_candidates(client, REQUIREMENT, flags=[], ears_pattern="Event-driven")

    retry_user_prompt = client.calls[1]["user_prompt"]
    assert BAD_TEXT in retry_user_prompt  # cites the previous attempt
    assert "EARS structure" in retry_user_prompt or "still fails" in retry_user_prompt
    # The correction call's TOTAL prompt (system + user) must be smaller
    # than the first call's -- the correction system prompt drops the full
    # EARS pattern set / rule citations build_prompt() sends, even though
    # its user prompt is a bit larger (it has to quote the previous
    # attempt and its specific failures).
    first_call_total = len(client.calls[0]["system_prompt"]) + len(client.calls[0]["user_prompt"])
    retry_total = len(client.calls[1]["system_prompt"]) + len(retry_user_prompt)
    assert retry_total < first_call_total


def test_correction_prompt_cites_the_specific_recheck_failure():
    client = FakeLLMClient([_result(BAD_TEXT), _result(GOOD_TEXT)])
    generate_candidates(client, REQUIREMENT, flags=[])
    retry_user_prompt = client.calls[1]["user_prompt"]
    assert "EARS structure" in retry_user_prompt


def test_temperature_and_seed_vary_across_retry_attempts():
    client = FakeLLMClient([_result(BAD_TEXT), _result(BAD_TEXT), _result(GOOD_TEXT)], temperature=0.2)
    generate_candidates(client, REQUIREMENT, flags=[])

    temperatures = [call["temperature"] for call in client.calls]
    seeds = [call["seed"] for call in client.calls]
    assert len(set(temperatures)) > 1  # not identical across attempts
    assert len(set(seeds)) > 1
    assert seeds == list(SEEDS[:3])
    assert all(t <= MAX_TEMPERATURE for t in temperatures)
    assert temperatures == sorted(temperatures)  # strictly non-decreasing across retries


def test_high_base_temperature_is_clamped_to_max_temperature():
    client = FakeLLMClient([_result(BAD_TEXT) for _ in range(MAX_ATTEMPTS)], temperature=0.95)
    generate_candidates(client, REQUIREMENT, flags=[])
    temperatures = [call["temperature"] for call in client.calls]
    assert all(t <= MAX_TEMPERATURE for t in temperatures)


def test_candidates_preserve_call_order_and_index():
    client = FakeLLMClient([_result(BAD_TEXT), _result(BAD_TEXT), _result(GOOD_TEXT)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert [c.index for c in candidates] == [0, 1, 2]


def test_compliance_threshold_is_respected_by_the_confirm_loop():
    # GOOD_TEXT scores 100 -- passes even an unusually strict threshold --
    # but an unreachable threshold (101) must force every attempt to be
    # treated as failing, exhausting all attempts.
    client = FakeLLMClient([_result(GOOD_TEXT) for _ in range(MAX_ATTEMPTS)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[], compliance_threshold=101.0)
    assert len(candidates) == MAX_ATTEMPTS


def test_num_candidates_is_a_deprecated_alias_for_max_attempts():
    client = FakeLLMClient([_result(BAD_TEXT) for _ in range(5)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[], num_candidates=5)
    assert len(candidates) == 5

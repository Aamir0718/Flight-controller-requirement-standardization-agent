"""Tests for src/pipeline/candidate_generator.py, using a fake LLM client
(no network, no real Ollama) so generation mechanics -- call count,
temperature/seed variation, prompt reuse -- can be checked deterministically.
"""

from __future__ import annotations

from llm.local_llm_client import LLMResult
from pipeline.candidate_generator import (
    MAX_TEMPERATURE,
    NUM_CANDIDATES,
    SEEDS,
    TEMPERATURE_OFFSETS,
    generate_candidates,
)


def _result(text: str) -> LLMResult:
    return LLMResult(
        pattern="State-driven",
        rewritten_text=text,
        vague_terms=[],
        confidence=0.8,
        notes="",
        raw={},
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
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "seed": seed,
            }
        )
        return self._results[len(self.calls) - 1]


REQUIREMENT = "While in orbit, the star tracker shall track reference stars continuously."


def test_generates_num_candidates_calls():
    client = FakeLLMClient([_result(f"variant {i}") for i in range(NUM_CANDIDATES)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert len(candidates) == NUM_CANDIDATES
    assert len(client.calls) == NUM_CANDIDATES


def test_candidates_carry_the_matching_llm_result_in_call_order():
    results = [_result("first"), _result("second"), _result("third")]
    client = FakeLLMClient(results)
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    assert [c.result.rewritten_text for c in candidates] == ["first", "second", "third"]
    assert [c.index for c in candidates] == [0, 1, 2]


def test_temperature_and_seed_vary_across_calls_not_identical():
    client = FakeLLMClient([_result(f"v{i}") for i in range(3)], temperature=0.2)
    generate_candidates(client, REQUIREMENT, flags=[])

    temperatures = [call["temperature"] for call in client.calls]
    seeds = [call["seed"] for call in client.calls]

    # The whole point of varying these is that the 3 calls are NOT identical.
    assert len(set(temperatures)) > 1
    assert len(set(seeds)) > 1
    # Check that temperatures match the expected offsets
    expected_temps = [min(0.2 + offset, MAX_TEMPERATURE) for offset in TEMPERATURE_OFFSETS]
    assert temperatures == expected_temps
    # Check that seeds match the expected values
    assert seeds == list(SEEDS)


def test_temperature_offsets_are_clamped_to_max_temperature():
    client = FakeLLMClient([_result(f"v{i}") for i in range(3)], temperature=0.95)
    generate_candidates(client, REQUIREMENT, flags=[])
    temperatures = [call["temperature"] for call in client.calls]
    assert all(t <= MAX_TEMPERATURE for t in temperatures)
    assert max(temperatures) == MAX_TEMPERATURE


def test_all_calls_reuse_the_same_prompt():
    client = FakeLLMClient([_result(f"v{i}") for i in range(3)])
    generate_candidates(client, REQUIREMENT, flags=[])
    system_prompts = {call["system_prompt"] for call in client.calls}
    # System prompts should be the same (they all have the same structural guidance)
    assert len(system_prompts) == 1
    # User prompts should differ (they have call-specific structural instructions)
    user_prompts = [call["user_prompt"] for call in client.calls]
    assert len(user_prompts) == 3
    # Each user prompt should have call-specific guidance
    assert any("Candidate 1" in p for p in user_prompts)
    assert any("Candidate 2" in p for p in user_prompts)
    assert any("Candidate 3" in p for p in user_prompts)


def test_num_candidates_override():
    client = FakeLLMClient([_result(f"v{i}") for i in range(5)])
    candidates = generate_candidates(client, REQUIREMENT, flags=[], num_candidates=5)
    assert len(candidates) == 5


def test_candidates_are_not_identical():
    """Test that candidates are structurally different, not identical copies."""
    # Simulate a scenario where the fake client returns slightly different texts
    # to verify the system can handle diverse candidates
    results = [
        _result("When the primary sensor is invalid, the system shall activate the backup sensor."),
        _result("The system shall activate the backup sensor upon detection of primary sensor invalidity."),
        _result("Upon detection that the primary sensor is invalid, the system shall transition to the backup sensor."),
    ]
    client = FakeLLMClient(results)
    candidates = generate_candidates(client, REQUIREMENT, flags=[])
    
    # Verify we get 3 candidates
    assert len(candidates) == 3
    
    # Verify they are not identical
    candidate_texts = [c.result.rewritten_text for c in candidates]
    assert len(set(candidate_texts)) == 3, "All candidates should be different"
    
    # Verify indices are preserved
    assert [c.index for c in candidates] == [0, 1, 2]

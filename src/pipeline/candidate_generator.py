"""Generates 3 distinct candidate rewrites for one requirement.

Calls the local LLM 3 times through the same prompt (src/llm/prompts.py)
but with a different temperature and seed each time, so the candidates are
genuinely different samples of the model's distribution rather than
near-duplicate reruns of the same greedy-ish completion. Recommending
between candidates that are all the same defeats the point of generating
3 in the first place.

Scoring/picking a winner is NOT this module's job -- see
src/pipeline/recommender.py, which runs the deterministic INCOSE scorer
against each candidate. Nothing here calls the scorer or the LLM more than
once per candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from llm.local_llm_client import LLMResult, LocalLLMClient
from llm.prompts import build_prompt

NUM_CANDIDATES = 3

# Added to the client's configured base temperature for each candidate
# slot (clamped to MAX_TEMPERATURE) and a distinct seed per slot, so
# candidate generation is reproducible run-to-run against the same model
# while still sampling 3 meaningfully different completions.
# Use higher temperature offsets to encourage more structural diversity.
TEMPERATURE_OFFSETS: tuple[float, ...] = (0.0, 0.4, 0.8)
SEEDS: tuple[int, ...] = (0, 42, 999)
MAX_TEMPERATURE = 1.0


@dataclass(frozen=True)
class Candidate:
    index: int
    result: LLMResult
    temperature: float
    seed: int


def generate_candidates(
    client: LocalLLMClient,
    requirement_text: str,
    flags: Iterable,
    ears_pattern: str | None = None,
    num_candidates: int = NUM_CANDIDATES,
) -> list[Candidate]:
    """Builds one prompt for ``requirement_text`` (via build_prompt) and
    calls ``client`` ``num_candidates`` times against it, varying
    temperature/seed each call. Returns one Candidate per call, in order.

    Raises whatever LocalLLMClient.generate_structured raises
    (OllamaUnavailableError, LLMResponseError) on the first call that
    fails -- a partial candidate set is not a useful result, so this does
    not swallow errors from individual calls.
    """
    base_temperature = client.temperature

    candidates: list[Candidate] = []
    for i in range(num_candidates):
        # Build a fresh prompt for each candidate with call-specific instructions
        bundle = build_prompt(requirement_text, flags, ears_pattern=ears_pattern, candidate_index=i)
        
        temperature = min(
            base_temperature + TEMPERATURE_OFFSETS[i % len(TEMPERATURE_OFFSETS)],
            MAX_TEMPERATURE,
        )
        seed = SEEDS[i % len(SEEDS)]
        result = client.generate_structured(
            bundle.system_prompt,
            bundle.user_prompt,
            temperature=temperature,
            seed=seed,
        )
        candidates.append(Candidate(index=i, result=result, temperature=temperature, seed=seed))

    return candidates

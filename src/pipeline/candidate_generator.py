"""Generates 3 distinct candidate rewrites for one requirement.

Calls the local LLM 3 times through the same prompt (src/llm/prompts.py)
but with a different temperature and seed each time, so the candidates are
genuinely different samples of the model's distribution rather than
near-duplicate reruns of the same greedy-ish completion. Recommending
between candidates that are all the same defeats the point of generating
3 in the first place.

The 3 calls are independent (own prompt variant, own temperature/seed) and
each is a blocking HTTP call to the configured LLM endpoint, so they run
concurrently via a thread pool rather than one at a time -- a real
wall-clock speedup whenever the server can service more than one request
at a time (LocalLLMClient wraps an httpx.Client, which is safe for
concurrent use from multiple threads). If the server only processes one
request at a time, this costs nothing extra either way.

Scoring/picking a winner is NOT this module's job -- see
src/pipeline/recommender.py, which runs the deterministic INCOSE scorer
against each candidate. Nothing here calls the scorer or the LLM more than
once per candidate.
"""

from __future__ import annotations

import concurrent.futures
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
TEMPERATURE_OFFSETS: tuple[float, ...] = (0.0, 0.5, 0.9)
SEEDS: tuple[int, ...] = (42, 1234, 789)
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
    (LLMUnavailableError, LLMResponseError) -- a partial candidate set
    is not a useful result, so this does not swallow errors from
    individual calls. All ``num_candidates`` calls are already in flight
    concurrently by the time any one of them can fail, so (unlike the old
    strictly-sequential version) a failure on an early index no longer
    guarantees later ones never started -- it still surfaces the first
    exception (in index order) to the caller either way.
    """
    base_temperature = client.temperature

    def _generate_one(i: int) -> Candidate:
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
        return Candidate(index=i, result=result, temperature=temperature, seed=seed)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_candidates) as executor:
        # Submitted in index order, all start immediately (max_workers ==
        # num_candidates, so none queue behind another); .result() is
        # called in that same index order so the returned list is ordered
        # exactly like the old sequential version regardless of which
        # call actually finishes first.
        futures = [executor.submit(_generate_one, i) for i in range(num_candidates)]
        candidates = [f.result() for f in futures]

    return candidates

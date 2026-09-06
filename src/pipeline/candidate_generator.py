"""Generates a confirmed-compliant rewrite for one requirement, making as
few LLM calls as it can get away with.

generate_candidates() used to always make 3 independent, parallel LLM
calls per requirement regardless of whether the first one was already
good -- 3x the token/latency cost every single time. It now makes ONE
call, deterministically re-checks that attempt (src/rules/
ears_classifier.classify_ears_pattern() + src/rules/incose_scorer.
score_requirement() -- both pure/instant, no LLM) against the same
EARS-matched + compliance-threshold criteria src/pipeline/graph.py's
Finalize node uses, and stops there if it already passes: 1 LLM call
total, the common case.

Only if that recheck FAILS does it make another call -- and that retry
uses build_correction_prompt() (src/llm/prompts.py), a much smaller
follow-up citing only the previous attempt and exactly what still fails,
not the full pattern-set/rule-citation/few-shot context again. This
repeats up to ``max_attempts`` times; if nothing confirms by then, every
attempt made is still returned (see below) so the pipeline's existing
best-of-N ranking (src/pipeline/recommender.py) and human-review fallback
behave exactly as before, just triggered less often since most
requirements now confirm on attempt 1.

The 3 calls used to run concurrently (independent, so parallelizing was
free). Attempts here are NOT independent -- each retry needs the previous
attempt's text and recheck result -- so they are necessarily sequential.
That's a fine trade: it also means the shared DRDO LLM server never gets
hit with a burst of 3 simultaneous requests per requirement anymore.

Scoring/picking a winner among the returned attempts is still NOT this
module's job -- see src/pipeline/recommender.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from llm.local_llm_client import LLMResult, LocalLLMClient
from llm.prompts import build_correction_prompt, build_prompt, format_recheck_failures
from rules.ears_classifier import UNCLEAR_LABEL, classify_ears_pattern
from rules.incose_scorer import score_requirement

MAX_ATTEMPTS = 3

# A distinct seed per attempt, so a retry samples a genuinely different
# completion rather than risking the exact same (already-rejected) output
# again from a low-temperature model. A small temperature bump on retries
# for the same reason; clamped so it never exceeds MAX_TEMPERATURE.
SEEDS: tuple[int, ...] = (42, 1234, 789)
RETRY_TEMPERATURE_INCREMENT = 0.2
MAX_TEMPERATURE = 1.0

# Backwards-compatible aliases: NUM_CANDIDATES used to mean "always
# generate this many"; it's now the retry cap (see MAX_ATTEMPTS).
NUM_CANDIDATES = MAX_ATTEMPTS


@dataclass(frozen=True)
class Candidate:
    index: int
    result: LLMResult
    temperature: float
    seed: int


def _passes_recheck(rewritten_text: str, compliance_threshold: float) -> tuple[bool, list[str]]:
    """Runs the same deterministic EARS+INCOSE recheck src/pipeline/
    graph.py's generate_requirement() already runs on the final result --
    called here after EVERY attempt instead of only the last one, so a
    bad attempt can be corrected before it's ever shown as "recommended".
    Returns (passed, failure_reasons)."""
    ears_recheck = classify_ears_pattern(rewritten_text)
    score_recheck = score_requirement(rewritten_text)
    passed = ears_recheck.pattern != UNCLEAR_LABEL and score_recheck.score >= compliance_threshold
    return passed, format_recheck_failures(ears_recheck, score_recheck)


def generate_candidates(
    client: LocalLLMClient,
    requirement_text: str,
    flags: Iterable,
    ears_pattern: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    incose_score: float | None = None,
    incose_violations: list[dict] | None = None,
    compliance_threshold: float = 80.0,
    num_candidates: int | None = None,
) -> list[Candidate]:
    """Generates 1 attempt, deterministically rechecks it, and stops as
    soon as one passes -- only retrying (up to ``max_attempts`` total) when
    the previous attempt failed. Returns every attempt made, in order, so
    a rejected earlier attempt is still visible to recommender.py's
    ranking and the review UI's "alternate" candidates, not thrown away.

    ``num_candidates`` is a deprecated alias for ``max_attempts`` (kept so
    an older caller passing it by keyword doesn't break); ``max_attempts``
    wins if both are given.

    ``incose_score``/``incose_violations`` are the original text's
    deterministic INCOSE score/failed-rules (src/rules/incose_scorer.py),
    passed straight through to build_prompt() so the first attempt is
    grounded in the actual measured compliance gap, not just the
    detector-flag heuristic. ``compliance_threshold`` is the same
    threshold src/pipeline/graph.py's Finalize node uses to decide
    needs_human_review -- passed in here too so the confirm-loop stops at
    exactly the bar the requirement actually needs to clear.

    Raises whatever LocalLLMClient.generate_structured raises
    (LLMUnavailableError, LLMResponseError) on any attempt -- a partial
    result is not useful, so errors are never swallowed.
    """
    if num_candidates is not None:
        max_attempts = num_candidates
    base_temperature = client.temperature

    attempts: list[Candidate] = []
    previous_text: str | None = None
    previous_failures: list[str] = []

    for i in range(max_attempts):
        if i == 0:
            bundle = build_prompt(
                requirement_text,
                flags,
                ears_pattern=ears_pattern,
                incose_score=incose_score,
                incose_violations=incose_violations,
            )
        else:
            bundle = build_correction_prompt(
                requirement_text,
                previous_attempt=previous_text,
                failure_reasons=previous_failures,
                ears_pattern=ears_pattern,
            )

        temperature = min(
            base_temperature + (RETRY_TEMPERATURE_INCREMENT * i), MAX_TEMPERATURE
        )
        seed = SEEDS[i % len(SEEDS)]
        result = client.generate_structured(
            bundle.system_prompt, bundle.user_prompt, temperature=temperature, seed=seed
        )
        attempts.append(Candidate(index=i, result=result, temperature=temperature, seed=seed))

        passed, failures = _passes_recheck(result.rewritten_text, compliance_threshold)
        if passed:
            break
        previous_text = result.rewritten_text
        previous_failures = failures

    return attempts

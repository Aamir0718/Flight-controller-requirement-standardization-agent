"""Picks the best of 3 candidate rewrites using the deterministic INCOSE
scorer -- never another LLM call.

recommend() runs each src/pipeline/candidate_generator.Candidate's
rewritten_text through src/rules/incose_scorer.score_requirement() (pure,
regex/word-list/structural, no network) and ranks them by:

    0. no invented number beats having one (see below), then
    1. highest compliance score (score_requirement's 0-100 score), then
    2. fewest LLM-flagged vague terms (Candidate.result.vague_terms), then
    3. shortest rewritten_text (fewest words), then
    4. candidate index (stable tie-break so ranking is fully deterministic)

Safeguard against invented numbers
-----------------------------------
src/llm/prompts.py explicitly instructs the model to never invent a
specific number when it flags a vague term -- only to describe what's
missing and let a human supply the real value. Nothing stops a model from
ignoring that instruction, and a candidate that *did* invent a number will
often score deceptively well (a fabricated "within 200 ms" satisfies
R6/R33/R34 just as well as a real one), which is exactly backwards: a
confidently-wrong number is worse than an honest "needs a value here"
flag. So before ranking, every candidate is checked for numbers that don't
appear anywhere in the original requirement text; a candidate with one is
never preferred over a candidate without one, regardless of score. If
every candidate invented a number, the top-ranked one still carries
has_invented_number = True in its ScoredCandidate -- callers (see
src/pipeline/graph.py's Finalize node) must treat that as a hard trigger
for needs_human_review, not a score to weigh against the threshold.

The result carries all 3 candidates with their individual scores and
pass/fail rule breakdowns, plus a single recommended_index.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from llm.local_llm_client import VagueTermSuggestion
from pipeline.candidate_generator import Candidate
from rules.incose_scorer import FailedRule, ScoreResult, score_requirement

_NUMBER = re.compile(r"[+\-]?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    return {float(m.group(0)) for m in _NUMBER.finditer(text)}


def find_invented_numbers(original_text: str, candidate_text: str) -> list[str]:
    """Numeric literals in ``candidate_text`` whose value doesn't appear
    anywhere in ``original_text`` -- i.e. numbers the LLM introduced rather
    than carried over or derived from what was already stated. Comparison
    is by parsed numeric value (so "50" vs "50.0" is not a mismatch), not
    raw substring, to avoid flagging harmless reformatting.
    """
    original_numbers = _numbers_in(original_text)
    return [
        m.group(0)
        for m in _NUMBER.finditer(candidate_text)
        if float(m.group(0)) not in original_numbers
    ]


@dataclass(frozen=True)
class ScoredCandidate:
    index: int
    rewritten_text: str
    pattern: str
    llm_confidence: float
    notes: str
    vague_terms: list[VagueTermSuggestion]
    temperature: float
    seed: int
    score: float
    total_rules: int
    passed_rule_ids: list[str]
    failed_rules: list[FailedRule]
    invented_numbers: list[str] = field(default_factory=list)

    @property
    def has_invented_number(self) -> bool:
        return bool(self.invented_numbers)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "rewritten_text": self.rewritten_text,
            "pattern": self.pattern,
            "llm_confidence": self.llm_confidence,
            "notes": self.notes,
            "vague_terms": [asdict(v) for v in self.vague_terms],
            "temperature": self.temperature,
            "seed": self.seed,
            "score": self.score,
            "total_rules": self.total_rules,
            "passed_rule_ids": self.passed_rule_ids,
            "failed_rules": [asdict(f) for f in self.failed_rules],
            "invented_numbers": self.invented_numbers,
            "has_invented_number": self.has_invented_number,
        }


@dataclass(frozen=True)
class RecommendationResult:
    candidates: list[ScoredCandidate]
    recommended_index: int

    @property
    def recommended(self) -> ScoredCandidate:
        return self.candidates[self.recommended_index]

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "recommended_index": self.recommended_index,
        }


def _score_candidate(
    candidate: Candidate, original_text: str, rulebook_path: Path | None
) -> ScoredCandidate:
    result: ScoreResult = score_requirement(candidate.result.rewritten_text, rulebook_path)
    return ScoredCandidate(
        index=candidate.index,
        rewritten_text=candidate.result.rewritten_text,
        pattern=candidate.result.pattern,
        llm_confidence=candidate.result.confidence,
        notes=candidate.result.notes,
        vague_terms=candidate.result.vague_terms,
        temperature=candidate.temperature,
        seed=candidate.seed,
        score=result.score,
        total_rules=result.total_rules,
        passed_rule_ids=result.passed,
        failed_rules=result.failed,
        invented_numbers=find_invented_numbers(original_text, candidate.result.rewritten_text),
    )


def _rank_key(candidate: ScoredCandidate) -> tuple:
    return (
        candidate.has_invented_number,               # candidates WITHOUT invented numbers first
        -candidate.score,                             # then highest score
        len(candidate.vague_terms),                    # then fewest flagged vague terms
        len(candidate.rewritten_text.split()),          # then shortest (word count)
        candidate.index,                                # stable, fully deterministic tie-break
    )


def recommend(
    candidates: list[Candidate],
    original_text: str,
    rulebook_path: Path | None = None,
) -> RecommendationResult:
    """Scores every candidate with the deterministic INCOSE scorer and
    ranks them. Does not call the LLM; ``candidates`` must already carry
    each LLMResult (see candidate_generator.generate_candidates).

    ``original_text`` is the requirement being rewritten -- required so
    each candidate can be checked for numbers it introduced that weren't
    anywhere in the original (see find_invented_numbers / module
    docstring). A candidate with an invented number is never ranked ahead
    of one without, regardless of compliance score.
    """
    if not candidates:
        raise ValueError("recommend() requires at least one candidate")

    scored = [_score_candidate(c, original_text, rulebook_path) for c in candidates]
    ranked = sorted(scored, key=_rank_key)
    recommended_index = ranked[0].index

    # Preserve original candidate order in the output (indexed by
    # generation order, not rank) so callers can line candidates[i] up
    # with the LLM call that produced it.
    scored_by_index = sorted(scored, key=lambda c: c.index)
    return RecommendationResult(candidates=scored_by_index, recommended_index=recommended_index)

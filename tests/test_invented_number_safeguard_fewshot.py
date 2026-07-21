"""Sweeps every vague-term example in data/golden/fewshot.json through the
invented-number safeguard (src/pipeline/recommender.py).

For each such row, this simulates an LLM that behaves badly on 2 of 3
candidates (fabricating a plausible-looking but made-up number to "fix"
the vague term) and honestly on the third (leaving the number out and
flagging the vague term with a suggestion instead -- exactly what
src/llm/prompts.py instructs). No real LLM call is made; the point is to
verify recommend() never lets a fabricated number through as the
recommendation, for every one of these rows, not just a hand-picked few.

Per the task: confirm no output contains an invented number, and every
vague-term case produces a non-empty suggestion string.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.local_llm_client import LLMResult, VagueTermSuggestion
from pipeline.candidate_generator import Candidate
from pipeline.recommender import find_invented_numbers, recommend
from rules.detectors import detect_vague_terms

FEWSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "fewshot.json"

# Same defect_type -> detector-category mapping as tests/test_detectors.py's
# CATEGORY_FOR_DEFECT_TYPE["vague_term"] bucket -- every fewshot.json
# defect_type that a vague/unmeasurable-term fix would address.
VAGUE_TERM_DEFECT_TYPES = {
    "Non-Verifiable", "Non-Verifiable / Unbounded", "Subjectivity / Non-Verifiable",
    "Vagueness", "Vagueness / Ambiguity", "Incompleteness / Vagueness",
    "Ambiguity / Vagueness", "Ambiguity", "Ambiguity / Subjectivity",
    "Ambiguity / Escape Clause", "Lack of Precision", "Subjectivity",
    "Non-Standard Syntax/Vocabulary", "Regulatory / Escape Clause", "Incompleteness",
}


def _load_vague_term_examples() -> list[dict]:
    rows = json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))
    return [
        row for row in rows
        if row["python_detectable"] is True and row["defect_type"] in VAGUE_TERM_DEFECT_TYPES
    ]


VAGUE_TERM_EXAMPLES = _load_vague_term_examples()


def _result(text: str, vague_terms: list[VagueTermSuggestion]) -> LLMResult:
    return LLMResult(
        pattern="Ubiquitous", rewritten_text=text, vague_terms=vague_terms,
        confidence=0.8, notes="", raw={},
    )


def _candidate(index: int, text: str, vague_terms: list[VagueTermSuggestion] | None = None) -> Candidate:
    return Candidate(
        index=index, result=_result(text, vague_terms or []), temperature=0.2, seed=index
    )


def _hallucinated_candidate(index: int, original_text: str, fabricated_number: str) -> Candidate:
    """Simulates a model that ignored the "never invent a number"
    instruction and appended one to make the sentence look fixed."""
    text = f"{original_text.rstrip('.')} within {fabricated_number} milliseconds."
    return _candidate(index, text, vague_terms=[])


def _honest_candidate(index: int, original_text: str, defect_reason: str) -> Candidate:
    """Simulates a model that followed the instruction: text unchanged
    (it genuinely cannot fix the vague term without a real number), vague
    term flagged with a plain-language suggestion instead. Uses the real
    vague-term detector to find the actual flagged span where possible, so
    the simulated candidate's "term" reflects genuine detector output
    rather than a stand-in string.
    """
    findings = detect_vague_terms(original_text)
    term = findings[0].span if findings else original_text.split()[-1].rstrip(".")
    return _candidate(
        index,
        original_text,
        vague_terms=[VagueTermSuggestion(term=term, suggestion=defect_reason)],
    )


assert len(VAGUE_TERM_EXAMPLES) >= 50, (
    f"expected a substantial sweep, only found {len(VAGUE_TERM_EXAMPLES)} vague-term "
    "examples -- did fewshot.json or the defect_type mapping change?"
)


@pytest.mark.parametrize(
    "example", VAGUE_TERM_EXAMPLES, ids=[e["id"] for e in VAGUE_TERM_EXAMPLES]
)
def test_recommended_candidate_never_contains_an_invented_number(example):
    original = example["bad_requirement"]
    candidates = [
        _hallucinated_candidate(0, original, "742"),
        _honest_candidate(1, original, example["reason"]),
        _hallucinated_candidate(2, original, "18"),
    ]

    recommendation = recommend(candidates, original)
    recommended = recommendation.recommended

    assert find_invented_numbers(original, recommended.rewritten_text) == []
    assert recommended.has_invented_number is False
    assert recommended.index == 1  # the honest candidate, every time


@pytest.mark.parametrize(
    "example", VAGUE_TERM_EXAMPLES, ids=[e["id"] for e in VAGUE_TERM_EXAMPLES]
)
def test_recommended_candidate_has_a_non_empty_suggestion(example):
    original = example["bad_requirement"]
    candidates = [
        _hallucinated_candidate(0, original, "742"),
        _honest_candidate(1, original, example["reason"]),
        _hallucinated_candidate(2, original, "18"),
    ]

    recommendation = recommend(candidates, original)
    recommended = recommendation.recommended

    assert recommended.vague_terms, f"expected a suggestion for {example['id']}"
    for vague_term in recommended.vague_terms:
        assert vague_term.term.strip()
        assert vague_term.suggestion.strip()


def test_when_every_candidate_hallucinates_the_result_still_flags_it():
    """Not every model call is guaranteed to include one honest candidate
    -- confirm the safeguard degrades safely (flags the problem) rather
    than silently picking whichever fabricated number scores best."""
    for example in VAGUE_TERM_EXAMPLES[:10]:  # representative sample, not the full sweep
        original = example["bad_requirement"]
        candidates = [
            _hallucinated_candidate(0, original, "111"),
            _hallucinated_candidate(1, original, "222"),
            _hallucinated_candidate(2, original, "333"),
        ]
        recommendation = recommend(candidates, original)
        assert recommendation.recommended.has_invented_number is True


def test_sweep_covers_every_python_detectable_vague_term_row_in_fewshot():
    """Guards the sweep's own premise: if the fewshot data or the
    defect_type mapping changes such that this list becomes empty or
    tiny, the two parametrized tests above would silently stop testing
    anything meaningful."""
    assert len(VAGUE_TERM_EXAMPLES) >= 50
    assert len({e["id"] for e in VAGUE_TERM_EXAMPLES}) == len(VAGUE_TERM_EXAMPLES)

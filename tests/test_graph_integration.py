"""End-to-end integration test for src/pipeline/graph.py against a real,
locally-running Ollama instance. Auto-skips (does not fail the build) when
Ollama isn't reachable -- consistent with tests/test_llm_integration.py.

Two scenarios, both required:

1. A handful of data/golden/fewshot.json examples -- the requirements the
   rule engine and the prompt few-shot selection were tuned against.
2. 2-3 hand-written requirements that do NOT appear anywhere in
   data/golden/fewshot.json or data/golden/eval.json (asserted
   programmatically below, not just by eyeballing it) -- to confirm the
   graph generalizes to unseen requirement text rather than only working
   because the LLM (or some part of the pipeline) has effectively
   memorized the golden set's specific wording.

Assertions are structural (shape, types, ranges), not exact-content, since
a live LLM's actual wording is inherently non-deterministic even with
fixed seeds across different model versions/hardware.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.local_llm_client import LocalLLMClient, LLMUnavailableError
from pipeline.graph import build_graph, run_requirement

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "golden"

FEWSHOT_EXAMPLE_IDS = [
    "EMBEDDED-REQ-IOT-076",  # Non-Verifiable ("optimize payload buffering")
    "AVIONICS-REQ-AV-015",   # Subtle Negative Constraint ("avoid locking")
    "AVIONICS-REQ-AV-031",   # Non-Atomic Multiple Behaviors (two hardware actions)
]

# None of these appear in fewshot.json or eval.json -- verified by
# test_hand_written_requirements_are_not_in_the_golden_dataset below.
HAND_WRITTEN_REQUIREMENTS = [
    "The onboard diagnostic module shall periodically transmit health telemetry to ground control.",
    "When the fuel gauge reads below reserve, the cockpit display shall not fail to show a warning.",
    "While charging, the battery management system shall balance cell voltages and monitor "
    "temperature and log anomalies.",
]


def _load_fewshot_examples(ids: list[str]) -> list[dict]:
    rows = json.loads((GOLDEN_DIR / "fewshot.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids]


def test_hand_written_requirements_are_not_in_the_golden_dataset():
    """Guards the premise of the generalization test below: if someone
    later edits HAND_WRITTEN_REQUIREMENTS to something that happens to
    match a golden example, this fails loudly instead of the
    generalization test silently proving nothing."""
    golden_texts = set()
    for filename in ("fewshot.json", "eval.json"):
        rows = json.loads((GOLDEN_DIR / filename).read_text(encoding="utf-8"))
        for row in rows:
            golden_texts.add(row["bad_requirement"])
            golden_texts.add(row["compliant_version"])

    for text in HAND_WRITTEN_REQUIREMENTS:
        assert text not in golden_texts, f"not actually unseen: {text!r}"


@pytest.fixture(scope="module")
def compiled_graph():
    client = LocalLLMClient()
    try:
        client.check_reachable()
    except LLMUnavailableError as exc:
        pytest.skip(f"Ollama not reachable -- skipping graph integration test ({exc})")
    return build_graph(client=client)


def _assert_well_formed_result(result: dict, original_text: str) -> None:
    assert result["original_text"] == original_text
    assert isinstance(result["source_location"], dict)
    assert isinstance(result["rule_flags"], list)
    assert isinstance(result["ears_pattern"], dict)
    assert result["ears_pattern"]["pattern"]

    assert len(result["candidates"]) == 3
    for i, candidate in enumerate(result["candidates"]):
        assert candidate["index"] == i
        assert candidate["rewritten_text"].strip()
        assert 0.0 <= candidate["score"] <= 100.0
        assert len(candidate["passed_rule_ids"]) + len(candidate["failed_rules"]) == candidate["total_rules"]

    assert 0 <= result["recommended_index"] < 3
    assert result["recommended_text"] == result["candidates"][result["recommended_index"]]["rewritten_text"]
    assert isinstance(result["vague_term_suggestions"], list)
    for vt in result["vague_term_suggestions"]:
        assert vt["term"].strip()
        assert vt["suggestion"].strip()
    assert isinstance(result["needs_human_review"], bool)
    # A candidate scoring below threshold must never be silently presented
    # as a confident recommendation.
    if result["recommended_score"] < result["compliance_threshold"]:
        assert result["needs_human_review"] is True


@pytest.mark.integration
class TestFewshotExamplesEndToEnd:
    @pytest.mark.parametrize("example", _load_fewshot_examples(FEWSHOT_EXAMPLE_IDS), ids=FEWSHOT_EXAMPLE_IDS)
    def test_runs_end_to_end_on_known_golden_examples(self, compiled_graph, example):
        result = run_requirement(compiled_graph, example["bad_requirement"])
        _assert_well_formed_result(result, example["bad_requirement"])
        # These rows are known-defective; the rule engine should agree.
        assert result["rule_flags"], f"expected at least one flag for {example['id']}"


@pytest.mark.integration
class TestHandWrittenRequirementsNotInGoldenSet:
    """The generalization check: these strings were never seen while
    building the detectors, the INCOSE scorer, the few-shot prompt
    examples, or (as far as we can tell) the model's training data
    specifically for this project. A pipeline that only "works" on
    data/golden/fewshot.json wording would be a much weaker result than
    one that holds up here too."""

    @pytest.mark.parametrize("requirement_text", HAND_WRITTEN_REQUIREMENTS)
    def test_runs_end_to_end_on_unseen_requirement(self, compiled_graph, requirement_text):
        result = run_requirement(compiled_graph, requirement_text)
        _assert_well_formed_result(result, requirement_text)

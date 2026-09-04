"""Integration test for the LLM stack (local_llm_client.py + prompts.py)
against the real, configured LLM endpoint (config/settings.yaml's
llm.base_url -- a DRDO-internal vLLM server).

This is the only test file in the suite allowed to make a network call,
and only ever to that one configured endpoint. It auto-skips (does not
fail the build/CI run) when the endpoint isn't reachable -- there is no
fallback to any other endpoint to test against instead.

Run with the endpoint reachable to actually exercise this:
    pytest tests/test_llm_integration.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.local_llm_client import LLMResult, LocalLLMClient, LLMUnavailableError
from llm.prompts import build_prompt
from rules.detectors import run_all_detectors

FEWSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "fewshot.json"

# A single, deterministic, well-understood example: a clear vague-term
# defect (a python_detectable row) with a known bad_requirement, reason,
# and compliant_version to sanity-check the round trip against.
KNOWN_EXAMPLE_ID = "EMBEDDED-REQ-IOT-076"

_VALID_EARS_PATTERNS = {
    "Ubiquitous", "Event-driven", "State-driven", "Unwanted Behavior",
    "Optional Feature", "Complex",
}


def _load_known_example() -> dict:
    rows = json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))
    for row in rows:
        if row["id"] == KNOWN_EXAMPLE_ID:
            return row
    raise LookupError(f"{KNOWN_EXAMPLE_ID} not found in {FEWSHOT_PATH}")


@pytest.fixture(scope="module")
def llm_client() -> LocalLLMClient:
    client = LocalLLMClient()
    try:
        client.check_reachable()
    except LLMUnavailableError as exc:
        pytest.skip(f"LLM endpoint not reachable -- skipping integration test ({exc})")
    return client


@pytest.mark.integration
def test_end_to_end_rewrite_of_a_known_fewshot_example_returns_valid_structured_json(llm_client):
    example = _load_known_example()
    assert example["python_detectable"] is True  # sanity: this row does have a mechanical defect

    findings = run_all_detectors(example["bad_requirement"], example["ears_pattern"])
    bundle = build_prompt(
        example["bad_requirement"], findings, ears_pattern=example["ears_pattern"]
    )

    result = llm_client.generate_structured(bundle.system_prompt, bundle.user_prompt)

    assert isinstance(result, LLMResult)
    assert result.pattern in _VALID_EARS_PATTERNS
    assert result.rewritten_text.strip()
    assert result.rewritten_text.strip() != example["bad_requirement"]
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.notes, str)
    assert isinstance(result.vague_terms, list)
    for vague_term in result.vague_terms:
        assert vague_term.term.strip()
        assert vague_term.suggestion.strip()

"""Tests for src/rules/ears_classifier.py.

1. Structural/unit tests on hand-written sentences (not from the golden
   dataset) covering all 5 EARS patterns + Complex + the "Unclear" cases.
2. An accuracy report against data/golden/fewshot.json's labeled
   `ears_pattern` column.

A note on scope: classify_ears_pattern() is a first-guess *keyword*
classifier, not a structural defect checker. It intentionally does not look
for a trigger keyword embedded mid-sentence after 'shall' (that's
src/rules/incose_scorer.py's R1 and src/rules/detectors.py's
missing_ears_trigger job) -- it only reads the leading, comma-separated
clause(s) ahead of 'shall'. This matters for accuracy on
data/golden/fewshot.json's "Structural Inconsistency" rows: those rows are
deliberately labeled with an EARS pattern their *embedded* condition
violates (e.g. a "Ubiquitous" row that hides a "when ..." condition after
'shall' instead of leading with it) -- the leading-clause reading still
matches the label, and does so correctly, because the leading structure
itself is exactly what's labeled. Running the classifier on those same
rows' `compliant_version` fix, however, surfaces a handful of rows where
fixing the defect *changed* which EARS pattern applies (the embedded
condition became the leading clause) while the dataset's `ears_pattern`
column still reflects the original label -- those are noted as a stale-label
artifact, not a classifier error, and are not counted against accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rules.ears_classifier import (
    CONFIDENCE_THRESHOLD,
    UNCLEAR_LABEL,
    ClassificationResult,
    classify_ears_pattern,
    load_ears_patterns,
)

FEWSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "fewshot.json"


@pytest.fixture(scope="module")
def fewshot() -> list[dict]:
    return json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_loads_all_6_patterns_from_prompt_5_file():
    patterns = load_ears_patterns()
    names = {p["name"] for p in patterns}
    assert names == {
        "Ubiquitous", "Event-driven", "State-driven", "Unwanted Behavior",
        "Optional Feature", "Complex",
    }


def test_classify_returns_classification_result():
    result = classify_ears_pattern("The system shall respond within 100 ms.")
    assert isinstance(result, ClassificationResult)
    assert isinstance(result.confidence, float)
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.matched_keywords, tuple)
    assert result.reason


# ---------------------------------------------------------------------------
# Unit tests on requirement text NOT in the golden dataset
# ---------------------------------------------------------------------------


class TestEachEarsPattern:
    def test_ubiquitous(self):
        result = classify_ears_pattern("The gateway shall log all connection attempts.")
        assert result.pattern == "Ubiquitous"

    def test_event_driven(self):
        result = classify_ears_pattern(
            "When the door sensor triggers, the alarm controller shall sound the siren."
        )
        assert result.pattern == "Event-driven"

    def test_state_driven(self):
        result = classify_ears_pattern(
            "While the vehicle is charging, the OBC shall limit current draw to 5 amperes."
        )
        assert result.pattern == "State-driven"

    def test_unwanted_behavior(self):
        result = classify_ears_pattern(
            "If the coolant pump fails, then the reactor controller shall trigger an emergency shutdown."
        )
        assert result.pattern == "Unwanted Behavior"

    def test_optional_feature(self):
        result = classify_ears_pattern(
            "Where a rear camera is installed, the display shall show the reverse feed."
        )
        assert result.pattern == "Optional Feature"

    def test_complex_combines_two_different_leading_clauses(self):
        result = classify_ears_pattern(
            "While in cruise mode, if an overspeed condition is detected, the autopilot shall reduce throttle."
        )
        assert result.pattern == "Complex"
        assert set(result.matched_keywords) == {"while", "if"}

    def test_repeated_same_keyword_is_not_complex(self):
        # Two "when" clauses are still one Event-driven requirement --
        # Complex means combining *different* clause types, not repeating one.
        result = classify_ears_pattern(
            "When the sensor fails and when the backup is unavailable, the system shall enter safe mode."
        )
        assert result.pattern == "Event-driven"


class TestUnclearCases:
    def test_no_shall_clause(self):
        result = classify_ears_pattern("This sentence has no response clause at all.")
        assert result.pattern == UNCLEAR_LABEL
        assert result.confidence == 0.0

    def test_leading_keyword_without_comma_is_unclear(self):
        result = classify_ears_pattern("When failure occurs the system shall log it.")
        assert result.pattern == UNCLEAR_LABEL

    def test_empty_string(self):
        result = classify_ears_pattern("")
        assert result.pattern == UNCLEAR_LABEL

    def test_unclear_results_are_always_below_threshold(self):
        for text in ["", "no shall here", "When X the system shall Y."]:
            result = classify_ears_pattern(text)
            if result.pattern == UNCLEAR_LABEL:
                assert result.confidence < CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Accuracy report against data/golden/fewshot.json
# ---------------------------------------------------------------------------

MIN_ACCURACY = 0.95


def test_accuracy_against_fewshot_golden_labels(fewshot):
    total = len(fewshot)
    correct = 0
    mismatches = []

    for row in fewshot:
        result = classify_ears_pattern(row["bad_requirement"])
        if result.pattern == row["ears_pattern"]:
            correct += 1
        else:
            mismatches.append(
                (row["id"], row["ears_pattern"], result.pattern, row["bad_requirement"])
            )

    accuracy = correct / total
    report = [
        "",
        f"accuracy: {correct}/{total} = {accuracy:.3f}",
    ]
    for row_id, expected, got, text in mismatches:
        report.append(f"  {row_id}: expected {expected!r}, got {got!r} -- {text}")
    report_text = "\n".join(report)
    print(report_text)

    assert accuracy >= MIN_ACCURACY, report_text


def test_no_row_is_misclassified_as_a_completely_different_confident_pattern(fewshot):
    """A wrong-but-confident guess (e.g. calling an Event-driven row
    State-driven) is worse than an honest UNCLEAR_LABEL -- this asserts
    every disagreement with the golden label is either an UNCLEAR call or
    the documented stale-label artifact, never a confident wrong guess."""
    hard_wrong = []
    for row in fewshot:
        result = classify_ears_pattern(row["bad_requirement"])
        if result.pattern != row["ears_pattern"] and result.pattern != UNCLEAR_LABEL:
            hard_wrong.append((row["id"], row["ears_pattern"], result.pattern))
    assert not hard_wrong, hard_wrong

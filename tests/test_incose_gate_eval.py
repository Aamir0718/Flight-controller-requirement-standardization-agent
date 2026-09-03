"""Regression test for scripts/evaluate_incose_gate.py: keeps the
precision=1.0/recall=1.0 claim in docs/safety_and_traceability.md and
docs/incose_coverage.md honest. If someone edits src/rules/incose_scorer.py
or data/golden/incose_gate_negatives.json in a way that degrades the
INCOSE gate's accuracy at the configured threshold, this fails instead of
the drift going unnoticed until someone happens to re-run the script by
hand.

Deliberately not testing exact scores/misclassified content (that's what
running the script directly and reading data/incose_gate_eval_results.json
is for) -- just the headline numbers this system's documentation cites.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from evaluate_incose_gate import DEFAULT_THRESHOLD, run_evaluation  # noqa: E402


def test_incose_gate_has_perfect_precision_and_recall_on_golden_data():
    report = run_evaluation(DEFAULT_THRESHOLD)

    assert report["confusion_matrix"]["false_positive"] == 0, (
        "IncoseCheck wrongly rejected a known-good requirement from "
        "data/golden/eval.json or fewshot.json -- see report['misclassified']"
    )
    assert report["confusion_matrix"]["false_negative"] == 0, (
        "IncoseCheck failed to reject a known-bad requirement from "
        "data/golden/incose_gate_negatives.json -- see report['misclassified']"
    )
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0


def test_negative_examples_are_ears_structurally_valid():
    """The negative set is only a meaningful test of IncoseCheck specifically
    if the text would otherwise clear the EARS gate -- otherwise a rejection
    could be attributed to either gate and this wouldn't isolate anything."""
    import json

    from rules.ears_classifier import UNCLEAR_LABEL, classify_ears_pattern

    rows = json.loads(
        (REPO_ROOT / "data" / "golden" / "incose_gate_negatives.json").read_text(encoding="utf-8")
    )
    for row in rows:
        classification = classify_ears_pattern(row["text"])
        assert classification.pattern != UNCLEAR_LABEL, (
            f"{row['id']} is not EARS-structurally valid ({classification.reason!r}) -- "
            "it no longer isolates the INCOSE gate from the EARS gate"
        )

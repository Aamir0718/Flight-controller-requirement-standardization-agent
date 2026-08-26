"""Precision/recall evaluation for src/pipeline/graph.py's pre-LLM EARS
compliance gate (the ComplianceCheck node) -- pure Python, no LLM, no
network, no Ollama dependency, finishes in a fraction of a second even
for hundreds of examples (the gate itself is a regex/keyword classifier).

Ground truth, "positive" = "should be rejected" (not EARS compliant):
- "Should pass" examples: every bad_requirement in data/golden/eval.json
  (60) and fewshot.json (150) -- 210 real, hand-written EARS-structured
  requirements, written for a different purpose (testing LLM rewrite
  quality) and never tuned against this gate.
- "Should reject" examples: data/golden/compliance_gate_negatives.json --
  25 hand-crafted cases covering empty/malformed input, wrong modal verb
  (will/must/should/may instead of "shall"), non-English text, missing
  "shall" entirely, a malformed trigger clause (no comma), and garbage
  text.

Reports a confusion matrix (TP/FP/TN/FN), precision, recall, F1, and
accuracy, plus every misclassified example so a wrong prediction can be
inspected directly rather than just counted.

Usage:
    python scripts/evaluate_compliance_gate.py [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from rules.ears_classifier import UNCLEAR_LABEL, classify_ears_pattern  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "data" / "golden"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "compliance_gate_eval_results.json"


def _load_positive_examples() -> list[dict]:
    """Every bad_requirement in eval.json + fewshot.json: real, hand-written
    EARS-structured requirements that should clear the compliance gate."""
    examples = []
    for filename in ("eval.json", "fewshot.json"):
        rows = json.loads((GOLDEN_DIR / filename).read_text(encoding="utf-8"))
        for row in rows:
            examples.append(
                {
                    "id": row["id"],
                    "text": row["bad_requirement"],
                    "expected_reject": False,
                    "source": filename,
                }
            )
    return examples


def _load_negative_examples() -> list[dict]:
    rows = json.loads((GOLDEN_DIR / "compliance_gate_negatives.json").read_text(encoding="utf-8"))
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "expected_reject": True,
            "source": "compliance_gate_negatives.json",
            "category": row.get("category"),
        }
        for row in rows
    ]


def evaluate_example(example: dict) -> dict:
    classification = classify_ears_pattern(example["text"])
    predicted_reject = classification.pattern == UNCLEAR_LABEL
    expected_reject = example["expected_reject"]

    if predicted_reject and expected_reject:
        outcome = "TP"
    elif predicted_reject and not expected_reject:
        outcome = "FP"
    elif not predicted_reject and expected_reject:
        outcome = "FN"
    else:
        outcome = "TN"

    return {
        **example,
        "predicted_reject": predicted_reject,
        "predicted_pattern": classification.pattern,
        "predicted_reason": classification.reason,
        "outcome": outcome,
    }


def build_report(records: list[dict]) -> dict:
    tp = sum(1 for r in records if r["outcome"] == "TP")
    fp = sum(1 for r in records if r["outcome"] == "FP")
    fn = sum(1 for r in records if r["outcome"] == "FN")
    tn = sum(1 for r in records if r["outcome"] == "TN")
    total = len(records)

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    accuracy = (tp + tn) / total if total else None

    misclassified = [r for r in records if r["outcome"] in ("FP", "FN")]

    return {
        "total_examples": total,
        "positive_examples_should_reject": sum(1 for r in records if r["expected_reject"]),
        "negative_examples_should_pass": sum(1 for r in records if not r["expected_reject"]),
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
        },
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1_score": round(f1, 4) if f1 is not None else None,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "misclassified_count": len(misclassified),
        "misclassified": misclassified,
    }


def run_evaluation() -> dict:
    examples = _load_positive_examples() + _load_negative_examples()
    records = [evaluate_example(e) for e in examples]
    return build_report(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    start = time.monotonic()
    report = run_evaluation()
    elapsed = time.monotonic() - start
    report["elapsed_seconds"] = round(elapsed, 4)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    cm = report["confusion_matrix"]
    print(
        f"Evaluated {report['total_examples']} examples "
        f"({report['positive_examples_should_reject']} should-reject, "
        f"{report['negative_examples_should_pass']} should-pass) "
        f"in {report['elapsed_seconds']}s -- pure Python, no LLM, no Ollama needed"
    )
    print(f"Wrote {args.output}\n")
    print("Confusion matrix:")
    print(f"  True Positive  (correctly rejected):  {cm['true_positive']}")
    print(f"  False Positive (wrongly rejected):    {cm['false_positive']}")
    print(f"  False Negative (wrongly passed):      {cm['false_negative']}")
    print(f"  True Negative  (correctly passed):    {cm['true_negative']}")
    print()
    print(f"Precision: {report['precision']}")
    print(f"Recall:    {report['recall']}")
    print(f"F1 score:  {report['f1_score']}")
    print(f"Accuracy:  {report['accuracy']}")
    if report["misclassified"]:
        print(f"\n{report['misclassified_count']} misclassified example(s):")
        for r in report["misclassified"]:
            print(f"  [{r['outcome']}] {r['id']}: {r['text'][:70]!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

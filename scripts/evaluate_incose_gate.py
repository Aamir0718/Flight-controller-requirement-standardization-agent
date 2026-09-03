"""Precision/recall evaluation for src/pipeline/graph.py's pre-LLM INCOSE
compliance gate (the IncoseCheck node) -- pure Python, no LLM, no network,
no Ollama dependency, finishes in a fraction of a second even for hundreds
of examples (the gate is a rule-by-rule regex/word-list/structural scorer,
same as everything else in src/rules/incose_scorer.py).

Mirrors scripts/evaluate_compliance_gate.py's method exactly, but for the
INCOSE gate instead of the EARS gate -- same ground-truth-split idea, same
confusion-matrix/precision/recall/F1/accuracy report shape, same
misclassified-examples listing, so the two gates' evaluation reports are
directly comparable side by side.

Ground truth, "positive" = "should be rejected" (INCOSE score below
pipeline.incose_gate_threshold):
- "Should pass" examples: every bad_requirement in data/golden/eval.json
  (60) and fewshot.json (150) -- 210 real, hand-written EARS-structured
  requirements, written for a different purpose (testing LLM rewrite
  quality) and never tuned against this gate. These are known to have
  *some* defect (that's the point of the golden set), but not the kind of
  multi-rule pile-up this gate is meant to catch -- they should still
  clear an 80/100 gate over ~25 rules.
- "Should reject" examples: data/golden/incose_gate_negatives.json -- 22
  hand-crafted requirements that are deliberately EARS-structurally VALID
  (confirmed via src/rules/ears_classifier.py -- see the comment at the
  top of that file) but stack 4-11 simultaneous INCOSE defects (vague
  terms, passive voice, missing tolerance, multiple "shall"s in one
  sentence, absolutes, unbounded "optimize" language, etc.) so the gate's
  score drops below threshold. Being EARS-valid is deliberate: it isolates
  what THIS gate catches from what ComplianceCheck (EARS) would catch
  anyway, so a reviewer can see the INCOSE gate is doing real,
  independent work rather than just re-flagging structurally broken text.

Reports a confusion matrix (TP/FP/TN/FN), precision, recall, F1, and
accuracy, plus every misclassified example so a wrong prediction can be
inspected directly rather than just counted. Also reports the full score
distribution (min/p10/median/p90/max) across every example, since a
single pass/fail count at one threshold doesn't show how sensitive the
gate is to that threshold choice -- see README/report discussion of why
80.0 was picked.

Usage:
    python scripts/evaluate_incose_gate.py [--output PATH] [--threshold N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from config import get_settings  # noqa: E402
from rules.incose_scorer import PRE_LLM_GATE_EXCLUDED_RULE_IDS, score_requirement  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "data" / "golden"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "incose_gate_eval_results.json"
DEFAULT_THRESHOLD = get_settings().get("pipeline", {}).get("incose_gate_threshold", 80.0)


def _load_negative_examples() -> list[dict]:
    """Every bad_requirement in eval.json + fewshot.json: real, hand-written
    EARS-structured requirements that should clear the INCOSE gate (they
    have other defects the LLM rewrite step is meant to fix, but not the
    kind of multi-rule pile-up this gate targets)."""
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


def _load_positive_examples() -> list[dict]:
    rows = json.loads((GOLDEN_DIR / "incose_gate_negatives.json").read_text(encoding="utf-8"))
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "expected_reject": True,
            "source": "incose_gate_negatives.json",
            "category": row.get("category"),
        }
        for row in rows
    ]


def evaluate_example(example: dict, threshold: float) -> dict:
    result = score_requirement(example["text"], exclude_rule_ids=PRE_LLM_GATE_EXCLUDED_RULE_IDS)
    predicted_reject = result.score < threshold
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
        "incose_score": result.score,
        "failed_rule_ids": [f.id for f in result.failed],
        "outcome": outcome,
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def build_report(records: list[dict], threshold: float) -> dict:
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

    scores = sorted(r["incose_score"] for r in records)
    score_distribution = {
        "min": scores[0] if scores else None,
        "p10": _percentile(scores, 10),
        "median": _percentile(scores, 50),
        "p90": _percentile(scores, 90),
        "max": scores[-1] if scores else None,
    }

    return {
        "threshold": threshold,
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
        "score_distribution": score_distribution,
        "misclassified_count": len(misclassified),
        "misclassified": misclassified,
    }


def run_evaluation(threshold: float) -> dict:
    examples = _load_negative_examples() + _load_positive_examples()
    records = [evaluate_example(e, threshold) for e in examples]
    return build_report(records, threshold)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"INCOSE gate score threshold below which a requirement is rejected "
        f"(default: pipeline.incose_gate_threshold from config/settings.yaml, currently {DEFAULT_THRESHOLD})",
    )
    args = parser.parse_args(argv)

    start = time.monotonic()
    report = run_evaluation(args.threshold)
    elapsed = time.monotonic() - start
    report["elapsed_seconds"] = round(elapsed, 4)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    cm = report["confusion_matrix"]
    dist = report["score_distribution"]
    print(
        f"Evaluated {report['total_examples']} examples "
        f"({report['positive_examples_should_reject']} should-reject, "
        f"{report['negative_examples_should_pass']} should-pass) "
        f"at threshold {report['threshold']} "
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
    print()
    print(
        f"Score distribution: min={dist['min']}  p10={dist['p10']}  "
        f"median={dist['median']}  p90={dist['p90']}  max={dist['max']}"
    )
    if report["misclassified"]:
        print(f"\n{report['misclassified_count']} misclassified example(s):")
        for r in report["misclassified"]:
            print(f"  [{r['outcome']}] {r['id']} (score {r['incose_score']}): {r['text'][:70]!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

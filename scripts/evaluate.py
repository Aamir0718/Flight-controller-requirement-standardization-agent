"""Runs the full pipeline (src/pipeline/graph.py) against every example in
data/golden/eval.json -- the 60 examples held out from fewshot.json and
never used to tune the detectors, the INCOSE rulebook, or the few-shot
prompt selection -- and reports:

- % correct EARS pattern classification (src/rules/ears_classifier.py's
  deterministic first guess vs. eval.json's labeled ears_pattern column)
- % of vague-term-flagged rows whose recommended candidate produces a
  non-empty suggestion, and separately % with needs_human_review set, and
  % with an invented number (src/pipeline/recommender.py's safeguard --
  this one should be 0%)
- the average INCOSE compliance score of the recommended candidate vs.
  the average of the two alternates, and how often the recommended
  candidate does NOT have the single highest score of the 3 -- not
  necessarily a bug (the invented-number safeguard and the vague-term/
  length tie-breaks can rank a lower-scoring candidate first on purpose),
  but a signal worth looking at if the rate is high
- every failure case: any example where something above didn't hold

Requires a reachable local Ollama instance (config/settings.yaml) --
fails fast with a clear message and writes no output file if it isn't,
rather than saving a partial/misleading report. Never calls any
external/hosted API (see src/llm/local_llm_client.py).

Usage:
    python scripts/evaluate.py [--limit N] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from llm.local_llm_client import LocalLLMClient, OllamaUnavailableError  # noqa: E402
from pipeline.graph import build_graph, run_requirement  # noqa: E402
from rules.detectors import run_all_detectors  # noqa: E402
from rules.ears_classifier import classify_ears_pattern  # noqa: E402

EVAL_PATH = REPO_ROOT / "data" / "golden" / "eval.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "eval_results.json"


def load_eval_examples(limit: int | None = None) -> list[dict]:
    examples = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    return examples[:limit] if limit else examples


def evaluate_example(compiled_graph, example: dict) -> dict:
    """Runs one eval.json row through the pipeline and returns a flat
    per-example record. Never raises: a pipeline exception is recorded as
    a failure on the record, not propagated, so one bad example can't
    abort the whole batch.
    """
    text = example["bad_requirement"]
    record: dict = {
        "id": example["id"],
        "bad_requirement": text,
        "golden_ears_pattern": example["ears_pattern"],
        "defect_type": example["defect_type"],
        "issues": [],
    }

    # Deterministic checks first -- these don't need the LLM and stay
    # available even if the full pipeline call below fails.
    classification = classify_ears_pattern(text)
    record["classified_ears_pattern"] = classification.pattern
    record["ears_pattern_correct"] = classification.pattern == example["ears_pattern"]
    if not record["ears_pattern_correct"]:
        record["issues"].append(
            f"EARS pattern misclassified: expected {example['ears_pattern']!r}, "
            f"got {classification.pattern!r}"
        )

    findings = run_all_detectors(text)
    record["is_vague_term_example"] = any(f.violation_type == "vague_term" for f in findings)

    try:
        result = run_requirement(compiled_graph, text)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: record, don't crash the batch
        record["pipeline_error"] = f"{type(exc).__name__}: {exc}"
        record["issues"].append(f"Pipeline raised {type(exc).__name__}: {exc}")
        return record

    scores = [c["score"] for c in result["candidates"]]
    recommended = result["candidates"][result["recommended_index"]]

    record.update(
        {
            "recommended_score": result["recommended_score"],
            "alternate_scores": [
                c["score"] for c in result["candidates"] if c["index"] != result["recommended_index"]
            ],
            "recommended_has_highest_score": result["recommended_score"] >= max(scores),
            "needs_human_review": result["needs_human_review"],
            "vague_term_suggestions": result["vague_term_suggestions"],
            "has_invented_number": recommended["has_invented_number"],
        }
    )

    if recommended["has_invented_number"]:
        record["issues"].append("Recommended candidate contains an invented number")

    if record["is_vague_term_example"]:
        if not result["vague_term_suggestions"]:
            record["issues"].append("Vague-term example produced no suggestion")
        if not result["needs_human_review"]:
            record["issues"].append("Vague-term example did not set needs_human_review")

    return record


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def build_report(per_example: list[dict]) -> dict:
    total = len(per_example)
    evaluated = [r for r in per_example if "pipeline_error" not in r]
    errored = [r for r in per_example if "pipeline_error" in r]

    ears_correct = sum(1 for r in per_example if r["ears_pattern_correct"])

    vague_examples = [r for r in evaluated if r["is_vague_term_example"]]
    vague_with_suggestion = sum(1 for r in vague_examples if r["vague_term_suggestions"])
    vague_with_review = sum(1 for r in vague_examples if r["needs_human_review"])
    invented_number_count = sum(1 for r in evaluated if r["has_invented_number"])

    recommended_scores = [r["recommended_score"] for r in evaluated]
    alternate_scores = [s for r in evaluated for s in r["alternate_scores"]]
    not_highest = [r for r in evaluated if not r["recommended_has_highest_score"]]

    failures = [r for r in per_example if r["issues"]]

    return {
        "eval_set_size": total,
        "evaluated": len(evaluated),
        "pipeline_errors": len(errored),
        "ears_pattern_classification": {
            "correct": ears_correct,
            "total": total,
            "pct_correct": _pct(ears_correct, total),
        },
        "vague_term_handling": {
            "total_vague_term_examples": len(vague_examples),
            "pct_with_suggestion": _pct(vague_with_suggestion, len(vague_examples)),
            "pct_with_needs_human_review": _pct(vague_with_review, len(vague_examples)),
            "pct_invented_numbers": _pct(invented_number_count, len(evaluated)),
        },
        "compliance_scoring": {
            "avg_recommended_score": round(sum(recommended_scores) / len(recommended_scores), 1)
            if recommended_scores else None,
            "avg_alternate_score": round(sum(alternate_scores) / len(alternate_scores), 1)
            if alternate_scores else None,
            "pct_recommended_not_highest_score": _pct(len(not_highest), len(evaluated)),
            "not_highest_score_example_ids": [r["id"] for r in not_highest],
        },
        "failures": failures,
    }


def run_evaluation(compiled_graph, examples: list[dict]) -> dict:
    per_example = [evaluate_example(compiled_graph, example) for example in examples]
    return build_report(per_example)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N examples (quick smoke run)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    client = LocalLLMClient()
    try:
        client.check_reachable()
    except OllamaUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    compiled_graph = build_graph(client=client)
    examples = load_eval_examples(args.limit)

    print(f"Evaluating {len(examples)} example(s) from {EVAL_PATH} ...")
    per_example = []
    start = time.monotonic()
    for i, example in enumerate(examples, start=1):
        print(f"  [{i}/{len(examples)}] {example['id']}")
        per_example.append(evaluate_example(compiled_graph, example))
    elapsed = time.monotonic() - start

    report = build_report(per_example)
    report["elapsed_seconds"] = round(elapsed, 1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    ears = report["ears_pattern_classification"]
    vague = report["vague_term_handling"]
    scoring = report["compliance_scoring"]
    print(f"\nWrote {args.output}")
    print(f"EARS pattern accuracy: {ears['pct_correct']}% ({ears['correct']}/{ears['total']})")
    print(
        f"Vague-term suggestion rate: {vague['pct_with_suggestion']}%  "
        f"needs_human_review rate: {vague['pct_with_needs_human_review']}%  "
        f"invented-number rate: {vague['pct_invented_numbers']}%"
    )
    print(
        f"Avg recommended score: {scoring['avg_recommended_score']}  "
        f"avg alternate score: {scoring['avg_alternate_score']}  "
        f"recommended NOT highest: {scoring['pct_recommended_not_highest_score']}%"
    )
    print(f"Failures: {len(report['failures'])}/{report['eval_set_size']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

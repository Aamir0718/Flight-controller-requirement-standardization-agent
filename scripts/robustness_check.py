"""Runs the full pipeline (src/pipeline/graph.py) against 15-20
hand-written requirements -- flight-controller-style language, none of it
copied from data/golden/fewshot.json or eval.json (checked programmatically
at startup, not just by eyeballing it) -- including a few deliberately
malformed/edge-case inputs: an empty string, a whitespace-only string, an
extremely long over-compounded sentence, non-English text (Chinese and
right-to-left Arabic), a number with no unit anywhere, embedded control
characters, and a bare number with no requirement text at all.

Confirms two things for every case, never assumed, always checked:

1. Nothing crashes. A pipeline exception is caught and recorded as a
   failure on that case, not allowed to abort the whole run.
2. Every input produces either a valid recommendation (real, non-empty
   rewritten text, well-formed output) or a clear needs_human_review
   flag -- never a silent failure (empty/garbage output presented with
   false confidence).

Requires a reachable local Ollama instance -- fails fast with a clear
message and writes no output file if it isn't, same as
scripts/evaluate.py. Never calls any external/hosted API.

Usage:
    python scripts/robustness_check.py [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from llm.local_llm_client import LocalLLMClient, OllamaUnavailableError  # noqa: E402
from pipeline.graph import build_graph, run_requirement  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "data" / "golden"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "robustness_results.json"

_LONG_COMPOUND_SENTENCE = (
    "When the aircraft is on final approach and the landing gear is not down and "
    "locked and the flaps are not in the landing configuration and the throttle is "
    "at idle and the radio altimeter reads below 500 feet and the autopilot is "
    "still engaged and the ground proximity warning system has not already fired "
    "within the last 10 seconds, the ground proximity warning system shall "
    "generate an aural alert and illuminate the master caution light and log the "
    "event to the flight data recorder and transmit a status message to the "
    "maintenance system and reduce the display brightness by 50 percent and "
    "temporarily disable non-essential autopilot modes and notify the cabin crew "
    "panel and increment the event counter in non-volatile memory."
)

CASES: list[dict] = [
    # --- flight-controller-style language, not in the golden dataset ---
    {"id": "normal-01-autopilot-force", "category": "normal",
     "text": "The autopilot shall disengage when the pilot applies more than 10 pounds of force to the control column."},
    {"id": "normal-02-taxi-alerts", "category": "normal",
     "text": "While in taxi mode, the ground collision avoidance system shall inhibit audible alerts below 30 knots groundspeed."},
    {"id": "normal-03-cabin-door", "category": "normal",
     "text": "When the cabin door sensor reports open, the pressurization controller shall prevent engine start."},
    {"id": "normal-04-anti-ice", "category": "normal",
     "text": "The engine anti-ice valve shall cycle open for 500 milliseconds every 10 seconds while icing conditions are detected."},
    {"id": "normal-05-hydraulic-backup", "category": "normal",
     "text": "If the primary hydraulic pump pressure drops below 2800 PSI, the flight control computer shall switch to the backup pump."},
    {"id": "normal-06-terrain-display", "category": "normal",
     "text": "Where a terrain awareness system is installed, the display shall render terrain elevation data using a color gradient keyed to altitude."},
    {"id": "normal-07-low-fuel", "category": "normal",
     "text": "When the fuel quantity indicator reads below 500 pounds, the flight management computer shall illuminate the low fuel annunciator."},
    {"id": "normal-08-satellite-attitude", "category": "normal",
     "text": "The satellite shall maintain attitude within 0.05 degrees over a 24 hour period while consuming less than 2 watts of power."},
    {"id": "normal-09-rotor-brake", "category": "normal",
     "text": "While the rotor brake is engaged, the helicopter flight control computer shall inhibit collective pitch inputs above 5 degrees."},
    {"id": "normal-10-cabin-altitude", "category": "normal",
     "text": "If the cabin altitude exceeds 14000 feet, the emergency oxygen system shall deploy the passenger masks."},
    # --- deliberately malformed / edge cases ---
    {"id": "malformed-01-empty-string", "category": "malformed", "text": ""},
    {"id": "malformed-02-whitespace-only", "category": "malformed", "text": "   \n\t  "},
    {"id": "malformed-03-long-compound-sentence", "category": "malformed", "text": _LONG_COMPOUND_SENTENCE},
    {"id": "malformed-04-chinese", "category": "malformed",
     "text": "当油温超过120摄氏度时，发动机控制单元应降低功率。"},
    {"id": "malformed-05-arabic-rtl", "category": "malformed",
     "text": "يجب على النظام أن يستجيب خلال 100 مللي ثانية."},
    {"id": "malformed-06-number-no-unit", "category": "malformed",
     "text": "The turbine shall not exceed 45000 during takeoff."},
    {"id": "malformed-07-control-characters", "category": "malformed",
     "text": "The system shall\tlog\tthe\x00fault immediately!!!???"},
    {"id": "malformed-08-bare-number", "category": "malformed", "text": "12345"},
]


def _assert_cases_not_in_golden_dataset() -> None:
    golden_texts: set[str] = set()
    for filename in ("fewshot.json", "eval.json"):
        rows = json.loads((GOLDEN_DIR / filename).read_text(encoding="utf-8"))
        for row in rows:
            golden_texts.add(row["bad_requirement"])
            golden_texts.add(row["compliant_version"])

    overlaps = [c["id"] for c in CASES if c["text"] and c["text"] in golden_texts]
    if overlaps:
        raise AssertionError(
            f"robustness cases must not be copied from the golden dataset, but "
            f"these are: {overlaps}"
        )


def _is_well_formed(result: dict) -> list[str]:
    """Structural sanity checks on the pipeline's output shape --
    catches "garbage output" (wrong types, missing fields, out-of-range
    values) even when the call didn't raise."""
    problems = []
    required_keys = {
        "original_text", "source_location", "rule_flags", "ears_pattern",
        "candidates", "recommended_index", "recommended_text",
        "recommended_score", "vague_term_suggestions", "needs_human_review",
    }
    missing = required_keys - result.keys()
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
        return problems  # further checks would just raise KeyError

    if len(result["candidates"]) != 3:
        problems.append(f"expected 3 candidates, got {len(result['candidates'])}")
    if not (0 <= result["recommended_index"] < len(result["candidates"])):
        problems.append(f"recommended_index {result['recommended_index']} out of range")
    if not isinstance(result["recommended_score"], (int, float)):
        problems.append("recommended_score is not numeric")
    elif not (0.0 <= result["recommended_score"] <= 100.0):
        problems.append(f"recommended_score {result['recommended_score']} out of [0, 100]")
    if not isinstance(result["needs_human_review"], bool):
        problems.append("needs_human_review is not a bool")
    for candidate in result["candidates"]:
        if not isinstance(candidate.get("rewritten_text"), str):
            problems.append(f"candidate {candidate.get('index')} rewritten_text is not a string")
    return problems


def check_case(compiled_graph, case: dict) -> dict:
    record: dict = {"id": case["id"], "category": case["category"], "text": case["text"]}

    try:
        result = run_requirement(compiled_graph, case["text"])
    except Exception as exc:  # noqa: BLE001 -- this IS the thing being checked for
        record["crashed"] = True
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["produced_valid_output"] = False
        return record

    record["crashed"] = False
    structural_problems = _is_well_formed(result)
    record["structural_problems"] = structural_problems

    if structural_problems:
        record["produced_valid_output"] = False
        record["needs_human_review"] = result.get("needs_human_review")
        record["recommended_text"] = result.get("recommended_text")
        record["recommended_score"] = result.get("recommended_score")
        return record

    has_usable_text = bool(result["recommended_text"] and result["recommended_text"].strip())
    record.update(
        {
            "needs_human_review": result["needs_human_review"],
            "recommended_text": result["recommended_text"],
            "recommended_score": result["recommended_score"],
            "has_usable_text": has_usable_text,
            # The requirement: a valid recommendation OR a clear
            # needs_human_review flag. If there's no usable text and
            # needs_human_review is False, that's exactly the silent
            # failure / false-confidence case this script exists to catch.
            "produced_valid_output": has_usable_text or result["needs_human_review"],
        }
    )
    return record


def build_report(records: list[dict]) -> dict:
    crashed = [r for r in records if r["crashed"]]
    silent_failures = [r for r in records if not r["crashed"] and not r["produced_valid_output"]]
    structurally_broken = [r for r in records if not r["crashed"] and r.get("structural_problems")]

    return {
        "total_cases": len(records),
        "crashed": len(crashed),
        "crashed_case_ids": [r["id"] for r in crashed],
        "silent_failures": len(silent_failures),
        "silent_failure_case_ids": [r["id"] for r in silent_failures],
        "structurally_broken_case_ids": [r["id"] for r in structurally_broken],
        "all_cases_handled_safely": not crashed and not silent_failures and not structurally_broken,
        "cases": records,
    }


def run_robustness_check(compiled_graph, cases: list[dict] | None = None) -> dict:
    return build_report([check_case(compiled_graph, case) for case in (cases or CASES)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    _assert_cases_not_in_golden_dataset()

    client = LocalLLMClient()
    try:
        client.check_reachable()
    except OllamaUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    compiled_graph = build_graph(client=client)

    print(f"Running {len(CASES)} robustness case(s) ...")
    records = []
    for i, case in enumerate(CASES, start=1):
        preview = case["text"][:50].replace("\n", "\\n").replace("\t", "\\t") or "(empty)"
        print(f"  [{i}/{len(CASES)}] {case['id']} ({case['category']}): {preview!r}")
        records.append(check_case(compiled_graph, case))

    report = build_report(records)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nWrote {args.output}")
    print(f"Crashed: {report['crashed']}/{report['total_cases']} {report['crashed_case_ids']}")
    print(f"Silent failures: {report['silent_failures']}/{report['total_cases']} {report['silent_failure_case_ids']}")
    print(f"All cases handled safely: {report['all_cases_handled_safely']}")

    return 0 if report["all_cases_handled_safely"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

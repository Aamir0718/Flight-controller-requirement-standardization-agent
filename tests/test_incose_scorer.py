"""Tests for src/rules/incose_scorer.py.

Two kinds of coverage, mirroring tests/test_detectors.py:

1. Structural/unit tests: rulebook<->CHECK_REGISTRY parity, ScoreResult
   shape, and hand-written sentences (not from the golden dataset) that
   demonstrate each check is a general pattern, not a lookup.

2. A precision/recall report against data/golden/fewshot.json's labeled
   `defect_type` column: for each labeled defect, does *some* rule in the
   expected subset fail (recall)? And does that same rule subset stay
   passing on the dataset's own compliant_version fix (precision)?

Defect-type variants are grouped into a handful of buckets (rather than
scored one tiny defect_type string at a time) because several individual
defect_type values have only 1-2 python_detectable examples in
fewshot.json -- scoring those alone would be statistically noisy. Bucket
membership and the expected rule-id set per bucket are documented inline.

A note on recall: incose_scorer.py deliberately stays close to the literal
example word lists INCOSE prints for each rule (extended only in the
direction INCOSE's own "such as" phrasing invites -- see comments in
incose_scorer.py). Two buckets are intentionally low-recall as a result:

- "informal_vocabulary" (INCOSE has no rule dedicated to slang/idiom --
  "hunt around", "fix the situation" -- so only the fraction that also
  happens to be a literal R7 vague-quality word gets caught).
- "missing_ears_trigger" (most "Structural Inconsistency" rows are
  domain-semantic contradictions -- e.g. "nominal ambient temperature
  triggers an emergency shutdown" -- that no text pattern can catch;
  R1 only catches the mechanically-detectable slice: a missing/misplaced
  EARS trigger clause).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from rules.incose_scorer import (
    CHECK_REGISTRY,
    ScoreResult,
    load_rulebook,
    score_requirement,
)

FEWSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "fewshot.json"


@pytest.fixture(scope="module")
def fewshot() -> list[dict]:
    return json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rulebook() -> list[dict]:
    return load_rulebook()


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_rulebook_has_42_rules(rulebook):
    assert len(rulebook) == 42
    assert {r["id"] for r in rulebook} == {f"R{i}" for i in range(1, 43)}


def test_every_rule_has_required_fields(rulebook):
    for rule in rulebook:
        assert rule["id"]
        assert rule["category"]
        assert rule["title"]
        assert rule["description"]
        assert isinstance(rule["automatable"], bool)
        if rule["automatable"]:
            assert rule.get("check_strategy"), f"{rule['id']} is automatable but has no check_strategy"
        else:
            assert rule.get("rationale_not_automatable"), f"{rule['id']} is not automatable but has no rationale"


def test_check_registry_matches_automatable_rules_exactly(rulebook):
    automatable_ids = {r["id"] for r in rulebook if r["automatable"]}
    assert set(CHECK_REGISTRY.keys()) == automatable_ids


def test_score_requirement_runs_every_automatable_rule(rulebook):
    automatable_count = sum(1 for r in rulebook if r["automatable"])
    result = score_requirement("The system shall respond within 100 ms.")
    assert isinstance(result, ScoreResult)
    assert result.total_rules == automatable_count
    assert len(result.passed) + len(result.failed) == automatable_count


def test_score_is_a_percentage():
    result = score_requirement("The system shall respond within 100 ms.")
    assert 0.0 <= result.score <= 100.0


def test_failed_rules_carry_id_title_category_and_reasons():
    result = score_requirement("When started, the software shall initialize and display status.")
    assert result.failed
    for f in result.failed:
        assert re.fullmatch(r"R\d+", f.id)
        assert f.title
        assert f.category
        assert f.reasons and all(isinstance(r, str) and r for r in f.reasons)


def test_scorer_is_pure_and_deterministic():
    text = "While in orbit, the star tracker shall track reference stars continuously."
    a = score_requirement(text)
    b = score_requirement(text)
    assert a == b


# ---------------------------------------------------------------------------
# Unit tests on requirement text NOT in the golden dataset
# ---------------------------------------------------------------------------


def _failed_ids(text: str) -> set[str]:
    return {f.id for f in score_requirement(text).failed}


class TestIndividualRuleChecks:
    def test_r1_flags_conditional_embedded_after_shall(self):
        text = "The display shall overlay a warning icon if the primary sensor becomes unavailable."
        assert "R1" in _failed_ids(text)

    def test_r1_accepts_well_formed_event_driven_requirement(self):
        text = "When the temperature exceeds 60C, the cooler shall activate the fan."
        assert "R1" not in _failed_ids(text)

    def test_r2_flags_passive_voice(self):
        assert "R2" in _failed_ids("The checksum shall be verified before execution begins.")

    def test_r2_accepts_active_voice(self):
        assert "R2" not in _failed_ids("The bootloader shall verify the checksum before execution begins.")

    def test_r5_flags_indefinite_article_subject(self):
        assert "R5" in _failed_ids("A sensor shall report the ambient temperature.")

    def test_r5_accepts_definite_article_subject(self):
        assert "R5" not in _failed_ids("The sensor shall report the ambient temperature.")

    def test_r6_flags_bare_number(self):
        assert "R6" in _failed_ids("The alarm shall trigger when pressure exceeds 100.")

    def test_r6_accepts_number_with_unit(self):
        assert "R6" not in _failed_ids("The alarm shall trigger when pressure exceeds 100 PSI.")

    def test_r7_flags_incose_vague_term_never_seen_in_golden_set(self):
        assert "R7" in _failed_ids("The gateway shall synchronize its clock adequately during startup.")

    def test_r8_flags_escape_clause(self):
        assert "R8" in _failed_ids("The relay shall isolate the circuit where possible.")

    def test_r9_flags_open_ended_clause(self):
        assert "R9" in _failed_ids("The logger shall record temperature, pressure, humidity, etc.")

    def test_r10_flags_superfluous_infinitive(self):
        assert "R10" in _failed_ids("The module shall be able to isolate the circuit.")

    def test_r11_flags_multiple_conditions_combined(self):
        text = "If the sensor fails and when the backup activates, the system shall log the event."
        assert "R11" in _failed_ids(text)

    def test_r16_flags_not(self):
        assert "R16" in _failed_ids("The pump shall not run dry.")

    def test_r16_accepts_positive_statement(self):
        assert "R16" not in _failed_ids("The controller shall command the actuator to the retracted position.")

    def test_r17_flags_oblique_symbol_outside_units(self):
        assert "R17" in _failed_ids("The system shall log the fault/error to non-volatile memory.")

    def test_r17_accepts_composite_unit(self):
        assert "R17" not in _failed_ids("The vehicle shall not exceed a speed of 120 km/h.")

    def test_r18_flags_multiple_shall_in_one_sentence(self):
        text = "The system shall detect the fault and the system shall log the fault."
        assert "R18" in _failed_ids(text)

    def test_r18_accepts_properly_split_sentences(self):
        text = "When started, the software shall initialize. When initialized, the software shall display status."
        assert "R18" not in _failed_ids(text)

    def test_r19_flags_combinator(self):
        assert "R19" in _failed_ids("The controller shall log the event and notify the operator.")

    def test_r21_flags_parenthetical_clause(self):
        text = "The system shall log the fault (which may take several forms depending on the subsystem)."
        assert "R21" in _failed_ids(text)

    def test_r24_flags_pronoun(self):
        assert "R24" in _failed_ids("If data is invalid, the software shall reject it.")

    def test_r26_flags_absolute(self):
        assert "R26" in _failed_ids("The pump shall never run dry.")

    def test_r28_flags_single_condition_multiple_actions(self):
        text = "When started, the software shall initialize and display status."
        assert "R28" in _failed_ids(text)

    def test_r32_flags_all_any_both(self):
        assert "R32" in _failed_ids("The controller shall poll all sensors every cycle.")

    def test_r33_flags_missing_tolerance(self):
        assert "R33" in _failed_ids("The heater shall maintain a temperature of 50C.")

    def test_r33_accepts_explicit_tolerance(self):
        assert "R33" not in _failed_ids("The heater shall maintain a temperature of 50 +/- 2C.")

    def test_r34_flags_unbounded_optimization(self):
        assert "R34" in _failed_ids("The controller shall optimize throttle response timing.")

    def test_r35_flags_indefinite_temporal_keyword(self):
        assert "R35" in _failed_ids("The gateway shall transmit power usage logs periodically.")

    def test_r38_flags_abbreviation(self):
        assert "R38" in _failed_ids("The display shall show the max. permissible speed.")

    def test_r40_flags_decimal_missing_leading_zero(self):
        assert "R40" in _failed_ids("The sensor shall report drift below .5 degrees per hour.")

    def test_r40_accepts_leading_zero(self):
        assert "R40" not in _failed_ids("The sensor shall report drift below 0.5 degrees per hour.")

    def test_precisely_written_requirement_scores_highly(self):
        text = "When the temperature exceeds 60.0 +/- 0.5C, the cooler shall activate the fan within 200 milliseconds."
        result = score_requirement(text)
        assert result.score >= 85.0


# ---------------------------------------------------------------------------
# Precision / recall report against data/golden/fewshot.json
# ---------------------------------------------------------------------------

# Buckets group related defect_type strings (several have only 1-2
# python_detectable examples individually) and state which automatable
# rule ids are expected to fail for that bucket's defects.
_BUCKETS = [
    {
        "name": "vague_family",
        "defect_types": [
            "Non-Verifiable", "Non-Verifiable / Unbounded", "Subjectivity / Non-Verifiable",
            "Vagueness", "Vagueness / Ambiguity", "Incompleteness / Vagueness",
            "Ambiguity / Vagueness", "Ambiguity", "Ambiguity / Subjectivity",
            "Ambiguity / Escape Clause", "Lack of Precision", "Subjectivity",
        ],
        "rule_ids": {"R7", "R8", "R33", "R34", "R35"},
        "min_recall": 0.75,
        "min_precision": 0.6,
    },
    {
        "name": "informal_vocabulary",
        "defect_types": ["Non-Standard Syntax/Vocabulary"],
        "rule_ids": {"R7"},
        "min_recall": 0.3,  # INCOSE has no rule dedicated to slang/idiom, see module docstring
        "min_precision": 0.6,
    },
    {
        "name": "escape_clause",
        "defect_types": ["Regulatory / Escape Clause"],
        "rule_ids": {"R8"},
        "min_recall": 0.5,
        "min_precision": 0.6,
    },
    {
        "name": "open_ended",
        "defect_types": ["Incompleteness"],
        "rule_ids": {"R9"},
        "min_recall": 0.6,
        "min_precision": 0.6,
    },
    {
        "name": "negative_constraint",
        "defect_types": ["Subtle Negative Constraint"],
        "rule_ids": {"R16", "R26"},
        "min_recall": 0.5,
        "min_precision": 0.6,
    },
    {
        "name": "compound_requirement",
        "defect_types": ["Non-Atomic Multiple Behaviors", "Singular"],
        "rule_ids": {"R11", "R18", "R19", "R28"},
        "min_recall": 0.9,
        "min_precision": 0.6,
    },
    {
        "name": "missing_ears_trigger",
        "defect_types": ["Structural Inconsistency"],
        "rule_ids": {"R1"},
        "min_recall": 0.15,  # mostly out-of-scope semantic defects, see module docstring
        "min_precision": 0.6,
    },
    {
        "name": "passive_voice",
        "defect_types": ["Passive Voice / Missing Actor"],
        "rule_ids": {"R2"},
        "min_recall": 0.9,
        "min_precision": 0.9,
    },
]


def test_precision_recall_against_fewshot_golden_labels(fewshot):
    positives = [row for row in fewshot if row["python_detectable"] is True]
    by_defect_type = defaultdict(list)
    for row in positives:
        by_defect_type[row["defect_type"]].append(row)

    report_lines = ["", f"{'bucket':<22}{'recall':>10}{'precision':>12}{'support':>10}"]
    failures = []

    for bucket in _BUCKETS:
        rows = [r for dt in bucket["defect_types"] for r in by_defect_type.get(dt, [])]
        if not rows:
            continue

        tp = fn = 0
        fn_examples = []
        for row in rows:
            failed_ids = {f.id for f in score_requirement(row["bad_requirement"]).failed}
            if failed_ids & bucket["rule_ids"]:
                tp += 1
            else:
                fn += 1
                fn_examples.append(row["id"])

        fp = tn = 0
        fp_examples = []
        for row in rows:
            failed_ids = {f.id for f in score_requirement(row["compliant_version"]).failed}
            if failed_ids & bucket["rule_ids"]:
                fp += 1
                fp_examples.append(row["id"])
            else:
                tn += 1

        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        report_lines.append(
            f"{bucket['name']:<22}{recall:>10.2f}{precision:>12.2f}{len(rows):>10d}"
        )
        if fn_examples:
            report_lines.append(f"  false negatives: {fn_examples}")
        if fp_examples:
            report_lines.append(f"  false positives (fired on compliant_version): {fp_examples}")

        if recall < bucket["min_recall"]:
            failures.append(f"{bucket['name']}: recall {recall:.2f} < required {bucket['min_recall']:.2f}")
        if precision < bucket["min_precision"]:
            failures.append(f"{bucket['name']}: precision {precision:.2f} < required {bucket['min_precision']:.2f}")

    report = "\n".join(report_lines)
    print(report)
    assert not failures, "\n".join(failures) + "\n" + report

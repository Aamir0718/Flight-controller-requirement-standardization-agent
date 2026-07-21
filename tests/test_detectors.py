"""Tests for src/rules/detectors.py.

Two kinds of coverage on purpose:

1. Unit tests on hand-written sentences that do NOT appear in the golden
   dataset -- these prove the detectors are general pattern checks, not
   lookups keyed on the 210 fewshot/eval rows (see module docstring in
   detectors.py).

2. A precision/recall report against data/golden/fewshot.json's labeled
   `defect_type` column (per the task: eval.json informed which detectors
   to build, but only fewshot.json is used for assertions here).

A note on the recall numbers below: several `defect_type` values describe
defects that need real-world/domain knowledge to catch (e.g. "a nominal
ambient temperature should not trigger an emergency shutdown", "TCAS not
installed but still computing advisories") rather than a text pattern. The
detectors here are deliberately *not* built to special-case those -- doing
so would mean overfitting to the 210 labeled examples instead of writing
something that generalizes to unseen requirements. Recall for
"Structural Inconsistency" is intentionally partial as a result: only the
mechanically-detectable slice (a trigger clause that is missing or placed
after the 'shall' action instead of leading the sentence) is in scope for
the EARS-trigger detector.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from rules.detectors import (
    Finding,
    detect_compound_requirement,
    detect_missing_ears_trigger,
    detect_missing_units,
    detect_negative_constraints,
    detect_passive_voice,
    detect_vague_terms,
    run_all_detectors,
)

FEWSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "fewshot.json"


@pytest.fixture(scope="module")
def fewshot() -> list[dict]:
    return json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Unit tests: general behavior on requirement text NOT in the golden dataset
# ---------------------------------------------------------------------------


class TestVagueTermDetector:
    def test_flags_incose_r7_words_never_seen_in_golden_set(self):
        text = "The gateway shall synchronize its clock adequately during startup."
        findings = detect_vague_terms(text)
        assert any(f.span.lower() == "adequately" for f in findings)

    def test_flags_escape_clause(self):
        text = "The relay shall isolate the circuit where applicable."
        findings = detect_vague_terms(text)
        assert any("where applicable" in f.span.lower() for f in findings)

    def test_flags_open_ended_scope_etc(self):
        text = "The logger shall record temperature, pressure, humidity, etc."
        findings = detect_vague_terms(text)
        assert any("etc" in f.span.lower() for f in findings)

    def test_no_false_positive_on_precise_requirement(self):
        text = "The pump controller shall close the inlet valve within 250 milliseconds."
        findings = detect_vague_terms(text)
        assert findings == []

    def test_bounded_at_least_is_not_flagged_but_unbounded_is(self):
        bounded = "The filter shall achieve a rejection ratio of at least 40 dB."
        unbounded = "The filter shall achieve a rejection ratio of at least acceptable levels."
        assert detect_vague_terms(bounded) == []
        assert any(f.span.lower() == "at least" for f in detect_vague_terms(unbounded))

    def test_finding_fields_are_populated_and_span_matches_offsets(self):
        text = "The unit shall respond appropriately to any fault."
        findings = detect_vague_terms(text)
        assert findings
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.violation_type == "vague_term"
        assert text[f.start:f.end] == f.span
        assert 0.0 < f.confidence <= 1.0
        assert f.reason and f.span.lower() in f.reason.lower()


class TestNegativeConstraintDetector:
    def test_flags_shall_not(self):
        findings = detect_negative_constraints("The valve shall not open above 500 PSI.")
        assert any("shall not" in f.span.lower() for f in findings)

    def test_flags_never(self):
        findings = detect_negative_constraints("The pump shall never run dry.")
        assert any("never" in f.span.lower() for f in findings)

    def test_flags_soft_negative_verbs_avoid_and_prevent(self):
        avoid_findings = detect_negative_constraints("The winch shall avoid overspeeding the drum.")
        prevent_findings = detect_negative_constraints("The latch shall prevent accidental release.")
        assert any("avoid" in f.span.lower() for f in avoid_findings)
        assert any("prevent" in f.span.lower() for f in prevent_findings)

    def test_bypass_as_hardware_noun_is_not_flagged(self):
        # "bypass valve"/"bypass circuit" are common component names, not the
        # negative verb "shall bypass X".
        findings = detect_negative_constraints(
            "The controller shall open the secondary cooling bypass valve."
        )
        assert findings == []

    def test_flags_double_negative(self):
        text = "The system shall not leave the surfaces in an un-commanded state."
        findings = detect_negative_constraints(text)
        assert any("double_negative" in f.reason for f in findings)

    def test_no_false_positive_on_positive_statement(self):
        text = "The controller shall command the actuator to the retracted position."
        assert detect_negative_constraints(text) == []


class TestMissingUnitDetector:
    def test_flags_dangling_number(self):
        findings = detect_missing_units("The alarm shall trigger when pressure exceeds 100.")
        assert any(f.span == "100" for f in findings)

    def test_accepts_number_with_unit(self):
        findings = detect_missing_units("The alarm shall trigger when pressure exceeds 100 PSI.")
        assert findings == []

    def test_accepts_fused_unit_notation(self):
        findings = detect_missing_units("The heater shall shut off above 85C.")
        assert findings == []

    def test_accepts_hyphenated_unit_fusion(self):
        findings = detect_missing_units("The buffer shall store a 256-byte packet.")
        assert findings == []

    def test_ignores_code_identifiers_not_measurements(self):
        findings = detect_missing_units("The module shall comply with standard IEC-61508.")
        assert findings == []

    def test_ignores_clock_time_format(self):
        findings = detect_missing_units("The job shall run daily at 00:00:00 UTC.")
        assert findings == []

    def test_flags_threshold_language_with_no_number_anywhere(self):
        findings = detect_missing_units("The relay shall open when current exceeds the safe level.")
        assert any(f.span.lower() == "exceeds" for f in findings)


class TestCompoundRequirementDetector:
    def test_flags_two_verbs_joined_by_and(self):
        findings = detect_compound_requirement(
            "When started, the software shall initialize and display status."
        )
        assert any(f.confidence >= 0.8 for f in findings)

    def test_flags_and_or(self):
        findings = detect_compound_requirement(
            "The controller shall log the event and/or notify the operator."
        )
        assert any("and/or" in f.span.lower() for f in findings)

    def test_flags_multiple_shall_in_one_sentence(self):
        findings = detect_compound_requirement(
            "The system shall detect the fault and the system shall log the fault."
        )
        assert any("multiple_shall" in f.reason for f in findings)

    def test_properly_split_sentences_are_not_flagged_as_multiple_shall(self):
        text = "When started, the software shall initialize. When initialized, the software shall display status."
        findings = detect_compound_requirement(text)
        assert not any("multiple_shall" in f.reason for f in findings)

    def test_no_false_positive_on_single_action(self):
        text = "The controller shall close the isolation valve within 50 milliseconds."
        assert detect_compound_requirement(text) == []


class TestMissingEarsTriggerDetector:
    def test_flags_wrong_leading_word_for_labeled_pattern(self):
        text = "The cooler shall activate the fan when the temperature exceeds 60C."
        findings = detect_missing_ears_trigger(text, ears_pattern="Event-driven")
        assert any("missing_trigger_keyword" in f.reason for f in findings)

    def test_accepts_correct_leading_trigger(self):
        text = "When the temperature exceeds 60C, the cooler shall activate the fan."
        assert detect_missing_ears_trigger(text, ears_pattern="Event-driven") == []

    def test_flags_conditional_embedded_after_shall(self):
        text = "The display shall overlay a warning icon if the primary sensor becomes unavailable."
        findings = detect_missing_ears_trigger(text)
        assert any("embedded_conditional" in f.reason for f in findings)

    def test_flags_unexpected_trigger_in_ubiquitous_requirement(self):
        text = "While in test mode, the logger shall discard all samples."
        findings = detect_missing_ears_trigger(text, ears_pattern="Ubiquitous")
        assert any("unexpected_trigger_keyword" in f.reason for f in findings)

    def test_no_false_positive_on_well_formed_requirement(self):
        text = "While in low-power mode, the MCU shall disable the ADC peripheral."
        assert detect_missing_ears_trigger(text, ears_pattern="State-driven") == []


class TestPassiveVoiceDetectorBonus:
    """Not one of the required five, but the same general-pattern approach
    catches this common defect class cheaply (see detectors.py)."""

    def test_flags_passive_shall_be(self):
        text = "The checksum shall be verified before execution begins."
        findings = detect_passive_voice(text)
        assert any("verified" in f.span for f in findings)

    def test_no_false_positive_on_active_voice(self):
        text = "The bootloader shall verify the checksum before execution begins."
        assert detect_passive_voice(text) == []


def test_run_all_detectors_aggregates_and_sorts_by_position():
    text = "The system shall never bypass the safety interlock and shall optimize throughput."
    findings = run_all_detectors(text)
    assert len(findings) >= 2
    assert [f.start for f in findings] == sorted(f.start for f in findings)


# ---------------------------------------------------------------------------
# Precision / recall report against data/golden/fewshot.json
# ---------------------------------------------------------------------------

# Maps a golden-dataset defect_type to the detector category expected to
# catch it. Only defect types that are, in principle, mechanically
# detectable by *this* module's category are listed; anything absent is
# out of scope (e.g. "Feasible"/"Verifiable" require domain judgement, and
# every such row in fewshot.json is marked python_detectable: null anyway).
CATEGORY_FOR_DEFECT_TYPE: dict[str, str] = {
    **{
        dt: "vague_term"
        for dt in [
            "Non-Verifiable", "Non-Verifiable / Unbounded", "Subjectivity / Non-Verifiable",
            "Vagueness", "Vagueness / Ambiguity", "Incompleteness / Vagueness",
            "Ambiguity / Vagueness", "Ambiguity", "Ambiguity / Subjectivity",
            "Ambiguity / Escape Clause", "Lack of Precision", "Subjectivity",
            "Non-Standard Syntax/Vocabulary", "Regulatory / Escape Clause", "Incompleteness",
        ]
    },
    "Subtle Negative Constraint": "negative_constraint",
    "Non-Atomic Multiple Behaviors": "compound_requirement",
    "Singular": "compound_requirement",
    "Structural Inconsistency": "missing_ears_trigger",
    "Passive Voice / Missing Actor": "passive_voice",  # bonus detector
}

DETECTOR_FOR_CATEGORY = {
    "vague_term": detect_vague_terms,
    "negative_constraint": detect_negative_constraints,
    "compound_requirement": detect_compound_requirement,
    "passive_voice": detect_passive_voice,
    # "missing_ears_trigger" is handled separately: it takes ears_pattern.
}

# Categories with at least one python_detectable==true example in
# fewshot.json to compute recall against (Singular's examples are all the
# EX50-* template rows, which are all python_detectable: null).
MIN_RECALL = {
    "vague_term": 0.85,
    "negative_constraint": 0.9,
    "compound_requirement": 0.9,
    "missing_ears_trigger": 0.15,  # mostly out-of-scope semantic defects, see module docstring
    "passive_voice": 0.9,
}
MIN_PRECISION = {
    "vague_term": 0.9,
    "negative_constraint": 0.9,
    "compound_requirement": 0.9,
    "missing_ears_trigger": 0.9,
    "passive_voice": 0.9,
}


def _findings_for(category: str, text: str, ears_pattern: str | None) -> list[Finding]:
    if category == "missing_ears_trigger":
        return detect_missing_ears_trigger(text, ears_pattern)
    return DETECTOR_FOR_CATEGORY[category](text)


def test_precision_recall_against_fewshot_golden_labels(fewshot):
    positives = [row for row in fewshot if row["python_detectable"] is True]

    tp = defaultdict(int)
    fn = defaultdict(int)
    fn_examples = defaultdict(list)
    for row in positives:
        category = CATEGORY_FOR_DEFECT_TYPE.get(row["defect_type"])
        if category is None:
            continue
        findings = _findings_for(category, row["bad_requirement"], row["ears_pattern"])
        if findings:
            tp[category] += 1
        else:
            fn[category] += 1
            fn_examples[category].append(row["id"])

    # Precision proxy: the same detector must NOT fire on the golden fix
    # for that row (compliant_version). For missing_ears_trigger we drop the
    # stale ears_pattern label -- the fix frequently changes which EARS
    # pattern applies, e.g. an embedded "if" moved to a leading clause turns
    # a mis-tagged "Ubiquitous" row into a proper "Unwanted Behavior" one,
    # so re-checking against the *original* label would be an unfair test
    # of the rewritten text, not of the detector.
    fp = defaultdict(int)
    tn = defaultdict(int)
    fp_examples = defaultdict(list)
    for row in positives:
        category = CATEGORY_FOR_DEFECT_TYPE.get(row["defect_type"])
        if category is None:
            continue
        ears_hint = None if category == "missing_ears_trigger" else row["ears_pattern"]
        findings = _findings_for(category, row["compliant_version"], ears_hint)
        if findings:
            fp[category] += 1
            fp_examples[category].append(row["id"])
        else:
            tn[category] += 1

    report_lines = ["", f"{'category':<22}{'recall':>10}{'precision':>12}{'support':>10}"]
    categories = sorted(set(tp) | set(fn) | set(fp) | set(tn))
    results = {}
    for category in categories:
        recall_total = tp[category] + fn[category]
        precision_total = tp[category] + fp[category]
        recall = tp[category] / recall_total if recall_total else float("nan")
        precision = tp[category] / precision_total if precision_total else float("nan")
        results[category] = (recall, precision, recall_total)
        report_lines.append(f"{category:<22}{recall:>10.2f}{precision:>12.2f}{recall_total:>10d}")
    report_lines.append("")
    for category, ids in fn_examples.items():
        report_lines.append(f"false negatives [{category}]: {ids}")
    for category, ids in fp_examples.items():
        report_lines.append(f"false positives [{category}] (fired on compliant_version): {ids}")
    report = "\n".join(report_lines)
    print(report)

    failures = []
    for category, (recall, precision, support) in results.items():
        if support == 0:
            continue
        min_recall = MIN_RECALL.get(category, 0.0)
        min_precision = MIN_PRECISION.get(category, 0.0)
        if recall < min_recall:
            failures.append(f"{category}: recall {recall:.2f} < required {min_recall:.2f}")
        if precision < min_precision:
            failures.append(f"{category}: precision {precision:.2f} < required {min_precision:.2f}")

    assert not failures, "\n".join(failures) + "\n" + report

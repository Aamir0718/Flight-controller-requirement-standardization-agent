"""Tests for src/rules/rule_selector.py."""

from __future__ import annotations

from rules.detectors import Finding, run_all_detectors
from rules.incose_scorer import load_rulebook
from rules.rule_selector import FLAG_TO_RULE_IDS, select_relevant_rules


def test_no_flags_returns_empty_list():
    assert select_relevant_rules([]) == []


def test_unknown_flag_is_ignored_not_an_error():
    assert select_relevant_rules(["some_flag_no_detector_produces"]) == []


def test_single_flag_returns_a_reduced_subset_not_all_42():
    rules = select_relevant_rules(["vague_term"])
    assert rules
    assert len(rules) < 42
    assert {r["id"] for r in rules} == set(FLAG_TO_RULE_IDS["vague_term"])


def test_every_flag_type_maps_to_at_least_one_rule():
    for flag, rule_ids in FLAG_TO_RULE_IDS.items():
        rules = select_relevant_rules([flag])
        assert rules, f"flag '{flag}' selected no rules"
        assert {r["id"] for r in rules} == set(rule_ids)


def test_multiple_flags_union_without_duplicates():
    rules = select_relevant_rules(["vague_term", "negative_constraint"])
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(FLAG_TO_RULE_IDS["vague_term"]) | set(FLAG_TO_RULE_IDS["negative_constraint"])


def test_returned_rules_are_full_rulebook_entries():
    rules = select_relevant_rules(["passive_voice"])
    assert rules
    for rule in rules:
        assert rule.keys() >= {"id", "category", "title", "description", "automatable"}


def test_accepts_finding_objects_directly_not_just_strings():
    finding = Finding(
        violation_type="negative_constraint",
        span="shall not",
        start=0,
        end=9,
        confidence=0.9,
        reason="test",
    )
    rules = select_relevant_rules([finding])
    assert {r["id"] for r in rules} == set(FLAG_TO_RULE_IDS["negative_constraint"])


def test_selection_is_deterministically_ordered():
    a = [r["id"] for r in select_relevant_rules(["vague_term", "compound_requirement"])]
    b = [r["id"] for r in select_relevant_rules(["compound_requirement", "vague_term"])]
    assert a == b  # order shouldn't depend on flag iteration order


def test_integration_with_real_detector_output():
    text = "When crosswind velocity exceeds 30 knots, the autoland system shall issue a go-around command packet to the FCC."
    findings = run_all_detectors(text, ears_pattern="Event-driven")
    rules = select_relevant_rules(findings)
    flags_present = {f.violation_type for f in findings}
    if flags_present:
        assert rules
        assert len(rules) < 42
    expected = set()
    for flag in flags_present:
        expected |= set(FLAG_TO_RULE_IDS.get(flag, ()))
    assert {r["id"] for r in rules} == expected


def test_all_rule_ids_referenced_by_flags_exist_in_rulebook():
    rulebook_ids = {r["id"] for r in load_rulebook()}
    for flag, rule_ids in FLAG_TO_RULE_IDS.items():
        for rule_id in rule_ids:
            assert rule_id in rulebook_ids, f"{flag} references unknown rule {rule_id}"

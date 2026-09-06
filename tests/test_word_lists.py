"""Tests for src/rules/word_lists.py -- the Excel-backed loader every
plain word/phrase list in src/rules/incose_scorer.py and src/rules/
ears_classifier.py now reads from, instead of being hardcoded in Python.
"""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from rules.word_lists import load_word_list


def _write_workbook(path, sheets: dict[str, list]):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        sheet = wb.create_sheet(name)
        sheet.append(["description"])
        for row in rows:
            sheet.append([row])
    wb.save(path)


def test_reads_terms_starting_at_row_2(tmp_path):
    path = tmp_path / "word_lists.xlsx"
    _write_workbook(path, {"vague_terms": ["some", "several", "many"]})
    assert load_word_list("vague_terms", path) == ("some", "several", "many")


def test_skips_blank_rows(tmp_path):
    path = tmp_path / "word_lists.xlsx"
    _write_workbook(path, {"acronyms": ["GPS", None, "  ", "UAV"]})
    assert load_word_list("acronyms", path) == ("GPS", "UAV")


def test_strips_whitespace(tmp_path):
    path = tmp_path / "word_lists.xlsx"
    _write_workbook(path, {"escape_clauses": ["  where possible  "]})
    assert load_word_list("escape_clauses", path) == ("where possible",)


def test_unknown_sheet_raises_key_error_naming_available_sheets(tmp_path):
    path = tmp_path / "word_lists.xlsx"
    _write_workbook(path, {"vague_terms": ["some"]})
    with pytest.raises(KeyError, match="vague_terms"):
        load_word_list("nonexistent_sheet", path)


def test_real_word_lists_workbook_has_every_sheet_the_rule_checkers_need():
    expected_sheets = {
        "weak_modals", "acronyms", "vague_terms", "escape_clauses",
        "superfluous_infinitives", "combinator_words", "purpose_phrases",
        "group_noun_references", "personal_pronouns", "unachievable_absolutes",
        "implied_applicability", "universal_quantifiers", "optimization_language",
        "indefinite_temporal_keywords", "banned_abbreviations", "action_verbs",
    }
    for sheet in expected_sheets:
        terms = load_word_list(sheet)
        assert len(terms) > 0, f"{sheet} sheet is empty"


def test_real_acronyms_sheet_includes_the_guides_examples():
    acronyms = {a.upper() for a in load_word_list("acronyms")}
    assert "UAV" in acronyms
    assert "ADC" in acronyms


def test_real_weak_modals_sheet_includes_should_and_must():
    weak_modals = {w.lower() for w in load_word_list("weak_modals")}
    assert "should" in weak_modals
    assert "must" in weak_modals

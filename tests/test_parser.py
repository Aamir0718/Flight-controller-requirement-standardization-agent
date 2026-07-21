"""Tests for src/ingestion/parser.py against synthetic messy .xlsx
fixtures in tests/fixtures/ (see build_fixtures.py for how they were
generated). These are deliberately NOT the clean golden dataset — they
simulate the kind of hand-edited, inconsistent sheets a real DRDO
submission is likely to contain.
"""

from pathlib import Path

import pytest

from ingestion.parser import parse_directory, parse_workbook

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_multi_sheet_extracts_requirements_and_skips_junk():
    result = parse_workbook(FIXTURES_DIR / "messy_multi_sheet.xlsx")

    assert not result.issues

    texts = {c.text for c in result.candidates}
    assert "The flight control computer shall compute attitude at 50 Hz." in texts
    assert "While on battery power, the system shall enter low power mode." in texts
    assert (
        "When an overheat condition is detected, the FCC shall shut down the affected channel."
        in texts
    )

    # "TBD" (row 8, requirement column) is a junk placeholder: too short to
    # be a requirement, and must be skipped rather than fabricated into one.
    tbd_skips = [
        s for s in result.skipped
        if s.location.sheet_name == "Requirements" and s.location.row == 8 and s.raw_value == "TBD"
    ]
    assert len(tbd_skips) == 1
    assert tbd_skips[0].reason.startswith("too_few_words")

    # The fully blank row (row 6) contributes nothing but empty_cell skips.
    row_6_skips = [
        s for s in result.skipped
        if s.location.sheet_name == "Requirements" and s.location.row == 6
    ]
    assert row_6_skips and all(s.reason == "empty_cell" for s in row_6_skips)

    # The "Legend" sheet is pure abbreviation definitions: short cells
    # everywhere, so it should yield zero candidate requirements.
    legend_candidates = [c for c in result.candidates if c.location.sheet_name == "Legend"]
    assert legend_candidates == []


def test_merged_note_row_is_deduplicated_and_skipped_as_junk():
    result = parse_workbook(FIXTURES_DIR / "messy_multi_sheet.xlsx")

    # The merged note banner at A7:E7 is a genuine junk/note row (no
    # recognized verb): it must be evaluated exactly once, from its anchor
    # cell, and correctly skipped there rather than fabricated into a
    # candidate — never once per cell in the merged range either way.
    note_text = "Note: Section reviewed by QA lead on 2024-01-10"
    assert all(note_text not in c.text for c in result.candidates)

    anchor_skip = [
        s for s in result.skipped
        if s.location.sheet_name == "Requirements" and s.location.cell_reference == "A7"
    ]
    assert len(anchor_skip) == 1
    assert anchor_skip[0].reason == "no_verb_detected"

    duplicates = [
        s for s in result.skipped
        if s.reason == "merged_cell_duplicate" and s.location.sheet_name == "Requirements"
        and s.location.row == 7
    ]
    assert {s.location.cell_reference for s in duplicates} == {"B7", "C7", "D7", "E7"}
    assert all(s.location.merge_anchor == (7, 1) for s in duplicates)


def test_merged_title_banner_deduplicated_across_row_1():
    result = parse_workbook(FIXTURES_DIR / "messy_multi_sheet.xlsx")

    duplicates = [
        s for s in result.skipped
        if s.reason == "merged_cell_duplicate" and s.location.sheet_name == "Requirements"
        and s.location.row == 1
    ]
    assert {s.location.cell_reference for s in duplicates} == {"B1", "C1", "D1", "E1"}

    # Exactly one candidate should come from the anchor cell A1 (the title
    # text happens to contain the word "control", which our keyword-only
    # heuristic cannot distinguish from a verb — a known, documented
    # limitation of the "simple heuristic first" approach, not a bug).
    title_candidates = [c for c in result.candidates if c.location.cell_reference == "A1"]
    assert len(title_candidates) == 1


def test_header_row_not_assumed_to_be_row_one():
    """Header lives at row 4 (after a merged title + blank rows); the
    parser must still find the real requirements without any special
    casing for where the header sits."""
    result = parse_workbook(FIXTURES_DIR / "header_row_offset.xlsx")

    assert not result.issues
    texts = {c.text for c in result.candidates}
    assert (
        "If the primary sensor fails, then the software shall switch to the backup sensor."
        in texts
    )
    assert (
        "While in autonomous mode, the navigation unit shall log its position every second."
        in texts
    )

    # A mid-sheet merged section banner ("SECTION 2 — NAVIGATION") is a
    # junk heading, not a requirement: it must not appear as a candidate,
    # and must be evaluated once (at its anchor) rather than 4 times.
    assert all("SECTION 2" not in c.text for c in result.candidates)

    banner_anchor_skip = [
        s for s in result.skipped
        if s.location.sheet_name == "Section A" and s.location.cell_reference == "A7"
    ]
    assert len(banner_anchor_skip) == 1
    assert banner_anchor_skip[0].reason == "no_verb_detected"

    banner_duplicates = [
        s for s in result.skipped
        if s.reason == "merged_cell_duplicate" and s.location.sheet_name == "Section A"
        and s.location.row == 7
    ]
    assert {s.location.cell_reference for s in banner_duplicates} == {"B7", "C7", "D7"}


def test_completely_empty_sheet_does_not_crash():
    result = parse_workbook(FIXTURES_DIR / "header_row_offset.xlsx")
    assert not any(issue.sheet_name == "Unused" for issue in result.issues)
    assert all(c.location.sheet_name != "Unused" for c in result.candidates)


def test_edge_case_cell_values_are_handled():
    result = parse_workbook(FIXTURES_DIR / "edge_cases.xlsx")

    assert not result.issues

    reasons_by_row = {s.location.row: s.reason for s in result.skipped if s.location.column == 2}
    assert reasons_by_row[2] == "formula_error_value"          # "#REF!"
    assert reasons_by_row[3].startswith("too_few_words")        # 42
    assert reasons_by_row[4].startswith("too_few_words")        # date
    assert reasons_by_row[5] == "no_verb_detected"               # legal footer, verb-free

    texts = {c.text for c in result.candidates}
    assert (
        "If the cabin altitude exceeds 10000 feet, then the system shall "
        "deploy the oxygen masks automatically." in texts
    )


def test_corrupt_file_never_crashes():
    result = parse_workbook(FIXTURES_DIR / "corrupt_file.xlsx")

    assert result.candidates == []
    assert result.skipped == []
    assert len(result.issues) == 1
    assert result.issues[0].reason.startswith("failed_to_open_workbook")


def test_missing_file_never_crashes():
    result = parse_workbook(FIXTURES_DIR / "does_not_exist.xlsx")

    assert result.candidates == []
    assert len(result.issues) == 1
    assert result.issues[0].reason == "file_not_found"


def test_min_word_count_override():
    lenient = parse_workbook(FIXTURES_DIR / "messy_multi_sheet.xlsx", min_word_count=1)
    default = parse_workbook(FIXTURES_DIR / "messy_multi_sheet.xlsx")

    # Loosening the threshold can only ever surface more candidates, never fewer.
    assert len(lenient.candidates) >= len(default.candidates)


def test_parse_directory_handles_mixed_valid_and_corrupt_files():
    results = parse_directory(FIXTURES_DIR, pattern="*.xlsx")

    assert len(results) == 4  # 3 messy sheets + 1 corrupt file

    corrupt_result = results[str(FIXTURES_DIR / "corrupt_file.xlsx")]
    assert corrupt_result.issues and corrupt_result.issues[0].reason.startswith(
        "failed_to_open_workbook"
    )

    valid_result = results[str(FIXTURES_DIR / "messy_multi_sheet.xlsx")]
    assert len(valid_result.candidates) > 0


@pytest.mark.parametrize(
    "fixture_name",
    ["messy_multi_sheet.xlsx", "header_row_offset.xlsx", "edge_cases.xlsx"],
)
def test_every_candidate_has_full_traceability_metadata(fixture_name):
    result = parse_workbook(FIXTURES_DIR / fixture_name)
    assert result.candidates, "expected at least one candidate per messy fixture"

    for candidate in result.candidates:
        loc = candidate.location
        assert loc.file_path
        assert loc.sheet_name
        assert loc.row >= 1
        assert loc.column >= 1
        assert loc.column_letter
        assert loc.cell_reference == f"{loc.column_letter}{loc.row}"

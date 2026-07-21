"""Tests for src/data_prep/consolidate.py against the real reference
files in data/reference/. There's only one real dataset here (not
synthetic fixtures) — and it's messy enough on its own, e.g. the
header/data column swap in the 50-example file handled below.
"""

from data_prep.consolidate import EVAL_SIZE, FEWSHOT_SIZE, load_all_rows, split_dataset


def _fresh_split():
    rows = load_all_rows()
    return split_dataset(rows)


def test_split_sizes_match_spec():
    fewshot, eval_rows = _fresh_split()
    assert len(fewshot) == FEWSHOT_SIZE == 150
    assert len(eval_rows) == EVAL_SIZE == 60


def test_no_row_appears_in_both_sets():
    fewshot, eval_rows = _fresh_split()
    fewshot_ids = {row.id for row in fewshot}
    eval_ids = {row.id for row in eval_rows}

    assert fewshot_ids.isdisjoint(eval_ids)
    # every id is unique within its own set too, not just across sets
    assert len(fewshot_ids) == len(fewshot)
    assert len(eval_ids) == len(eval_rows)


def test_all_defect_types_appear_in_fewshot():
    all_rows = load_all_rows()
    fewshot, _ = split_dataset(all_rows)

    all_defect_types = {row.defect_type for row in all_rows}
    fewshot_defect_types = {row.defect_type for row in fewshot}
    assert fewshot_defect_types == all_defect_types


def test_eval_has_every_ears_pattern():
    all_rows = load_all_rows()
    _, eval_rows = split_dataset(all_rows)

    all_patterns = {row.ears_pattern for row in all_rows}
    eval_patterns = {row.ears_pattern for row in eval_rows}
    assert eval_patterns == all_patterns


def test_split_is_reproducible_with_fixed_seed():
    all_rows = load_all_rows()
    fewshot_a, eval_a = split_dataset(all_rows)
    fewshot_b, eval_b = split_dataset(all_rows)

    assert [row.id for row in fewshot_a] == [row.id for row in fewshot_b]
    assert [row.id for row in eval_a] == [row.id for row in eval_b]


def test_reads_expected_row_counts_per_source_file():
    all_rows = load_all_rows()
    assert len(all_rows) == 210

    by_prefix = {"EX50": 0, "AVIONICS": 0, "EMBEDDED": 0}
    for row in all_rows:
        by_prefix[row.id.split("-")[0]] += 1

    assert by_prefix == {"EX50": 50, "AVIONICS": 80, "EMBEDDED": 80}


def test_50_example_file_column_swap_is_corrected():
    """Regression guard for the header/data column swap in
    50_EARS_INCOSE_Requirement_Examples.xlsx: `bad_requirement` must be an
    actual sentence and `defect_type` must be the short category label —
    not the other way around, which naive header-based mapping would
    produce."""
    all_rows = load_all_rows()
    ex50_rows = [row for row in all_rows if row.id.startswith("EX50-")]
    assert ex50_rows

    for row in ex50_rows:
        assert len(row.bad_requirement.split()) >= 4, row
        assert len(row.defect_type.split()) <= 3, row
        assert row.python_detectable is None
        assert row.detection_method is None


def test_load_all_rows_prints_per_source_summary(capsys):
    load_all_rows()
    captured = capsys.readouterr()

    assert "50_EARS_INCOSE_Requirement_Examples.xlsx: 50 rows" in captured.out
    assert "Avionics_Embedded_Software_EARS_Compliance_Audit_Matrix.xlsx: 80 rows" in captured.out
    assert "Embedded_Software_EARS_INCOSE_Requirements_Matrix.xlsx: 80 rows" in captured.out
    assert "TOTAL: 210 rows" in captured.out

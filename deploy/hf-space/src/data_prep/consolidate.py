"""Consolidates the 3 example Excel files in data/reference/ into one
common schema, then splits the combined rows into a few-shot set and a
held-out evaluation set under data/golden/.

IMPORTANT — read this before trusting this dataset for anything:
This dataset (and the fewshot/eval split built from it) exists only to
(a) supply few-shot examples for LLM prompting and (b) sanity-check the
INCOSE rulebook's scoring against known-good/known-bad requirement pairs.
It is NOT the compliance authority for this project. The actual authority
is the structured INCOSE rulebook (JSON rule definitions + deterministic
Python scorer) built in Prompt 5, under src/rules/. That rulebook is
applied to every requirement the agent ever sees, including the ~400
real DRDO requirements that will never appear in these 210 rows. This
dataset can be incomplete, inconsistently labeled, or wrong in places
(see the notes on the 50-example file below) without that being a
compliance problem, because compliance never depends on this file.

Run directly:
    .venv\\Scripts\\python.exe -m data_prep.consolidate
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

RANDOM_SEED = 42
FEWSHOT_SIZE = 150
EVAL_SIZE = 60


@dataclass(frozen=True)
class UnifiedRow:
    id: str
    ears_pattern: str
    defect_type: str
    bad_requirement: str
    reason: str
    compliant_version: str
    python_detectable: bool | None
    detection_method: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _reference_dir() -> Path:
    try:
        from config import get_settings

        return _project_root() / get_settings()["ingestion"]["reference_dir"]
    except Exception:
        return _project_root() / "data" / "reference"


def _golden_dir() -> Path:
    try:
        from config import get_settings

        return _project_root() / get_settings()["ingestion"]["golden_dir"]
    except Exception:
        return _project_root() / "data" / "golden"


def _clean_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def _parse_python_detectable(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "true"}:
        return True
    if text in {"no", "n", "false"}:
        return False
    return None  # unrecognized value: don't guess, leave it null


# Any sentence beginning with one of these EARS keywords is classified by
# that keyword's pattern, per the EARS syntax templates themselves — this
# is a syntactic stand-in only, used solely because the 50-example source
# file provides no reliable pattern label of its own (see below). The
# real EARS classifier lives in src/rules/ and is what the pipeline
# actually uses at runtime.
_EARS_KEYWORD_PATTERNS = [
    ("while", "State-driven"),
    ("if", "Unwanted Behavior"),
    ("when", "Event-driven"),
    ("where", "Optional Feature"),
]


def _infer_ears_pattern(text: str) -> str:
    lowered = text.strip().lower()
    for keyword, pattern in _EARS_KEYWORD_PATTERNS:
        if lowered.startswith(keyword + " ") or lowered.startswith(keyword + ","):
            return pattern
    return "Ubiquitous"


def _read_50_examples(path: Path) -> list[UnifiedRow]:
    """50_EARS_INCOSE_Requirement_Examples.xlsx

    This file's own header row is actively misleading: it labels column B
    "Non-compliant EARS Requirement (<25 words)" and column C "Hidden
    INCOSE Violation", but the DATA underneath is swapped — column B
    actually holds a short category label (e.g. "Ambiguity", "Verifiable")
    and column C holds the real, long requirement sentence. Mapping by
    header text here would silently put category labels into
    `bad_requirement` and sentences into `defect_type`. We map by verified
    content position instead, and note it here so nobody "fixes" this
    back to header-based lookup later.

    The file also has no EARS-pattern or python-detectable/
    detection-method columns at all. `ears_pattern` is therefore backfilled
    with a lightweight keyword heuristic (see `_infer_ears_pattern`), and
    `python_detectable` / `detection_method` are left null rather than
    fabricated.
    """
    df = pd.read_excel(path, sheet_name=0, header=0)
    rows: list[UnifiedRow] = []
    for _, record in df.iterrows():
        raw_id = record.iloc[0]
        defect_type = _clean_str(record.iloc[1])       # mislabeled "requirement" column
        bad_requirement = _clean_str(record.iloc[2])    # mislabeled "violation" column
        reason = _clean_str(record.iloc[3])
        compliant_version = _clean_str(record.iloc[4])

        rows.append(UnifiedRow(
            id=f"EX50-{raw_id}",
            ears_pattern=_infer_ears_pattern(bad_requirement),
            defect_type=defect_type,
            bad_requirement=bad_requirement,
            reason=reason,
            compliant_version=compliant_version,
            python_detectable=None,
            detection_method=None,
        ))
    return rows


def _read_avionics_matrix(path: Path) -> list[UnifiedRow]:
    """Avionics_Embedded_Software_EARS_Compliance_Audit_Matrix.xlsx —
    headers here are trustworthy and map directly onto the unified
    schema."""
    df = pd.read_excel(path, sheet_name="Avionics EARS Matrix", header=0)
    rows: list[UnifiedRow] = []
    for _, record in df.iterrows():
        rows.append(UnifiedRow(
            id=f"AVIONICS-{record['Requirement ID']}",
            ears_pattern=_clean_str(record["EARS Template Archetype"]),
            defect_type=_clean_str(record["Core Structural Defect Type"]),
            bad_requirement=_clean_str(record["Non-Compliant Requirement (<25 Words)"]),
            reason=_clean_str(record["Detailed Sub-Ambiguity / Non-Compliance Reason"]),
            compliant_version=_clean_str(record["EARS-Compliant Engineering Version"]),
            python_detectable=_parse_python_detectable(record["Python Detectable?"]),
            detection_method=_clean_str(record["Python Automated Detection Methodology"]),
        ))
    return rows


def _read_embedded_matrix(path: Path) -> list[UnifiedRow]:
    """Embedded_Software_EARS_INCOSE_Requirements_Matrix.xlsx — headers
    here are trustworthy and map directly onto the unified schema."""
    df = pd.read_excel(path, sheet_name="Requirements Matrix", header=0)
    rows: list[UnifiedRow] = []
    for _, record in df.iterrows():
        rows.append(UnifiedRow(
            id=f"EMBEDDED-{record['Requirement ID']}",
            ears_pattern=_clean_str(record["EARS Pattern"]),
            defect_type=_clean_str(record["INCOSE Category Violated"]),
            bad_requirement=_clean_str(record["Non-Compliant Requirement (<25 words)"]),
            reason=_clean_str(record["Non-Compliance Reason (Subtle)"]),
            compliant_version=_clean_str(record["Compliant Version"]),
            python_detectable=_parse_python_detectable(record["Python Detectable?"]),
            detection_method=_clean_str(record["How Python Code Detects It"]),
        ))
    return rows


# (filename, reader) pairs, in a fixed order so the printed summary and
# any downstream reasoning about row order stays stable.
_SOURCE_FILES = [
    ("50_EARS_INCOSE_Requirement_Examples.xlsx", _read_50_examples),
    ("Avionics_Embedded_Software_EARS_Compliance_Audit_Matrix.xlsx", _read_avionics_matrix),
    ("Embedded_Software_EARS_INCOSE_Requirements_Matrix.xlsx", _read_embedded_matrix),
]


def load_all_rows(reference_dir: Path | None = None) -> list[UnifiedRow]:
    """Reads and normalizes all 3 reference files, printing a per-source
    row count summary."""
    reference_dir = reference_dir or _reference_dir()

    all_rows: list[UnifiedRow] = []
    counts: dict[str, int] = {}
    for filename, reader in _SOURCE_FILES:
        rows = reader(reference_dir / filename)
        counts[filename] = len(rows)
        all_rows.extend(rows)

    print("Source file row count summary:")
    for filename, count in counts.items():
        print(f"  {filename}: {count} rows")
    print(f"  TOTAL: {len(all_rows)} rows")

    return all_rows


def split_dataset(
    rows: list[UnifiedRow],
    *,
    fewshot_size: int = FEWSHOT_SIZE,
    eval_size: int = EVAL_SIZE,
    seed: int = RANDOM_SEED,
) -> tuple[list[UnifiedRow], list[UnifiedRow]]:
    """Splits `rows` into (fewshot, eval), stratified by ears_pattern and
    defect_type, with a fixed seed for reproducibility.

    Every row belongs to exactly one of the two returned lists, so no row
    can ever appear in both. The split guarantees:
      - every distinct defect_type has at least one row in fewshot
      - every distinct ears_pattern has at least one row in eval
    via a two-phase reserve-then-fill strategy: first reserve one row per
    defect_type into fewshot, then one row per ears_pattern (from what's
    left) into eval, then fill both sets up to their exact target sizes
    from the remaining shuffled pool.
    """
    if fewshot_size + eval_size != len(rows):
        raise ValueError(
            f"fewshot_size ({fewshot_size}) + eval_size ({eval_size}) must equal "
            f"the total row count ({len(rows)})"
        )

    rng = random.Random(seed)
    shuffled = list(rows)
    rng.shuffle(shuffled)

    # Phase 1: guarantee every defect_type is represented in fewshot.
    fewshot: list[UnifiedRow] = []
    seen_defect_types: set[str] = set()
    remaining: list[UnifiedRow] = []
    for row in shuffled:
        if row.defect_type not in seen_defect_types:
            seen_defect_types.add(row.defect_type)
            fewshot.append(row)
        else:
            remaining.append(row)

    if len(fewshot) > fewshot_size:
        raise ValueError(
            f"{len(fewshot)} distinct defect types each need a fewshot slot, "
            f"but fewshot_size is only {fewshot_size}"
        )

    # Phase 2: guarantee every ears_pattern is represented in eval, using
    # only rows not already reserved for fewshot above.
    eval_rows: list[UnifiedRow] = []
    seen_patterns: set[str] = set()
    still_remaining: list[UnifiedRow] = []
    for row in remaining:
        if row.ears_pattern not in seen_patterns:
            seen_patterns.add(row.ears_pattern)
            eval_rows.append(row)
        else:
            still_remaining.append(row)
    remaining = still_remaining

    if len(eval_rows) > eval_size:
        raise ValueError(
            f"{len(eval_rows)} distinct EARS patterns each need an eval slot, "
            f"but eval_size is only {eval_size}"
        )

    # Phase 3: fill both sets up to their exact target sizes.
    need_fewshot = fewshot_size - len(fewshot)
    need_eval = eval_size - len(eval_rows)
    assert need_fewshot + need_eval == len(remaining), "reservation bookkeeping bug"

    fewshot.extend(remaining[:need_fewshot])
    eval_rows.extend(remaining[need_fewshot:need_fewshot + need_eval])

    return fewshot, eval_rows


def _write_json(path: Path, rows: list[UnifiedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump([row.to_dict() for row in rows], f, indent=2, ensure_ascii=False)


def main() -> None:
    all_rows = load_all_rows()
    fewshot, eval_rows = split_dataset(all_rows)

    golden_dir = _golden_dir()
    _write_json(golden_dir / "fewshot.json", fewshot)
    _write_json(golden_dir / "eval.json", eval_rows)

    print(f"Wrote {len(fewshot)} rows to {golden_dir / 'fewshot.json'}")
    print(f"Wrote {len(eval_rows)} rows to {golden_dir / 'eval.json'}")


if __name__ == "__main__":
    main()

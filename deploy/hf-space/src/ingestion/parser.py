"""Parses messy, real-world requirement spreadsheets into candidate
requirement text with full source metadata for traceability.

Design decisions, since this will meet spreadsheets no fixture ever saw:

- No assumption about where headers live. Rather than locate a header row
  and read fixed columns beneath it, every resolved cell in every sheet is
  independently tested against a junk/note-row heuristic (minimum word
  count + presence of a verb). This makes "inconsistent header positions"
  a non-issue by construction: header cells are filtered out because they
  are short and verb-free, wherever they sit.
- Merged cells are resolved to their anchor (top-left) cell's value before
  the heuristic runs, and every non-anchor cell in a merged range is
  skipped as a duplicate so one merged title doesn't yield N candidates.
- Nothing here raises. Failures are caught at the file, sheet, and cell
  level and turned into a logged, reasoned skip/error entry in the
  returned ParseResult instead of aborting the run.
- The verb check is a small curated keyword/stem list, not a POS tagger:
  there is no bundled offline language model yet, and the brief calls for
  a simple heuristic first. Swap `_contains_verb` for spaCy-based POS
  tagging later without touching the rest of the module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)

DEFAULT_MIN_WORD_COUNT = 4

# Excel formula-error sentinel strings that show up as literal cell text
# when a workbook is saved with `data_only=True` computed values missing.
_FORMULA_ERROR_VALUES = {
    "#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#SPILL!",
}

# Modal/auxiliary verbs: on their own these are a strong signal of a
# requirement-shaped sentence ("shall", "must", "is", ...).
_MODAL_VERBS = {
    "shall", "should", "must", "will", "would", "may", "might", "can", "could",
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "does", "do", "did",
}

# Common requirement/engineering action verbs (base forms). `_contains_verb`
# also checks simple -s/-es/-ed/-ing stems against this set, so "monitors",
# "monitored", and "monitoring" all match "monitor".
_ACTION_VERB_STEMS = {
    "provide", "support", "enable", "disable", "allow", "prevent", "perform",
    "control", "monitor", "detect", "display", "log", "report", "calculate",
    "compute", "validate", "verify", "maintain", "ensure", "generate", "store",
    "read", "write", "send", "receive", "transmit", "activate", "initiate",
    "trigger", "capture", "sample", "filter", "actuate", "command", "output",
    "input", "close", "open", "boot", "initialize", "install", "download",
    "upload", "execute", "process", "switch", "lock", "unlock", "reset",
    "load", "save", "compare", "check", "confirm", "indicate", "notify",
    "alert", "warn", "limit", "restrict", "apply", "update", "configure",
    "determine", "identify", "respond", "react", "operate", "function",
    "include", "exclude", "contain", "require", "need", "use", "utilize",
    "implement", "deploy", "manage", "handle", "produce", "create", "remove",
    "delete", "insert", "retrieve", "fetch", "sync", "synchronize",
    "communicate", "interface", "connect", "disconnect", "power", "shut",
    "start", "stop", "begin", "end", "terminate", "abort", "cancel", "resume",
    "pause", "continue", "wait", "delay", "schedule", "invoke", "call",
    "return", "yield", "fill", "engage", "disengage", "arm", "disarm",
    "launch", "land", "climb", "descend", "turn", "hold", "fly", "navigate",
    "calibrate", "test", "measure", "record", "annunciate", "shutdown",
    "reboot", "authenticate", "encrypt", "decrypt", "compress", "decompress",
}


@dataclass(frozen=True)
class SourceLocation:
    """Full source metadata for one resolved spreadsheet cell."""

    file_path: str
    sheet_name: str
    row: int
    column: int
    column_letter: str
    is_merged: bool = False
    merge_anchor: tuple[int, int] | None = None

    @property
    def cell_reference(self) -> str:
        return f"{self.column_letter}{self.row}"


@dataclass(frozen=True)
class CandidateRequirement:
    """A cell whose text cleared the junk/note-row heuristic."""

    text: str
    raw_value: Any
    location: SourceLocation


@dataclass(frozen=True)
class SkippedCell:
    """A cell that was deliberately not extracted, with a clear reason."""

    location: SourceLocation
    raw_value: Any
    reason: str


@dataclass(frozen=True)
class ParseIssue:
    """A file- or sheet-level failure that did not stop the overall run."""

    file_path: str
    sheet_name: str | None
    reason: str


@dataclass
class ParseResult:
    candidates: list[CandidateRequirement] = field(default_factory=list)
    skipped: list[SkippedCell] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


def _default_min_word_count() -> int:
    try:
        from config import get_settings

        return int(get_settings()["ingestion"]["min_word_count"])
    except Exception:
        return DEFAULT_MIN_WORD_COUNT


def _normalize_cell_text(value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = str(value)
    elif isinstance(value, (datetime, date, time)):
        text = value.isoformat()
    else:
        text = str(value)
    return " ".join(text.split())


def _is_formula_error(text: str) -> bool:
    return text.strip().upper() in _FORMULA_ERROR_VALUES


def _word_count(text: str) -> int:
    return len(text.split())


def _candidate_stems(word: str) -> list[str]:
    stems = [word]
    if word.endswith("ing") and len(word) > 4:
        stems.append(word[:-3])
    if word.endswith("ed") and len(word) > 3:
        stems.append(word[:-2])
        stems.append(word[:-1])
    if word.endswith("es") and len(word) > 3:
        stems.append(word[:-2])
    if word.endswith("s") and len(word) > 2:
        stems.append(word[:-1])
    return stems


def _contains_verb(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z]+", text.lower())
    for token in tokens:
        if token in _MODAL_VERBS:
            return True
        if any(stem in _ACTION_VERB_STEMS for stem in _candidate_stems(token)):
            return True
    return False


def _build_merge_anchor_map(ws: Worksheet) -> dict[tuple[int, int], tuple[int, int]]:
    """Maps every (row, col) inside a merged range to that range's
    top-left anchor coordinate. Anchors map to themselves."""
    anchor_of: dict[tuple[int, int], tuple[int, int]] = {}
    for merged_range in ws.merged_cells.ranges:
        anchor = (merged_range.min_row, merged_range.min_col)
        for row_idx in range(merged_range.min_row, merged_range.max_row + 1):
            for col_idx in range(merged_range.min_col, merged_range.max_col + 1):
                anchor_of[(row_idx, col_idx)] = anchor
    return anchor_of


def _classify_cell(
    raw_value: Any,
    location: SourceLocation,
    min_word_count: int,
) -> tuple[CandidateRequirement | None, str | None]:
    """Returns (candidate, None) on success, or (None, skip_reason)."""
    if raw_value is None:
        return None, "empty_cell"

    text = _normalize_cell_text(raw_value)
    if text == "":
        return None, "empty_after_normalization"

    if _is_formula_error(text):
        return None, "formula_error_value"

    word_count = _word_count(text)
    if word_count < min_word_count:
        return None, f"too_few_words:{word_count}<{min_word_count}"

    if not _contains_verb(text):
        return None, "no_verb_detected"

    return CandidateRequirement(text=text, raw_value=raw_value, location=location), None


def _parse_sheet(
    ws: Worksheet,
    file_path: str,
    sheet_name: str,
    min_word_count: int,
    result: ParseResult,
) -> None:
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    if max_row == 0 or max_col == 0:
        logger.info("Sheet %r in %s is empty; nothing to parse.", sheet_name, file_path)
        return

    anchor_of = _build_merge_anchor_map(ws)

    for row_idx in range(1, max_row + 1):
        for col_idx in range(1, max_col + 1):
            coord = (row_idx, col_idx)
            column_letter = get_column_letter(col_idx)

            try:
                anchor = anchor_of.get(coord, coord)
                is_merged = coord in anchor_of

                if anchor != coord:
                    # Non-anchor cell of a merged range: the anchor cell
                    # already carries (and will yield) the real value.
                    location = SourceLocation(
                        file_path, sheet_name, row_idx, col_idx, column_letter,
                        is_merged=True, merge_anchor=anchor,
                    )
                    result.skipped.append(SkippedCell(location, None, "merged_cell_duplicate"))
                    continue

                location = SourceLocation(
                    file_path, sheet_name, row_idx, col_idx, column_letter,
                    is_merged=is_merged, merge_anchor=anchor if is_merged else None,
                )
                raw_value = ws.cell(row=row_idx, column=col_idx).value

                candidate, skip_reason = _classify_cell(raw_value, location, min_word_count)
                if candidate is not None:
                    result.candidates.append(candidate)
                else:
                    result.skipped.append(SkippedCell(location, raw_value, skip_reason or "unknown"))

            except Exception as exc:  # noqa: BLE001 - a single bad cell must never abort the run
                logger.warning(
                    "Failed to process cell %s%s in sheet %r of %s: %r",
                    column_letter, row_idx, sheet_name, file_path, exc,
                )
                location = SourceLocation(file_path, sheet_name, row_idx, col_idx, column_letter)
                result.skipped.append(SkippedCell(location, None, f"cell_processing_error: {exc!r}"))


def parse_workbook(path: str | Path, *, min_word_count: int | None = None) -> ParseResult:
    """Parses one Excel workbook into a ParseResult.

    Never raises: file-open failures, per-sheet failures, and per-cell
    failures are all caught and recorded (with a reason) instead of
    propagating, so one malformed spreadsheet in a batch cannot abort the
    rest of the run.
    """
    path = Path(path)
    result = ParseResult()
    effective_min_words = min_word_count if min_word_count is not None else _default_min_word_count()

    if not path.exists():
        logger.error("Cannot parse %s: file does not exist.", path)
        result.issues.append(ParseIssue(str(path), None, "file_not_found"))
        return result

    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:  # noqa: BLE001 - any bad/corrupt/unsupported file must not crash the run
        logger.error("Failed to open workbook %s: %r", path, exc)
        result.issues.append(ParseIssue(str(path), None, f"failed_to_open_workbook: {exc!r}"))
        return result

    for sheet_name in workbook.sheetnames:
        try:
            _parse_sheet(workbook[sheet_name], str(path), sheet_name, effective_min_words, result)
        except Exception as exc:  # noqa: BLE001 - one bad sheet must not stop the others
            logger.error("Failed to parse sheet %r in %s: %r", sheet_name, path, exc)
            result.issues.append(ParseIssue(str(path), sheet_name, f"failed_to_parse_sheet: {exc!r}"))
            continue

    logger.info(
        "Parsed %s: %d candidate(s), %d skipped cell(s), %d issue(s).",
        path, len(result.candidates), len(result.skipped), len(result.issues),
    )
    return result


def parse_directory(directory: str | Path, *, pattern: str = "*.xlsx") -> dict[str, ParseResult]:
    """Parses every workbook matching `pattern` in `directory`.

    A failure on one file is captured in that file's own ParseResult
    (via parse_workbook's guarantees) and does not affect the others.
    """
    directory = Path(directory)
    results: dict[str, ParseResult] = {}
    if not directory.exists():
        logger.error("Cannot parse directory %s: it does not exist.", directory)
        return results

    for file_path in sorted(directory.glob(pattern)):
        results[str(file_path)] = parse_workbook(file_path)

    return results

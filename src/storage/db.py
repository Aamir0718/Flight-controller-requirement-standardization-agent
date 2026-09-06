"""SQLite storage for pipeline run traces, plus an Excel export of a
completed run for human review.

Zero setup, zero network: the database is a single local file (path from
config/settings.yaml's storage.sqlite_path, never hardcoded) created
automatically -- via stdlib `sqlite3.connect()` + `CREATE TABLE IF NOT
EXISTS` -- the first time this module is used. No server process, no
migration tool, nothing to install beyond what's already in
requirements.txt (sqlite3 is part of the Python standard library).

Schema
------
runs            One row per uploaded file processed through the pipeline:
                file metadata (name, path, size, sha256) and when it ran.
requirements    One row per requirement processed within a run: the full
                trace src/pipeline/graph.py produces for it (original
                text, source location, rule-engine flags, all 3 scored
                candidates, the recommendation, vague-term suggestions,
                needs_human_review) -- stored as-is, keyed to its run.

Nested structures (source_location, rule_flags, candidates,
vague_term_suggestions) are stored as JSON text columns; SQLite has no
native JSON type, and this project has no need to query inside them from
SQL, so this is the simplest correct choice rather than normalizing them
into more tables.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import get_settings

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    file_path TEXT,
    file_size_bytes INTEGER,
    sha256 TEXT,
    uploaded_at TEXT NOT NULL,
    requirement_count INTEGER NOT NULL DEFAULT 0,
    total_requirements INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    consistency_analyzed_at TEXT,
    consistency_last_error TEXT
);

CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sequence_in_run INTEGER NOT NULL,
    original_text TEXT NOT NULL,
    source_location_json TEXT NOT NULL,
    ears_pattern_json TEXT NOT NULL,
    rule_flags_json TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    recommended_index INTEGER NOT NULL,
    recommended_text TEXT NOT NULL,
    recommended_score REAL NOT NULL,
    vague_term_suggestions_json TEXT NOT NULL,
    compliance_threshold REAL NOT NULL,
    needs_human_review INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'analyzed',
    violations_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    accurate_score_status TEXT NOT NULL DEFAULT 'not_computed',
    accurate_score REAL,
    accurate_violations_json TEXT NOT NULL DEFAULT '[]',
    accurate_score_error_message TEXT
);

CREATE TABLE IF NOT EXISTS requirement_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    req_id_1 INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    req_id_2 INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, req_id_1, req_id_2)
);

CREATE INDEX IF NOT EXISTS idx_requirements_run_id ON requirements(run_id);
CREATE INDEX IF NOT EXISTS idx_requirement_relationships_run_id ON requirement_relationships(run_id);
CREATE INDEX IF NOT EXISTS idx_requirement_relationships_req_ids ON requirement_relationships(req_id_1, req_id_2);
"""


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolves the SQLite file path: an explicit override, or
    config/settings.yaml's storage.sqlite_path (relative paths are
    resolved against the repo root, matching src/config.py's convention).
    """
    if db_path is not None:
        return Path(db_path)
    configured = get_settings().get("storage", {}).get("sqlite_path", "data/app.db")
    configured_path = Path(configured)
    return configured_path if configured_path.is_absolute() else _REPO_ROOT / configured_path


# Columns added to `requirements` after its original CREATE TABLE shipped.
# `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a
# database file created before this list existed needs these added
# explicitly -- see _migrate_schema() below. (column, DDL type+default)
_REQUIREMENTS_MIGRATIONS = [
    ("status", "TEXT NOT NULL DEFAULT 'analyzed'"),
    ("violations_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("error_message", "TEXT"),
    # On-demand "accurate" (42-rule) scoring -- see src/rules/incose_ai_scorer.py.
    # Every existing row predates this feature, so 'not_computed' is the
    # correct default for all of them, same as a freshly-inserted row.
    ("accurate_score_status", "TEXT NOT NULL DEFAULT 'not_computed'"),
    ("accurate_score", "REAL"),
    ("accurate_violations_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("accurate_score_error_message", "TEXT"),
]

# Columns added to `runs` after its original CREATE TABLE shipped -- lets a
# human (and the frontend) tell "consistency analysis was never run for
# this run" apart from "it ran and genuinely found 0 relationships", which
# look identical if all you can see is an empty relationships table. See
# src/ui/api.py's _run_consistency_analysis()/record_consistency_analysis_outcome().
_RUNS_MIGRATIONS = [
    ("consistency_analyzed_at", "TEXT"),
    ("consistency_last_error", "TEXT"),
]


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Adds any column in _REQUIREMENTS_MIGRATIONS/_RUNS_MIGRATIONS that an
    existing database file predates. A fresh database already has every
    column via _SCHEMA's CREATE TABLE, so this is a no-op for it --
    existing() just comes back non-empty and every ALTER TABLE is
    skipped."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(requirements)").fetchall()}
    for column, ddl in _REQUIREMENTS_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE requirements ADD COLUMN {column} {ddl}")

    existing_run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for column, ddl in _RUNS_MIGRATIONS:
        if column not in existing_run_columns:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")

    # ADD COLUMN's DEFAULT 'analyzed' is right for a row that genuinely
    # never reached the LLM (candidates=[] and recommended_index=-1 --
    # which is also exactly what a pre-this-change RejectNonEars row looks
    # like, so "analyzed" is still the correct read for those). But a
    # pre-existing row that DID go through the old one-shot pipeline and
    # got real LLM candidates would otherwise show as "analyzed" (not yet
    # generated) when it's actually already done -- backfill those.
    # Unconditional (not just right after adding the column) and cheap:
    # it only ever touches rows currently mismarked this way, so it's a
    # no-op once the data's correct, and self-heals the live database if
    # it was ever backfilled wrong by an earlier version of this function.
    conn.execute(
        "UPDATE requirements SET status = 'generated' "
        "WHERE status = 'analyzed' AND (recommended_index >= 0 OR candidates_json != '[]')"
    )
    conn.commit()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Opens the SQLite database, creating the file and schema if this is
    the first run. No server, no network, no external setup step -- the
    parent directory and file are created on demand.
    """
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate_schema(conn)
    return conn


@contextmanager
def open_db(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """``with open_db() as conn:`` -- like connect(), but closes the
    connection on exit (sqlite3.Connection's own context-manager protocol
    only commits/rolls back, it does not close)."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_metadata(file_path: str | Path | None) -> tuple[int | None, str | None]:
    """(size in bytes, sha256 hex digest) for a real file on disk, or
    (None, None) if file_path is falsy or doesn't exist -- e.g. a
    directly-typed requirement with no backing upload."""
    if not file_path:
        return None, None
    path = Path(file_path)
    if not path.is_file():
        return None, None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def create_run(
    conn: sqlite3.Connection,
    file_name: str,
    file_path: str | Path | None = None,
    file_size_bytes: int | None = None,
    sha256: str | None = None,
) -> int:
    """Records one uploaded file's metadata as a new run. Size/sha256 are
    computed automatically from ``file_path`` when it points at a real
    file and aren't given explicitly.
    """
    if file_size_bytes is None or sha256 is None:
        computed_size, computed_sha256 = _file_metadata(file_path)
        if file_size_bytes is None:
            file_size_bytes = computed_size
        if sha256 is None:
            sha256 = computed_sha256

    cursor = conn.execute(
        "INSERT INTO runs (file_name, file_path, file_size_bytes, sha256, uploaded_at, "
        "requirement_count, status) VALUES (?, ?, ?, ?, ?, 0, 'pending')",
        (file_name, str(file_path) if file_path else None, file_size_bytes, sha256, _utcnow()),
    )
    conn.commit()
    return cursor.lastrowid


# Valid run.status values -- a run moves through these strictly in order,
# never backwards, and 'completed'/'failed' are terminal.
RUN_STATUSES = ("pending", "processing", "completed", "failed")


def update_run_status(
    conn: sqlite3.Connection, run_id: int, status: str, error_message: str | None = None
) -> None:
    """Updates a run's status (see RUN_STATUSES) -- used by the background
    task in src/ui/api.py to report progress as it works through a run,
    and to record why a run failed when it does.
    """
    if status not in RUN_STATUSES:
        raise ValueError(f"Unknown run status {status!r}; expected one of {RUN_STATUSES}")
    conn.execute(
        "UPDATE runs SET status = ?, error_message = ? WHERE id = ?", (status, error_message, run_id)
    )
    conn.commit()


def record_consistency_analysis_outcome(
    conn: sqlite3.Connection, run_id: int, error: str | None
) -> None:
    """Records that a consistency-analysis attempt (src/ui/api.py's
    _run_consistency_analysis()) just happened for this run, successfully
    (``error`` is None) or not (``error`` is the failure reason). Sets
    consistency_analyzed_at unconditionally -- even a failed attempt "was
    attempted" -- so GET /runs/{run_id}/consistency can tell a human
    "analysis has never run for this run" apart from "it ran and found
    nothing" or "it ran and failed", which otherwise all look identical
    (an empty requirement_relationships table)."""
    conn.execute(
        "UPDATE runs SET consistency_analyzed_at = ?, consistency_last_error = ? WHERE id = ?",
        (_utcnow(), error, run_id),
    )
    conn.commit()


def set_run_total_requirements(conn: sqlite3.Connection, run_id: int, total: int) -> None:
    """Records how many requirements a run will process, known once the
    upload has been parsed but before generation starts -- lets a status
    poll show "N of TOTAL processed" (requirement_count already increments
    per-requirement as save_requirement() is called)."""
    conn.execute("UPDATE runs SET total_requirements = ? WHERE id = ?", (total, run_id))
    conn.commit()


def save_requirement(conn: sqlite3.Connection, run_id: int, sequence_in_run: int, result: dict) -> int:
    """Persists one requirement's trace -- either analyze_requirement()'s
    deterministic-only dict, generate_requirement()'s LLM-phase dict, or
    (for tests/test_graph_integration.py and any other caller still using
    the old one-shot pipeline) run_requirement()/run_workbook()'s combined
    dict. All three shapes share original_text, source_location,
    ears_pattern, rule_flags, candidates, recommended_index/text/score,
    vague_term_suggestions, compliance_threshold, needs_human_review;
    "status" and "violations" are optional (default "generated" and []
    respectively) since the old combined shape has neither.
    """
    cursor = conn.execute(
        """
        INSERT INTO requirements (
            run_id, sequence_in_run, original_text, source_location_json,
            ears_pattern_json, rule_flags_json, candidates_json,
            recommended_index, recommended_text, recommended_score,
            vague_term_suggestions_json, compliance_threshold,
            needs_human_review, created_at, status, violations_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            sequence_in_run,
            result["original_text"],
            json.dumps(result["source_location"]),
            json.dumps(result["ears_pattern"]),
            json.dumps(result["rule_flags"]),
            json.dumps(result["candidates"]),
            result["recommended_index"],
            result["recommended_text"],
            result["recommended_score"],
            json.dumps(result["vague_term_suggestions"]),
            result["compliance_threshold"],
            1 if result["needs_human_review"] else 0,
            _utcnow(),
            result.get("status", "generated"),
            json.dumps(result.get("violations", [])),
        ),
    )
    conn.execute("UPDATE runs SET requirement_count = requirement_count + 1 WHERE id = ?", (run_id,))
    conn.commit()
    return cursor.lastrowid


# Valid requirements.status values. A row starts "analyzed" (deterministic
# phase only, right after upload); a human moves it to "generating" ->
# "generated"/"failed" by clicking Generate, or straight to "edited" by
# typing a replacement themselves. Never moves backwards automatically.
REQUIREMENT_STATUSES = ("analyzed", "generating", "generated", "edited", "failed")


def update_requirement_status(
    conn: sqlite3.Connection, requirement_id: int, status: str, error_message: str | None = None
) -> None:
    """Updates just a requirement's status (and optionally an error code) --
    used to mark a row "generating" right before its LLM call starts, or
    "failed" if that call raises, without touching any of its other
    columns."""
    if status not in REQUIREMENT_STATUSES:
        raise ValueError(f"Unknown requirement status {status!r}; expected one of {REQUIREMENT_STATUSES}")
    conn.execute(
        "UPDATE requirements SET status = ?, error_message = ? WHERE id = ?",
        (status, error_message, requirement_id),
    )
    conn.commit()


def apply_generation_result(conn: sqlite3.Connection, requirement_id: int, result: dict) -> None:
    """Overwrites one requirement row with generate_requirement()'s output
    after a human clicked Generate for it: candidates, recommendation,
    vague-term suggestions, needs_human_review, and status="generated".
    original_text/source_location/rule_flags/ears_pattern's *structural*
    fields are left as analyze_requirement() wrote them (ears_pattern
    itself IS overwritten -- generate_requirement() may have rewritten its
    "reason" to report a failed post-generation re-check)."""
    conn.execute(
        """
        UPDATE requirements SET
            ears_pattern_json = ?, candidates_json = ?, recommended_index = ?,
            recommended_text = ?, recommended_score = ?,
            vague_term_suggestions_json = ?, needs_human_review = ?,
            status = 'generated', error_message = NULL
        WHERE id = ?
        """,
        (
            json.dumps(result["ears_pattern"]),
            json.dumps(result["candidates"]),
            result["recommended_index"],
            result["recommended_text"],
            result["recommended_score"],
            json.dumps(result["vague_term_suggestions"]),
            1 if result["needs_human_review"] else 0,
            requirement_id,
        ),
    )
    conn.commit()


def apply_manual_edit(conn: sqlite3.Connection, requirement_id: int, edited_text: str) -> dict[str, Any]:
    """A human typed a replacement requirement themselves (the Edit button,
    no LLM involved). Re-scores the new text deterministically (full
    INCOSE rulebook, same scorer used everywhere else) and stores it as
    the recommendation: recommended_index=-1 signals "not one of the AI
    candidates", needs_human_review=False since a human just wrote/approved
    this text directly, status="edited". Returns the updated row.
    """
    from rules.incose_scorer import score_requirement

    score_result = score_requirement(edited_text)
    conn.execute(
        """
        UPDATE requirements SET
            recommended_text = ?, recommended_index = -1, recommended_score = ?,
            needs_human_review = 0, status = 'edited', error_message = NULL
        WHERE id = ?
        """,
        (edited_text, score_result.score, requirement_id),
    )
    conn.commit()
    return get_requirement(conn, requirement_id)


# Valid requirements.accurate_score_status values -- a row starts
# "not_computed" (the default 28-rule score is all it has); a human's
# "Check Accurate Score" click moves it to "computing" while the LLM call
# for the 14 non-automatable rules is in flight, then "done" or "failed".
ACCURATE_SCORE_STATUSES = ("not_computed", "computing", "done", "failed")


def start_accurate_score(conn: sqlite3.Connection, requirement_id: int) -> None:
    """Marks a row 'computing' right before its accurate-score LLM call
    starts, mirroring update_requirement_status()'s 'generating' marker --
    same reason: a client polling GET /runs/{run_id}/requirements sees live
    per-row progress with no separate console/stage machinery."""
    conn.execute(
        "UPDATE requirements SET accurate_score_status = 'computing', "
        "accurate_score_error_message = NULL WHERE id = ?",
        (requirement_id,),
    )
    conn.commit()


def save_accurate_score(
    conn: sqlite3.Connection, requirement_id: int, score: float, violations: list[dict]
) -> dict[str, Any]:
    """Stores a completed src/rules/incose_ai_scorer.score_accurate() result
    (the combined 42-rule score and every failed rule's id/title/category/
    reasons) for one requirement. Returns the updated row."""
    conn.execute(
        """
        UPDATE requirements SET
            accurate_score_status = 'done', accurate_score = ?,
            accurate_violations_json = ?, accurate_score_error_message = NULL
        WHERE id = ?
        """,
        (score, json.dumps(violations), requirement_id),
    )
    conn.commit()
    return get_requirement(conn, requirement_id)


def fail_accurate_score(conn: sqlite3.Connection, requirement_id: int, error_message: str) -> None:
    """Records that an accurate-score LLM call failed (endpoint unreachable,
    bad response, etc.) -- same friendly-error-code convention as
    update_requirement_status()'s 'failed' status for Generate."""
    conn.execute(
        "UPDATE requirements SET accurate_score_status = 'failed', "
        "accurate_score_error_message = ? WHERE id = ?",
        (error_message, requirement_id),
    )
    conn.commit()


def save_pipeline_run(
    conn: sqlite3.Connection,
    file_name: str,
    results: list[dict],
    file_path: str | Path | None = None,
) -> int:
    """Convenience wrapper: records one run and every requirement result
    from a single pipeline pass (e.g. src/pipeline/graph.py's
    run_workbook() output) in sequence order. Returns the new run_id.
    """
    run_id = create_run(conn, file_name=file_name, file_path=file_path)
    set_run_total_requirements(conn, run_id, len(results))
    for i, result in enumerate(results):
        save_requirement(conn, run_id, i, result)
    update_run_status(conn, run_id, "completed")
    return run_id


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _row_to_requirement(row: sqlite3.Row) -> dict[str, Any]:
    columns = row.keys()
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "sequence_in_run": row["sequence_in_run"],
        "original_text": row["original_text"],
        "source_location": json.loads(row["source_location_json"]),
        "ears_pattern": json.loads(row["ears_pattern_json"]),
        "rule_flags": json.loads(row["rule_flags_json"]),
        "candidates": json.loads(row["candidates_json"]),
        "recommended_index": row["recommended_index"],
        "recommended_text": row["recommended_text"],
        "recommended_score": row["recommended_score"],
        "vague_term_suggestions": json.loads(row["vague_term_suggestions_json"]),
        "compliance_threshold": row["compliance_threshold"],
        "needs_human_review": bool(row["needs_human_review"]),
        "created_at": row["created_at"],
        # These three columns only exist on a migrated/fresh database (see
        # _migrate_schema) -- guarded so a row read mid-migration, or by a
        # connection that skipped it, doesn't KeyError.
        "status": row["status"] if "status" in columns else "generated",
        "violations": json.loads(row["violations_json"]) if "violations_json" in columns else [],
        "error_message": row["error_message"] if "error_message" in columns else None,
        # On-demand 42-rule score (src/rules/incose_ai_scorer.py) -- absent
        # ("not_computed"/None/[]) until a human clicks "Check Accurate
        # Score" for this row. Same migrated-column guard as above.
        "accurate_score_status": row["accurate_score_status"] if "accurate_score_status" in columns else "not_computed",
        "accurate_score": row["accurate_score"] if "accurate_score" in columns else None,
        "accurate_violations": json.loads(row["accurate_violations_json"]) if "accurate_violations_json" in columns else [],
        "accurate_score_error_message": row["accurate_score_error_message"] if "accurate_score_error_message" in columns else None,
    }


def get_requirements_for_run(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM requirements WHERE run_id = ? ORDER BY sequence_in_run", (run_id,)
    ).fetchall()
    return [_row_to_requirement(row) for row in rows]


def get_requirement(conn: sqlite3.Connection, requirement_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
    return _row_to_requirement(row) if row else None


# ---------------------------------------------------------------------------
# Consistency Analysis
# ---------------------------------------------------------------------------


def save_requirement_relationship(
    conn: sqlite3.Connection,
    run_id: int,
    req_id_1: int,
    req_id_2: int,
    relationship_type: str,
    similarity_score: float,
    confidence: float,
    reason: str | None = None,
) -> int:
    """Saves a relationship between two requirements."""
    cursor = conn.execute(
        """
        INSERT OR REPLACE INTO requirement_relationships 
        (run_id, req_id_1, req_id_2, relationship_type, similarity_score, confidence, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, req_id_1, req_id_2, relationship_type, similarity_score, confidence, reason, _utcnow()),
    )
    conn.commit()
    return cursor.lastrowid


def get_requirement_relationships(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """Retrieves all relationships for a run."""
    rows = conn.execute(
        "SELECT * FROM requirement_relationships WHERE run_id = ? ORDER BY similarity_score DESC",
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_consistency_summary(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    """Retrieves a summary of consistency analysis for a run."""
    rows = conn.execute(
        "SELECT relationship_type, COUNT(*) as count FROM requirement_relationships WHERE run_id = ? GROUP BY relationship_type",
        (run_id,),
    ).fetchall()
    
    summary = {"duplicate": 0, "similar": 0, "contradiction": 0, "independent": 0}
    for row in rows:
        summary[row["relationship_type"]] = row["count"]
    
    # Calculate independent pairs
    run = get_run(conn, run_id)
    if run:
        total_reqs = run.get("total_requirements", 0)
        total_pairs = total_reqs * (total_reqs - 1) // 2
        total_detected = sum(summary.values())
        summary["independent"] = max(0, total_pairs - total_detected)
    
    return summary


def clear_requirement_relationships(conn: sqlite3.Connection, run_id: int) -> None:
    """Clears all relationships for a run (useful for re-analysis)."""
    conn.execute("DELETE FROM requirement_relationships WHERE run_id = ?", (run_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

_HEADER_FILL = "4472C4"
_HEADER_FONT_COLOR = "FFFFFF"
_NEEDS_REVIEW_FILL = "FFC7CE"   # light red -- matches Excel's built-in "Bad" style
_NEEDS_REVIEW_FONT = "9C0006"
_OK_FILL = "C6EFCE"             # light green -- matches Excel's built-in "Good" style
_OK_FONT = "006100"

_COLUMN_WIDTHS = [4, 24, 44, 16, 12, 44, 18, 20, 40, 40, 12, 44, 44]
_HEADERS = [
    "#", "Source Location", "Original Requirement", "EARS Pattern", "Status",
    "Recommended Requirement", "Compliance Score (28 automatable rules)",
    "Accurate Score (42 rules, incl. AI-judged)",
    "Alternate 1", "Alternate 2",
    "Needs Review", "Suggestions", "Violations",
]
_STATUS_LABELS = {
    "analyzed": "Not Generated",
    "generating": "Generating...",
    "generated": "AI Generated",
    "edited": "Manually Edited",
    "failed": "Generation Failed",
}


def _format_source_location(location: dict[str, Any]) -> str:
    if location.get("sheet_name") and location.get("column_letter") and location.get("row"):
        return f"{location['sheet_name']}!{location['column_letter']}{location['row']}"
    if location.get("source") == "inline":
        return "(direct input)"
    return json.dumps(location)


def _format_candidate(candidate: dict[str, Any] | None) -> str:
    if candidate is None:
        return ""
    return f"{candidate['rewritten_text']} (score: {candidate['score']:.1f})"


def _format_suggestions(suggestions: list[dict[str, str]]) -> str:
    if not suggestions:
        return "(none)"
    return "; ".join(f"{s['term']}: {s['suggestion']}" for s in suggestions)


def _format_violations(violations: list[dict[str, Any]]) -> str:
    if not violations:
        return "(none)"
    return "; ".join(
        f"{v['id']} ({v['title']}): {' '.join(v['reasons'])}" for v in violations
    )


def _format_accurate_score(status: str, score: float | None) -> str:
    if status == "done" and score is not None:
        return f"{score:.1f}"
    if status == "computing":
        return "(computing...)"
    if status == "failed":
        return "(check failed -- see app)"
    return "Not checked (click \"Check Accurate Score\" in the app)"


def export_run_to_excel(conn: sqlite3.Connection, run_id: int, output_path: str | Path) -> Path:
    """Exports a run to a formatted .xlsx for human review, at whatever
    point it's called -- right after upload with every row still
    "analyzed" (deterministic-only, nothing generated yet) works exactly
    as well as after some or all rows have been Generated or Edited. Each
    row's Status column says which of those three it's in; color follows
    needs_human_review (red = still needs attention, green = ready) which
    is True for every "analyzed" row (nothing decided yet), then becomes
    whatever generate_requirement()/apply_manual_edit() set it to once a
    human acts on that row -- so a row genuinely turns green only once
    it's actually been resolved, not just because it was included in a run.
    Also includes a consistency analysis sheet if relationships exist.

    Raises ValueError if ``run_id`` doesn't exist.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    run = get_run(conn, run_id)
    if run is None:
        raise ValueError(f"No run found with id {run_id}")
    requirements = get_requirements_for_run(conn, run_id)

    workbook = Workbook()
    
    # Main Requirements Review Sheet
    sheet = workbook.active
    sheet.title = "Requirements Review"

    sheet.append(_HEADERS)
    header_font = Font(bold=True, color=_HEADER_FONT_COLOR)
    header_fill = PatternFill(start_color=_HEADER_FILL, end_color=_HEADER_FILL, fill_type="solid")
    for col_idx in range(1, len(_HEADERS) + 1):
        cell = sheet.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"

    for row_num, req in enumerate(requirements, start=2):
        candidates = req["candidates"]
        recommended_idx = req["recommended_index"]
        alternates = [c for c in candidates if c["index"] != recommended_idx]

        sheet.append([
            req["sequence_in_run"] + 1,
            _format_source_location(req["source_location"]),
            req["original_text"],
            req["ears_pattern"].get("pattern", ""),
            _STATUS_LABELS.get(req["status"], req["status"]),
            req["recommended_text"],
            req["recommended_score"],
            _format_accurate_score(req["accurate_score_status"], req["accurate_score"]),
            _format_candidate(alternates[0] if len(alternates) > 0 else None),
            _format_candidate(alternates[1] if len(alternates) > 1 else None),
            "Yes" if req["needs_human_review"] else "No",
            _format_suggestions(req["vague_term_suggestions"]),
            _format_violations(req["violations"]),
        ])

        needs_review = req["needs_human_review"]
        fill = PatternFill(
            start_color=_NEEDS_REVIEW_FILL if needs_review else _OK_FILL,
            end_color=_NEEDS_REVIEW_FILL if needs_review else _OK_FILL,
            fill_type="solid",
        )
        review_font = Font(bold=True, color=_NEEDS_REVIEW_FONT if needs_review else _OK_FONT)
        for col_idx in range(1, len(_HEADERS) + 1):
            cell = sheet.cell(row=row_num, column=col_idx)
            cell.fill = fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if col_idx == 11:  # "Needs Review" column
                cell.font = review_font

    for col_idx, width in enumerate(_COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(col_idx)].width = width

    # Consistency Analysis Sheet (if relationships exist)
    relationships = get_requirement_relationships(conn, run_id)
    if relationships:
        consistency_sheet = workbook.create_sheet("Consistency Analysis")
        
        consistency_headers = [
            "Req #1", "Req #2", "Relationship Type", 
            "Similarity Score", "Confidence", "Reason"
        ]
        consistency_sheet.append(consistency_headers)
        
        for col_idx in range(1, len(consistency_headers) + 1):
            cell = consistency_sheet.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        
        consistency_sheet.column_dimensions["A"].width = 8
        consistency_sheet.column_dimensions["B"].width = 8
        consistency_sheet.column_dimensions["C"].width = 18
        consistency_sheet.column_dimensions["D"].width = 14
        consistency_sheet.column_dimensions["E"].width = 12
        consistency_sheet.column_dimensions["F"].width = 50
        
        # Build requirement map for display
        req_map = {req["id"]: req["sequence_in_run"] + 1 for req in requirements}
        
        for row_num, rel in enumerate(relationships, start=2):
            req_1_num = req_map.get(rel["req_id_1"], rel["req_id_1"])
            req_2_num = req_map.get(rel["req_id_2"], rel["req_id_2"])
            
            consistency_sheet.append([
                f"#{req_1_num}",
                f"#{req_2_num}",
                rel["relationship_type"].capitalize(),
                f"{rel['similarity_score'] * 100:.1f}%",
                f"{rel['confidence'] * 100:.1f}%",
                rel["reason"] or "",
            ])
            
            # Color code based on relationship type
            fill = None
            if rel["relationship_type"] == "duplicate":
                fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            elif rel["relationship_type"] == "contradiction":
                fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            elif rel["relationship_type"] == "similar":
                fill = PatternFill(start_color="FFE6CC", end_color="FFE6CC", fill_type="solid")
            
            if fill:
                for col_idx in range(1, len(consistency_headers) + 1):
                    cell = consistency_sheet.cell(row=row_num, column=col_idx)
                    cell.fill = fill

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return output_path

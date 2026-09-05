"""FastAPI backend for the Flight Controller Requirements Agent.

Two-phase, deliberately split (see src/pipeline/graph.py's module
docstring for the full rationale):

  1. POST /upload parses the workbook and runs analyze_requirement() --
     deterministic only, no LLM -- on every requirement SYNCHRONOUSLY
     (sub-millisecond each, so even a few hundred requirements return
     before the request times out). The client gets EARS pattern, INCOSE
     score, and every violation for the whole workbook back immediately.
  2. A human then decides, per requirement (or in bulk): POST
     /runs/{id}/requirements/generate to send it to the LLM, or PUT
     /runs/{id}/requirements/{req_id} to type a replacement themselves.
     Only step 2 ever talks to the LLM endpoint, and only for the rows a
     human actually asked for -- never automatically for a whole workbook.

No auth, no task queue, no websockets -- in-process FastAPI
BackgroundTasks (for the LLM generate step only) and the same local
SQLite file src/storage/db.py already uses are enough for a single-user
local tool. The only network call this app ever makes is to the
DRDO-internal vLLM endpoint configured in config/settings.yaml's
llm.base_url -- never a public/hosted API -- and only from the Generate
action and consistency's contradiction check; everything else (analysis,
manual edit, export) is local and works with that endpoint unreachable.

Run it (binds to loopback by default, matching the offline requirement):
    uvicorn ui.api:app --app-dir src
"""

from __future__ import annotations
import os
import sqlite3
from fastapi.middleware.cors import CORSMiddleware
import uuid
from dataclasses import asdict
from pathlib import Path
from zipfile import BadZipFile

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import storage.db as db
from consistency.analyzer import ConsistencyAnalyzer
from ingestion.parser import parse_workbook
from llm.local_llm_client import LocalLLMClient, LLMUnavailableError
from pipeline.graph import analyze_requirement, generate_requirement
from rules.incose_ai_scorer import score_accurate
from config import get_settings
from ui import progress

app = FastAPI(title="Flight Controller Requirements Agent")

# Local dev origins are always allowed. When the frontend is deployed
# elsewhere (e.g. Vercel), set CORS_ALLOWED_ORIGINS to a comma-separated
# list of extra origins (e.g. "https://my-app.vercel.app") rather than
# hardcoding a deployment-specific URL here.
_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = REPO_ROOT / "data" / "uploads"
EXPORT_DIR = REPO_ROOT / "data" / "exports"


def _get_run_upload_dir(run_id: int) -> Path:
    """Returns the run-specific upload directory: data/uploads/run_{id}/"""
    return UPLOAD_DIR / f"run_{run_id}"


def _get_run_export_dir(run_id: int) -> Path:
    """Returns the run-specific export directory: data/exports/run_{id}/"""
    return EXPORT_DIR / f"run_{run_id}"


def _ensure_run_folder_structure(run_id: int) -> None:
    """Creates the run folder structure with input, output, and logs subdirectories."""
    run_upload_dir = _get_run_upload_dir(run_id)
    run_export_dir = _get_run_export_dir(run_id)
    
    # Create upload structure: run_{id}/input/
    (run_upload_dir / "input").mkdir(parents=True, exist_ok=True)
    
    # Create export structure: run_{id}/output/ and run_{id}/logs/
    (run_export_dir / "output").mkdir(parents=True, exist_ok=True)
    (run_export_dir / "logs").mkdir(parents=True, exist_ok=True)

INVALID_EXCEL_FILE = "INVALID_EXCEL_FILE"
PARSE_ERROR = "PARSE_ERROR"
INVALID_FILE_TYPE = "INVALID_FILE_TYPE"

# LLM-related error codes
AI_SERVICE_UNAVAILABLE = "AI_SERVICE_UNAVAILABLE"
AI_RESPONSE_VALIDATION_FAILED = "AI_RESPONSE_VALIDATION_FAILED"
AI_REQUEST_TIMEOUT = "AI_REQUEST_TIMEOUT"
AI_MODEL_NOT_FOUND = "AI_MODEL_NOT_FOUND"
AI_UNKNOWN_ERROR = "AI_UNKNOWN_ERROR"


def _error_code_for_parse_issues(issues: list) -> str:
    """Maps parser-reported workbook issues to a frontend-friendly error code."""
    for issue in issues:
        reason = issue.reason
        if reason == "file_not_found":
            return PARSE_ERROR
        if reason.startswith("failed_to_open_workbook"):
            return INVALID_EXCEL_FILE
        if reason.startswith("failed_to_parse_sheet"):
            return PARSE_ERROR
    return PARSE_ERROR


def _error_code_for_exception(exc: Exception) -> str | None:
    """Maps parse-related and LLM exceptions to friendly codes; None preserves legacy formatting."""
    # Excel parsing errors
    if isinstance(exc, BadZipFile):
        return INVALID_EXCEL_FILE

    exc_name = type(exc).__name__
    if exc_name in ("InvalidFileException", "UnsupportedFormatException"):
        return INVALID_EXCEL_FILE

    message = str(exc).lower()
    if "failed to parse" in message:
        return PARSE_ERROR
    if "bad zip" in message or "not a zip file" in message:
        return INVALID_EXCEL_FILE

    # LLM-related errors
    if exc_name == "LLMUnavailableError":
        return AI_SERVICE_UNAVAILABLE
    if exc_name == "LLMResponseError":
        return AI_RESPONSE_VALIDATION_FAILED
    if "timeout" in message or "timed out" in message:
        return AI_REQUEST_TIMEOUT
    if "model not found" in message or "model" in message and "not" in message:
        return AI_MODEL_NOT_FOUND

    return None


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "model": settings["llm"]["model"]}


def _analyze_run(conn: sqlite3.Connection, run_id: int, file_path: Path) -> None:
    """Runs analyze_requirement() -- deterministic only, no LLM -- against
    every requirement in ``file_path`` and saves each result immediately.
    Called synchronously from POST /upload, not as a background task:
    even a few hundred requirements finish in well under a second (see
    analyze_requirement()'s own timing), so there's nothing to poll for
    and no reason to make the client wait through a "processing" status
    for what is, start to finish, sub-second work.
    """
    db.update_run_status(conn, run_id, "processing")

    parse_result = parse_workbook(file_path)
    if parse_result.issues:
        db.update_run_status(
            conn, run_id, "failed", error_message=_error_code_for_parse_issues(parse_result.issues)
        )
        return
    total = len(parse_result.candidates)
    db.set_run_total_requirements(conn, run_id, total)

    for i, candidate in enumerate(parse_result.candidates):
        result = analyze_requirement(candidate.text, source_location=asdict(candidate.location))
        db.save_requirement(conn, run_id, i, result)

    db.update_run_status(conn, run_id, "completed")


def _generate_selected(run_id: int, requirement_ids: list[int]) -> None:
    """Background task for POST /runs/{run_id}/requirements/generate: runs
    the LLM phase for exactly the requirement ids a human selected, one at
    a time, marking each row "generating" right before its call starts so
    a client polling GET /runs/{run_id}/requirements sees live per-row
    progress without any separate console/stage machinery -- the status
    column IS the progress indicator.

    Never raises out of a background task (FastAPI would just log and
    silently drop the exception) -- a failure marks that one row "failed"
    with a friendly error code and moves on to the next id, rather than
    losing the whole selection because one requirement's call errored.
    """
    conn = db.connect()
    try:
        client = LocalLLMClient()
        try:
            client.check_reachable()
        except LLMUnavailableError:
            for req_id in requirement_ids:
                db.update_requirement_status(conn, req_id, "failed", error_message=AI_SERVICE_UNAVAILABLE)
            return

        for req_id in requirement_ids:
            analyzed = db.get_requirement(conn, req_id)
            if analyzed is None:
                continue
            db.update_requirement_status(conn, req_id, "generating")
            try:
                result = generate_requirement(analyzed, client)
                db.apply_generation_result(conn, req_id, result)
            except Exception as exc:  # noqa: BLE001 -- one bad row must not stop the rest
                friendly_code = _error_code_for_exception(exc) or AI_UNKNOWN_ERROR
                print(f"Error generating requirement {req_id} (run {run_id}): {exc}")
                import traceback
                traceback.print_exc()
                db.update_requirement_status(conn, req_id, "failed", error_message=friendly_code)
    finally:
        conn.close()


def _compute_accurate_score(run_id: int, requirement_id: int) -> None:
    """Background task for POST /runs/{run_id}/requirements/{id}/accurate-score.

    Computes the on-demand 42-rule score for exactly the ONE requirement a
    human clicked "Check Accurate Score" for -- the existing 28-rule
    deterministic score (src/rules/incose_scorer.py) plus an LLM verdict on
    the 14 rules that can't be checked mechanically (src/rules/
    incose_ai_scorer.py). This never runs automatically or in bulk: it's a
    real LLM call, made only for the one row a human explicitly asked
    about, same "opt-in, one row at a time" spirit as Generate.

    Scores whatever text is currently under review (requirement's
    recommended_text -- the original text for an "analyzed"/not-yet-acted-
    on row, or the generated/edited text once a human has acted on it),
    not always the original submission, so the accurate score always
    reflects what the human is actually looking at right now.
    """
    conn = db.connect()
    try:
        req = db.get_requirement(conn, requirement_id)
        if req is None or req["run_id"] != run_id:
            return

        try:
            client = LocalLLMClient()
            client.check_reachable()
        except LLMUnavailableError:
            db.fail_accurate_score(conn, requirement_id, AI_SERVICE_UNAVAILABLE)
            return

        db.start_accurate_score(conn, requirement_id)
        try:
            result = score_accurate(req["recommended_text"], client)
            violations = (
                [asdict(f) for f in result.deterministic.failed]
                + [asdict(f) for f in result.ai.failed]
            )
            db.save_accurate_score(conn, requirement_id, result.combined_score, violations)
        except Exception as exc:  # noqa: BLE001 -- must not crash the background task
            friendly_code = _error_code_for_exception(exc) or AI_UNKNOWN_ERROR
            print(f"Error computing accurate score for requirement {requirement_id} (run {run_id}): {exc}")
            import traceback
            traceback.print_exc()
            db.fail_accurate_score(conn, requirement_id, friendly_code)
    finally:
        conn.close()


def _run_consistency_analysis(conn: db.sqlite3.Connection, run_id: int) -> bool:
    """Runs consistency analysis on all requirements in a run -- duplicate/
    similarity detection is pure embeddings (no LLM); contradiction
    detection needs the LLM endpoint and is skipped (not a failure) if
    it isn't reachable, checked once for the whole run, not once per pair
    -- see ConsistencyAnalyzer._is_llm_reachable(). Failures here should
    not fail the entire run - we log and continue.

    Returns True if contradiction detection was skipped because the LLM
    endpoint wasn't reachable (duplicate/similarity results are still
    valid and saved either way) -- callers use this to tell the human
    "duplicates and similar pairs were found; contradiction checking
    needs the LLM endpoint reachable" instead of silently under-reporting
    contradictions.
    """
    try:
        requirements = db.get_requirements_for_run(conn, run_id)
        if len(requirements) < 2:
            return False  # Not enough requirements to analyze

        # Clear any existing relationships for this run to avoid stale data
        conn.execute("DELETE FROM requirement_relationships WHERE run_id = ?", (run_id,))
        conn.commit()

        # Prepare requirements for analysis
        # Note: We use the database auto-increment ID here for analysis,
        # but will convert to sequence_in_run for display to avoid showing stale IDs
        req_data = [{"id": req["id"], "recommended_text": req["recommended_text"]} for req in requirements]

        # Run consistency analysis
        analyzer = ConsistencyAnalyzer()
        result = analyzer.analyze_requirements(run_id, req_data)

        # Save relationships to database
        # Save relationships to database. analyzer.py's analyze_requirements
        # already sets req_id_1/req_id_2 to the real requirement IDs (not
        # positions), so no remapping is needed here.
        for rel in result.relationships:
            db.save_requirement_relationship(
                conn,
                run_id,
                rel.req_id_1,
                rel.req_id_2,
                rel.relationship_type.value,
                rel.similarity_score,
                rel.confidence,
                rel.reason,
            )

        print(f"Consistency analysis completed for run {run_id}: {len(result.relationships)} relationships found")
        return result.contradiction_check_skipped

    except Exception as exc:  # noqa: BLE001 -- consistency analysis failure should not fail the run
        # Log the error but don't fail the entire run
        print(f"Consistency analysis failed for run {run_id}: {exc}")
        import traceback
        traceback.print_exc()
        return False


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """Saves the uploaded spreadsheet, creates a run row, and runs the
    deterministic analysis phase (analyze_requirement() for every
    requirement -- EARS pattern, INCOSE score, violations, no LLM)
    SYNCHRONOUSLY before responding: sub-second even for a large workbook,
    so the client gets the full analysis table back in this one response
    instead of polling a "processing" status for it. The run is already
    "completed" (analysis-complete) by the time this returns; LLM
    generation is a separate, later, per-requirement action -- see POST
    /runs/{run_id}/requirements/generate.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    # Step 1: Save file temporarily to get run_id
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = UPLOAD_DIR / f"temp_{uuid.uuid4().hex}_{file.filename}"
    temp_path.write_bytes(await file.read())

    # Step 2: Create run in database to get run_id
    conn = db.connect()
    try:
        run_id = db.create_run(conn, file_name=file.filename, file_path=temp_path)
    finally:
        conn.close()

    # Step 3: Create run folder structure
    _ensure_run_folder_structure(run_id)

    # Step 4: Move file to final location: uploads/run_{id}/input/
    final_path = _get_run_upload_dir(run_id) / "input" / file.filename
    temp_path.rename(final_path)

    # Step 5: Update database with new file path, then run analysis --
    # same connection, no background task: this is the whole request.
    conn = db.connect()
    try:
        conn.execute("UPDATE runs SET file_path = ? WHERE id = ?", (str(final_path), run_id))
        conn.commit()
        _analyze_run(conn, run_id, final_path)
        run = db.get_run(conn, run_id)
    finally:
        conn.close()

    return {"run_id": run_id, "status": run["status"] if run else "failed"}


@app.get("/runs")
def list_runs() -> list[dict]:
    conn = db.connect()
    try:
        return db.list_runs(conn)
    finally:
        conn.close()


@app.get("/runs/{run_id}")
def get_run_status(run_id: int) -> dict:
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
    finally:
        conn.close()
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return run


@app.get("/runs/{run_id}/requirements")
def get_run_requirements(run_id: int) -> list[dict]:
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        return db.get_requirements_for_run(conn, run_id)
    finally:
        conn.close()


class GenerateRequest(BaseModel):
    requirement_ids: list[int]


@app.post("/runs/{run_id}/requirements/generate")
def generate_requirements(run_id: int, body: GenerateRequest, background_tasks: BackgroundTasks) -> dict:
    """A human selected one or more requirements (a single row's Generate
    button, or Select All + Generate) and wants the LLM to rewrite them.
    Schedules _generate_selected() in the background -- an LLM call can
    take anywhere from seconds to several minutes on CPU, so this returns
    immediately and the client polls GET /runs/{run_id}/requirements,
    watching each requested row's own "status" flip
    analyzed -> generating -> generated/failed. Every other row in the run
    is left completely untouched.
    """
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        if not body.requirement_ids:
            raise HTTPException(status_code=400, detail="requirement_ids must not be empty.")
        for req_id in body.requirement_ids:
            if db.get_requirement(conn, req_id) is None:
                raise HTTPException(status_code=404, detail=f"No requirement with id {req_id}")
    finally:
        conn.close()

    background_tasks.add_task(_generate_selected, run_id, body.requirement_ids)
    return {"run_id": run_id, "status": "generating", "requirement_ids": body.requirement_ids}


class EditRequest(BaseModel):
    recommended_text: str


@app.put("/runs/{run_id}/requirements/{requirement_id}")
def edit_requirement(run_id: int, requirement_id: int, body: EditRequest) -> dict:
    """A human typed a replacement requirement themselves instead of using
    Generate -- no LLM involved, purely deterministic re-scoring
    (db.apply_manual_edit), so this is synchronous and near-instant.
    """
    if not body.recommended_text.strip():
        raise HTTPException(status_code=400, detail="recommended_text must not be empty.")

    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        existing = db.get_requirement(conn, requirement_id)
        if existing is None or existing["run_id"] != run_id:
            raise HTTPException(
                status_code=404, detail=f"No requirement with id {requirement_id} in run {run_id}"
            )
        return db.apply_manual_edit(conn, requirement_id, body.recommended_text.strip())
    finally:
        conn.close()


@app.post("/runs/{run_id}/requirements/{requirement_id}/accurate-score")
def compute_accurate_score(
    run_id: int, requirement_id: int, background_tasks: BackgroundTasks
) -> dict:
    """A human clicked "Check Accurate Score" for one requirement: the
    default score every requirement gets automatically only covers the 28
    automatable INCOSE rules (see src/rules/incose_scorer.py); this adds an
    LLM judgement on the other 14 rules and combines both into a 42-rule
    score (src/rules/incose_ai_scorer.py). Runs in the background exactly
    like POST .../generate -- a real LLM call can take a while, so this
    returns immediately with status "computing" and the client polls GET
    /runs/{run_id}/requirements, watching this row's own
    accurate_score_status flip to "done" or "failed".
    """
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        existing = db.get_requirement(conn, requirement_id)
        if existing is None or existing["run_id"] != run_id:
            raise HTTPException(
                status_code=404, detail=f"No requirement with id {requirement_id} in run {run_id}"
            )
    finally:
        conn.close()

    background_tasks.add_task(_compute_accurate_score, run_id, requirement_id)
    return {"run_id": run_id, "requirement_id": requirement_id, "status": "computing"}


@app.get("/runs/{run_id}/download")
def download_run(run_id: int) -> FileResponse:
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        if run["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id} is not ready to download (status: {run['status']}).",
            )

        # Ensure run folder structure exists
        _ensure_run_folder_structure(run_id)

        # Export to run-specific output directory: exports/run_{id}/output/
        export_path = _get_run_export_dir(run_id) / "output" / "reviewed_requirements.xlsx"
        db.export_run_to_excel(conn, run_id, export_path)
    finally:
        conn.close()

    return FileResponse(
        export_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=export_path.name,
    )


@app.get("/runs/{run_id}/consistency")
def get_run_consistency(run_id: int) -> dict:
    """Returns consistency analysis results for a run."""
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        
        relationships = db.get_requirement_relationships(conn, run_id)
        summary = db.get_consistency_summary(conn, run_id)
        
        # Get requirement details for the relationships
        requirements_map = {}
        for req in db.get_requirements_for_run(conn, run_id):
            requirements_map[req["id"]] = {
                "id": req["id"],
                "sequence_in_run": req["sequence_in_run"],
                "recommended_text": req["recommended_text"],
                "original_text": req["original_text"],
            }
        
        # Enrich relationships with requirement details
        # Map database IDs to sequence_in_run for display to avoid showing stale/incorrect IDs
        enriched_relationships = []
        for rel in relationships:
            req_1 = requirements_map.get(rel["req_id_1"])
            req_2 = requirements_map.get(rel["req_id_2"])
            
            if req_1 and req_2:
                # Use sequence_in_run for display IDs (0-based, so add 1 for 1-based display)
                enriched_relationships.append({
                    **rel,
                    "req_1": {
                        **req_1,
                        "display_id": req_1["sequence_in_run"] + 1,  # Convert to 1-based for display
                    },
                    "req_2": {
                        **req_2,
                        "display_id": req_2["sequence_in_run"] + 1,  # Convert to 1-based for display
                    },
                })
        
        return {
            "run_id": run_id,
            "total_requirements": run.get("total_requirements", 0),
            "summary": summary,
            "relationships": enriched_relationships,
        }
    finally:
        conn.close()


@app.post("/runs/{run_id}/reanalyze-consistency")
def reanalyze_consistency(run_id: int) -> dict:
    """Triggers re-analysis of consistency for a run."""
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        if run["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id} must be completed before re-analyzing consistency.",
            )
        
        # Clear existing relationships
        db.clear_requirement_relationships(conn, run_id)

        # Re-run consistency analysis
        contradiction_check_skipped = _run_consistency_analysis(conn, run_id)

        # Return updated results
        relationships = db.get_requirement_relationships(conn, run_id)
        summary = db.get_consistency_summary(conn, run_id)

        message = (
            "Consistency analysis completed, but contradiction detection was "
            "skipped because the LLM endpoint is not reachable -- duplicate and "
            "similarity results (no LLM needed) are still complete and accurate."
            if contradiction_check_skipped
            else "Consistency analysis completed"
        )
        return {
            "run_id": run_id,
            "message": message,
            "contradiction_check_skipped": contradiction_check_skipped,
            "summary": summary,
            "relationships_count": len(relationships),
        }
    finally:
        conn.close()


@app.get("/runs/{run_id}/progress")
def get_run_progress(run_id: int, after_seq: int = -1) -> dict:
    """Live pipeline progress for the Processing Status page: which stage
    is currently running for which requirement, plus every stage-completion
    event with seq > after_seq (pass the highest seq you've already seen to
    poll incrementally instead of re-fetching the whole log each time).
    """
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    finally:
        conn.close()
    return progress.get_progress(run_id, after_seq)


@app.get("/runs/{run_id}/embedding-matrix")
def get_embedding_matrix(run_id: int) -> dict:
    """Full pairwise embedding-similarity matrix for every combination of
    requirements in a run (not just the ones that clear the duplicate/
    similar thresholds -- see /runs/{run_id}/consistency for that). Pure
    embedding + cosine similarity, no LLM calls, so it's cheap to call on
    every tab open even for a 100-requirement run (~5000 pairs).
    """
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        requirements = db.get_requirements_for_run(conn, run_id)
    finally:
        conn.close()

    req_data = [{"id": req["id"], "recommended_text": req["recommended_text"]} for req in requirements]
    analyzer = ConsistencyAnalyzer()
    result = analyzer.compute_pairwise_similarities(req_data)

    seq_by_id = {req["id"]: req["sequence_in_run"] + 1 for req in requirements}
    for pair in result["pairs"]:
        pair["req_1_number"] = seq_by_id.get(pair["req_id_1"])
        pair["req_2_number"] = seq_by_id.get(pair["req_id_2"])

    return result

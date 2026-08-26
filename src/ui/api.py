"""FastAPI backend for the Flight Controller Requirements Agent.

Deliberately simple: one endpoint to upload a spreadsheet and kick off the
pipeline, one to poll run status, one to fetch the per-requirement results,
one to download the reviewed Excel export. No auth, no task queue, no
websockets -- an in-process FastAPI BackgroundTasks call and the same
local SQLite file src/storage/db.py already uses are enough for a
single-user local tool that, per this project's README, never talks to
anything but a loopback Ollama instance.

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

import storage.db as db
from consistency.analyzer import ConsistencyAnalyzer
from ingestion.parser import parse_workbook
from llm.local_llm_client import LocalLLMClient
from pipeline.graph import build_graph, run_requirement_streaming
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
    if exc_name == "OllamaUnavailableError":
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
    return {"status": "ok", "model": settings["ollama"]["model"]}


def _describe_stage(node_name: str, node_output: dict) -> str:
    """Turns one LangGraph node's raw output into a human-readable console
    line for the live progress log -- e.g. "3 candidate rewrites generated
    via Ollama" rather than dumping the raw state dict."""
    if node_name == "Parse":
        text = node_output.get("original_text", "")
        return f"Parsed requirement text ({len(text)} chars)"

    if node_name == "RuleFlag":
        flags = node_output.get("rule_flags", [])
        if not flags:
            return "No rule violations detected"
        types = ", ".join(f["violation_type"] for f in flags)
        return f"{len(flags)} rule flag(s) detected: {types}"

    if node_name == "ClassifyPattern":
        classification = node_output.get("ears_classification", {})
        pattern = classification.get("pattern", "unknown")
        confidence = classification.get("confidence", 0.0)
        return f"EARS pattern classified as '{pattern}' (confidence {confidence:.2f})"

    if node_name == "AbbreviationCheck":
        issues = node_output.get("abbreviation_issues", [])
        if not issues:
            return "No undefined acronyms or informal abbreviations found"
        return f"{len(issues)} abbreviation issue(s) found: " + " ".join(issues)

    if node_name == "ComplianceCheck":
        compliant = node_output.get("ears_compliant", False)
        if compliant:
            return "EARS compliance check passed -- proceeding to LLM rewrite generation"
        reason = node_output.get("rejection_reason", "")
        return f"EARS compliance check FAILED -- rejecting without calling the LLM: {reason}"

    if node_name == "RejectNonEars":
        result = node_output.get("result", {})
        reason = result.get("ears_pattern", {}).get("reason", "not EARS compliant")
        return f"Requirement REJECTED: {reason}"

    if node_name == "GenerateCandidates":
        candidates = node_output.get("candidates_raw", [])
        return f"{len(candidates)} candidate rewrite(s) generated via Ollama"

    if node_name == "ScoreAndRecommend":
        recommendation = node_output.get("recommendation")
        if recommendation is None:
            return "Candidates scored via INCOSE rule engine"
        recommended = recommendation.recommended
        return (
            f"Recommended candidate #{recommendation.recommended_index + 1} "
            f"(INCOSE score {recommended.score:.1f}/100)"
        )

    if node_name == "Finalize":
        needs_review = node_output.get("needs_human_review", False)
        return (
            "Flagged for human review"
            if needs_review
            else "Ready for export -- no human review required"
        )

    return "Stage completed"


def _process_run(run_id: int, file_path: Path) -> None:
    """Runs the full pipeline against every requirement in ``file_path``
    and saves each result as it completes. Always leaves the run in
    'completed' or 'failed' status -- never raises out of a background
    task, since FastAPI would just log and silently drop the exception.

    Also streams live stage-by-stage progress (see src/ui/progress.py) so
    the frontend's Processing Status page can show, in real time, exactly
    which of the 6 pipeline stages is running for which requirement.
    """
    conn = db.connect()
    progress.start_run(run_id)
    try:
        db.update_run_status(conn, run_id, "processing")

        parse_result = parse_workbook(file_path)
        if parse_result.issues:
            db.update_run_status(
                conn,
                run_id,
                "failed",
                error_message=_error_code_for_parse_issues(parse_result.issues),
            )
            return
        total = len(parse_result.candidates)
        db.set_run_total_requirements(conn, run_id, total)

        client = LocalLLMClient()
        client.check_reachable()
        compiled_graph = build_graph(client=client)

        for i, candidate in enumerate(parse_result.candidates):
            progress.record(
                run_id, i, "Start", f"Processing requirement {i + 1} of {total}", status="running"
            )

            def _on_stage(node_name: str, node_output: dict, _i: int = i) -> None:
                progress.record(run_id, _i, node_name, _describe_stage(node_name, node_output))

            result = run_requirement_streaming(
                compiled_graph,
                candidate.text,
                source_location=asdict(candidate.location),
                on_stage=_on_stage,
            )
            db.save_requirement(conn, run_id, i, result)

        # Run consistency analysis after all requirements are processed
        progress.record(
            run_id, total - 1, "ConsistencyAnalysis",
            "Running cross-requirement consistency analysis...", status="running",
        )
        _run_consistency_analysis(conn, run_id)
        progress.record(
            run_id, total - 1, "ConsistencyAnalysis", "Consistency analysis complete"
        )

        db.update_run_status(conn, run_id, "completed")
    except Exception as exc:  # noqa: BLE001 -- always record, a background task must not fail silently
        friendly_code = _error_code_for_exception(exc)

        # Log full technical error for debugging
        import traceback
        import sys
        try:
            print(f"Error processing run {run_id}: {exc}")
            traceback.print_exc()
        except UnicodeEncodeError:
            # Fallback for Windows console encoding issues
            print(f"Error processing run {run_id}: {repr(exc)}")
            traceback.print_exc(file=sys.stderr)

        # Store user-friendly error code in database
        error_message = friendly_code if friendly_code else AI_UNKNOWN_ERROR
        db.update_run_status(conn, run_id, "failed", error_message=error_message)
    finally:
        conn.close()


def _run_consistency_analysis(conn: db.sqlite3.Connection, run_id: int) -> None:
    """Runs consistency analysis on all requirements in a run.
    
    This is called after all requirements have been processed.
    Failures here should not fail the entire run - we log and continue.
    """
    try:
        requirements = db.get_requirements_for_run(conn, run_id)
        if len(requirements) < 2:
            return  # Not enough requirements to analyze

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

    except Exception as exc:  # noqa: BLE001 -- consistency analysis failure should not fail the run
        # Log the error but don't fail the entire run
        print(f"Consistency analysis failed for run {run_id}: {exc}")
        import traceback
        traceback.print_exc()


@app.post("/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    """Saves the uploaded spreadsheet, creates a run row, and schedules
    pipeline processing in the background. Returns immediately with a
    run_id the client polls via GET /runs/{run_id}.
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

    # Step 5: Update database with new file path
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE runs SET file_path = ? WHERE id = ?",
            (str(final_path), run_id)
        )
        conn.commit()
    finally:
        conn.close()

    # Step 6: Schedule background task with final path
    background_tasks.add_task(_process_run, run_id, final_path)
    return {"run_id": run_id, "status": "pending"}


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
        _run_consistency_analysis(conn, run_id)
        
        # Return updated results
        relationships = db.get_requirement_relationships(conn, run_id)
        summary = db.get_consistency_summary(conn, run_id)
        
        return {
            "run_id": run_id,
            "message": "Consistency analysis completed",
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

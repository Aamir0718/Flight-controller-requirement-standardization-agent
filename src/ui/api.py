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
from fastapi.middleware.cors import CORSMiddleware
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

import storage.db as db
from ingestion.parser import parse_workbook
from llm.local_llm_client import LocalLLMClient
from pipeline.graph import build_graph, run_requirement

app = FastAPI(title="Flight Controller Requirements Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = REPO_ROOT / "data" / "uploads"
EXPORT_DIR = REPO_ROOT / "data" / "exports"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _process_run(run_id: int, file_path: Path) -> None:
    """Runs the full pipeline against every requirement in ``file_path``
    and saves each result as it completes. Always leaves the run in
    'completed' or 'failed' status -- never raises out of a background
    task, since FastAPI would just log and silently drop the exception.
    """
    conn = db.connect()
    try:
        db.update_run_status(conn, run_id, "processing")

        parse_result = parse_workbook(file_path)
        if parse_result.issues:
            raise RuntimeError(f"Failed to parse {file_path.name}: {parse_result.issues}")
        db.set_run_total_requirements(conn, run_id, len(parse_result.candidates))

        client = LocalLLMClient()
        client.check_reachable()
        compiled_graph = build_graph(client=client)

        for i, candidate in enumerate(parse_result.candidates):
            result = run_requirement(
                compiled_graph, candidate.text, source_location=asdict(candidate.location)
            )
            db.save_requirement(conn, run_id, i, result)

        db.update_run_status(conn, run_id, "completed")
    except Exception as exc:  # noqa: BLE001 -- always record, a background task must not fail silently
        db.update_run_status(conn, run_id, "failed", error_message=f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()


@app.post("/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    """Saves the uploaded spreadsheet, creates a run row, and schedules
    pipeline processing in the background. Returns immediately with a
    run_id the client polls via GET /runs/{run_id}.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    saved_path.write_bytes(await file.read())

    conn = db.connect()
    try:
        run_id = db.create_run(conn, file_name=file.filename, file_path=saved_path)
    finally:
        conn.close()

    background_tasks.add_task(_process_run, run_id, saved_path)
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

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        export_path = EXPORT_DIR / f"run_{run_id}_review.xlsx"
        db.export_run_to_excel(conn, run_id, export_path)
    finally:
        conn.close()

    return FileResponse(
        export_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=export_path.name,
    )

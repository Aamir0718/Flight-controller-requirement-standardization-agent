"""In-memory live progress tracking for an active pipeline run.

Lets the frontend's Processing Status page show, in real time, which of
the LangGraph pipeline stages (Parse, RuleFlag, ClassifyPattern,
AbbreviationCheck, IncoseCheck, ComplianceCheck, GenerateCandidates,
ScoreAndRecommend, Finalize -- see src/pipeline/graph.py) is currently
executing for which requirement, plus a running console log of what each
stage did -- without adding a task queue, websockets, or a new SQLite
table for what is inherently transient, run-scoped state (this project's
README is explicit that it's a single-user local tool; a background
BackgroundTasks call is the only concurrency it has).

Not thread-safe beyond CPython's GIL; that's fine here for the same
reason src/storage/db.py doesn't bother locking its connection either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StageEvent:
    seq: int
    ts: str
    requirement_index: int  # 0-based index of the requirement this event is about
    stage: str
    message: str
    status: str  # "running" | "done" | "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "requirement_index": self.requirement_index,
            "stage": self.stage,
            "message": self.message,
            "status": self.status,
        }


@dataclass
class _RunProgress:
    events: list[StageEvent] = field(default_factory=list)
    current_requirement_index: int | None = None
    current_stage: str | None = None
    next_seq: int = 0

    def add(self, requirement_index: int, stage: str, message: str, status: str) -> None:
        self.events.append(
            StageEvent(
                seq=self.next_seq,
                ts=datetime.now(timezone.utc).isoformat(),
                requirement_index=requirement_index,
                stage=stage,
                message=message,
                status=status,
            )
        )
        self.next_seq += 1
        self.current_requirement_index = requirement_index
        self.current_stage = stage


_progress_by_run: dict[int, _RunProgress] = {}


def start_run(run_id: int) -> None:
    """Resets tracking state for a run. Called once at the top of
    src/ui/api.py's _process_run so a run_id is never shown with stale
    events left over from anything earlier."""
    _progress_by_run[run_id] = _RunProgress()


def record(run_id: int, requirement_index: int, stage: str, message: str, status: str = "done") -> None:
    """Appends one stage event. If start_run() wasn't called first (should
    not happen in normal flow), tracking starts implicitly rather than the
    event being silently dropped."""
    run_progress = _progress_by_run.setdefault(run_id, _RunProgress())
    run_progress.add(requirement_index, stage, message, status)


def get_progress(run_id: int, after_seq: int = -1) -> dict[str, Any]:
    """Returns this run's current stage plus every event with seq >
    after_seq, so the frontend can poll incrementally instead of
    re-fetching the whole log every time. Returns an all-empty shape (not
    None/404) for a run_id nothing has been recorded for yet -- e.g. the
    short window between upload and _process_run's first stage event."""
    run_progress = _progress_by_run.get(run_id)
    if run_progress is None:
        return {"current_requirement_index": None, "current_stage": None, "events": []}
    return {
        "current_requirement_index": run_progress.current_requirement_index,
        "current_stage": run_progress.current_stage,
        "events": [e.to_dict() for e in run_progress.events if e.seq > after_seq],
    }


def clear_run(run_id: int) -> None:
    """Drops tracking state for a run. Not called automatically -- normal
    single-user local usage keeps the number of runs tracked for one
    server process's lifetime small enough that this is only here for
    completeness/tests, not because unbounded growth is a real concern."""
    _progress_by_run.pop(run_id, None)

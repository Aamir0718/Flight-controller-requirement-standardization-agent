"""Streamlit frontend for the Flight Controller Requirements Agent.

DRDO Aerospace & Defence AI Engineering Workspace over src/ui/api.py.
The FastAPI backend owns uploading, LangGraph processing, SQLite persistence,
and Excel export; the frontend presents that trace as an intelligent requirements
engineering workspace.

Run it:
    streamlit run src/ui/streamlit_app.py
(scripts/run_api.ps1 must already be running the backend.)
"""

from __future__ import annotations

import time
from datetime import datetime
from difflib import SequenceMatcher
from html import escape
from statistics import mean
from typing import Any

import pandas as pd
import requests
import streamlit as st

from config import get_settings

SETTINGS = get_settings()
_API_PORT = SETTINGS["ui"]["api_port"]
# Always loopback: config's ui.api_host is a bind address. The client must
# connect to a concrete local address to preserve the offline guarantee.
API_BASE_URL = f"http://127.0.0.1:{_API_PORT}"

NEEDS_REVIEW_COLOR = "#3a2118"
OK_COLOR = "#173225"
POLL_INTERVAL_SECONDS = 1.5
RECOMMENDED_MARKER = "\u2b50 "

st.set_page_config(
    page_title="Flight Controller Requirements Assistant | DRDO Engineering Workspace",
    page_icon=":material/flight:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Design System & Modern Tactical CSS Injection
# ---------------------------------------------------------------------------


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap');

        :root {
            --fc-bg: #070a10;
            --fc-surface-1: #0f172a;
            --fc-surface-2: #1e293b;
            --fc-border: #334155;
            --fc-border-subtle: rgba(255, 255, 255, 0.08);
            --fc-text-primary: #f8fafc;
            --fc-text-secondary: #cbd5e1;
            --fc-text-muted: #64748b;
            --fc-accent: #38bdf8;
            --fc-accent-glow: rgba(56, 189, 248, 0.15);
            --fc-green: #10b981;
            --fc-green-bg: rgba(16, 185, 129, 0.12);
            --fc-amber: #f59e0b;
            --fc-amber-bg: rgba(245, 158, 11, 0.12);
            --fc-rose: #f43f5e;
            --fc-rose-bg: rgba(244, 63, 94, 0.12);
            --fc-purple: #8b5cf6;
            --fc-purple-bg: rgba(139, 92, 246, 0.12);
            --fc-font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --fc-font-mono: 'JetBrains Mono', "SFMono-Regular", Consolas, monospace;
        }

        /* Overall Workspace Background */
        .stApp {
            background-color: var(--fc-bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(56, 189, 248, 0.08) 0px, transparent 45%),
                radial-gradient(at 100% 0%, rgba(139, 92, 246, 0.06) 0px, transparent 45%),
                linear-gradient(180deg, #070a10 0%, #04060a 100%);
            color: var(--fc-text-primary);
            font-family: var(--fc-font-sans);
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #05080e;
            border-right: 1px solid var(--fc-border);
        }

        [data-testid="stHeader"] {
            background: rgba(7, 10, 16, 0.82);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--fc-border-subtle);
        }

        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 4rem;
            max-width: 1560px;
        }

        /* Monospace elements */
        code, pre, .fc-mono {
            font-family: var(--fc-font-mono) !important;
        }

        /* Card and Container Styling */
        div[data-testid="stMetric"],
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--fc-surface-1);
            border: 1px solid var(--fc-border);
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transition: all 0.2s ease;
        }

        div[data-testid="stMetric"]:hover {
            border-color: rgba(56, 189, 248, 0.45);
            transform: translateY(-1px);
        }

        div[data-testid="stMetric"] label {
            color: var(--fc-text-muted) !important;
            font-size: 0.75rem !important;
            font-weight: 700 !important;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--fc-text-primary);
            font-weight: 700;
            font-size: 1.5rem;
        }

        /* Tactical DRDO Hero Banner */
        .fc-hero {
            border: 1px solid var(--fc-border);
            border-radius: 12px;
            padding: 1.6rem 2rem;
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.65));
            backdrop-filter: blur(8px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
            position: relative;
            overflow: hidden;
            margin-bottom: 1.2rem;
        }

        .fc-hero::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #38bdf8, #8b5cf6, #10b981);
        }

        .fc-eyebrow {
            color: var(--fc-accent);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .fc-hero h1 {
            margin: 0 0 0.5rem 0;
            font-size: clamp(1.8rem, 2.5vw, 2.6rem);
            font-weight: 700;
            color: var(--fc-text-primary);
            letter-spacing: -0.02em;
        }

        .fc-hero p {
            color: var(--fc-text-secondary);
            max-width: 82ch;
            margin-bottom: 0.9rem;
            font-size: 0.94rem;
            line-height: 1.6;
        }

        /* Badge Styling */
        .fc-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            align-items: center;
        }

        .fc-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border: 1px solid var(--fc-border);
            border-radius: 9999px;
            color: var(--fc-text-secondary);
            background: rgba(15, 23, 42, 0.85);
            font-size: 0.78rem;
            font-weight: 500;
            padding: 0.22rem 0.65rem;
            letter-spacing: 0.01em;
        }

        .fc-badge.green { border-color: rgba(16, 185, 129, 0.4); color: #6ee7b7; background: var(--fc-green-bg); }
        .fc-badge.blue { border-color: rgba(56, 189, 248, 0.4); color: #7dd3fc; background: var(--fc-accent-glow); }
        .fc-badge.amber { border-color: rgba(245, 158, 11, 0.4); color: #fcd34d; background: var(--fc-amber-bg); }
        .fc-badge.red { border-color: rgba(244, 63, 94, 0.4); color: #fca5a5; background: var(--fc-rose-bg); }
        .fc-badge.purple { border-color: rgba(139, 92, 246, 0.4); color: #c4b5fd; background: var(--fc-purple-bg); }

        /* Rule Violation Chips */
        .fc-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 6px;
            padding: 0.22rem 0.6rem;
            font-size: 0.8rem;
            font-weight: 600;
            margin: 0.15rem 0.2rem 0.15rem 0;
            line-height: 1.3;
        }

        .fc-chip-red {
            border: 1px solid rgba(244, 63, 94, 0.45);
            background: var(--fc-rose-bg);
            color: #fca5a5;
        }

        .fc-chip-yellow {
            border: 1px solid rgba(245, 158, 11, 0.45);
            background: var(--fc-amber-bg);
            color: #fcd34d;
        }

        .fc-chip-blue {
            border: 1px solid rgba(56, 189, 248, 0.45);
            background: var(--fc-accent-glow);
            color: #7dd3fc;
        }

        .fc-chip-purple {
            border: 1px solid rgba(139, 92, 246, 0.45);
            background: var(--fc-purple-bg);
            color: #c4b5fd;
        }

        .fc-chip-green {
            border: 1px solid rgba(16, 185, 129, 0.45);
            background: var(--fc-green-bg);
            color: #6ee7b7;
        }

        /* Interactive Pipeline Timeline Rail */
        .fc-workflow {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.6rem;
            margin: 1rem 0 1.4rem;
        }

        .fc-step {
            border: 1px solid var(--fc-border);
            border-radius: 8px;
            background: var(--fc-surface-1);
            padding: 0.75rem 0.85rem;
            color: var(--fc-text-muted);
            font-size: 0.82rem;
            transition: all 0.25 ease;
            position: relative;
        }

        .fc-step strong {
            color: var(--fc-text-secondary);
            display: flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.88rem;
            margin-bottom: 0.15rem;
        }

        .fc-step.active {
            border-color: var(--fc-accent);
            background: var(--fc-accent-glow);
            color: var(--fc-text-primary);
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.15);
        }

        .fc-step.active strong {
            color: var(--fc-accent);
        }

        .fc-step.done {
            border-color: rgba(16, 185, 129, 0.4);
            background: var(--fc-green-bg);
            color: var(--fc-text-secondary);
        }

        .fc-step.done strong {
            color: #6ee7b7;
        }

        /* Section Headings & Text Boxes */
        .fc-section-label {
            color: var(--fc-text-muted);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 0.2rem 0 0.3rem;
        }

        .fc-card-title {
            color: var(--fc-text-primary);
            font-size: 1rem;
            font-weight: 600;
            line-height: 1.4;
            margin-bottom: 0.35rem;
        }

        .fc-text-box {
            border: 1px solid var(--fc-border);
            border-radius: 8px;
            background: rgba(4, 7, 13, 0.8);
            padding: 0.85rem 0.95rem;
            min-height: 7.5rem;
            white-space: pre-wrap;
            font-family: var(--fc-font-sans);
            font-size: 0.9rem;
            line-height: 1.55;
            color: #e2e8f0;
        }

        .fc-text-box.mono {
            font-family: var(--fc-font-mono) !important;
            font-size: 0.88rem;
        }

        /* Diff Highlight Styling */
        .fc-change {
            background: rgba(56, 189, 248, 0.22);
            color: #7dd3fc;
            border-bottom: 2px solid var(--fc-accent);
            border-radius: 2px;
            padding: 0.08rem 0.25rem;
            font-weight: 500;
        }

        /* Run Context Card */
        .fc-run-context {
            border: 1px solid var(--fc-border);
            border-radius: 10px;
            background: linear-gradient(180deg, var(--fc-surface-1) 0%, rgba(15, 23, 42, 0.65) 100%);
            padding: 0.95rem 1.15rem;
            margin: 0.75rem 0 1.1rem;
        }

        /* Run History Card in Sidebar */
        .fc-sidebar-run {
            border: 1px solid var(--fc-border);
            border-radius: 8px;
            background: var(--fc-surface-1);
            padding: 0.65rem 0.75rem;
            margin-bottom: 0.5rem;
            transition: all 0.2s ease;
        }

        .fc-sidebar-run:hover {
            border-color: var(--fc-accent);
            background: var(--fc-accent-glow);
        }

        /* Button Styling Overrides */
        div.stButton > button[kind="primary"],
        div.stDownloadButton > button[kind="primary"] {
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            border: 1px solid rgba(125, 211, 252, 0.4);
            color: #ffffff;
            font-weight: 600;
            border-radius: 6px;
            box-shadow: 0 2px 12px rgba(56, 189, 248, 0.25);
            transition: all 0.2s ease;
        }

        div.stButton > button[kind="primary"]:hover,
        div.stDownloadButton > button[kind="primary"]:hover {
            background: linear-gradient(135deg, #0369a1, #0284c7);
            border-color: #7dd3fc;
            box-shadow: 0 4px 18px rgba(56, 189, 248, 0.4);
            color: #ffffff;
        }

        /* Export CTA Box */
        .fc-export-cta {
            border: 1px solid rgba(56, 189, 248, 0.4);
            border-radius: 12px;
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(14, 116, 144, 0.15));
            padding: 1.5rem 1.8rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# API Client Helpers
# ---------------------------------------------------------------------------


def _api_get(path: str):
    return requests.get(f"{API_BASE_URL}{path}", timeout=30)


def _api_post(path: str, **kwargs):
    return requests.post(f"{API_BASE_URL}{path}", timeout=30, **kwargs)


def _api_reachable() -> bool:
    try:
        return _api_get("/health").status_code == 200
    except requests.exceptions.RequestException:
        return False


# ---------------------------------------------------------------------------
# Data & Formatting Helpers (Tested by PyTest)
# ---------------------------------------------------------------------------


def _format_source_location(location: dict[str, Any] | None) -> str:
    if not location:
        return "Workbook"
    if location.get("sheet_name") and location.get("column_letter") and location.get("row"):
        return f"{location['sheet_name']}!{location['column_letter']}{location['row']}"
    if location.get("source") == "inline":
        return "Direct input"
    return "Workbook"


def _candidate_by_index(req: dict[str, Any], index: int) -> dict[str, Any] | None:
    return next((c for c in req.get("candidates", []) if c.get("index") == index), None)


def _recommended_candidate(req: dict[str, Any]) -> dict[str, Any] | None:
    return _candidate_by_index(req, req.get("recommended_index", -1))


def _review_reasons(req: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    score = float(req.get("recommended_score", 0.0))
    threshold = float(req.get("compliance_threshold", 80.0))
    recommended = _recommended_candidate(req)

    if score < threshold:
        reasons.append(f"Recommended score {score:.1f} is below the {threshold:.1f} review threshold.")
    if recommended and recommended.get("has_invented_number"):
        reasons.append("The recommended candidate contains a number not present in the original text.")
    if req.get("vague_term_suggestions"):
        reasons.append("One or more vague terms still require an engineer-supplied value or limit.")
    if not reasons and req.get("needs_human_review"):
        reasons.append("The backend marked this requirement for manual review.")
    return reasons


def _friendly_error_summary(error_message: str | None) -> tuple[str, list[str]]:
    if not error_message:
        return "The backend stopped before it could finish this review.", [
            "Check the local API terminal for the full stack trace.",
            "Start a new review after the local model service is healthy.",
        ]

    lower = error_message.lower()
    model_name = SETTINGS["ollama"]["model"]

    if "not found" in lower or "404" in lower:
        return f"The configured Ollama model '{model_name}' was not found locally.", [
            f"Run `ollama pull {model_name}` in your PowerShell/Command terminal.",
            "Ensure Ollama is running in the background (`ollama serve`).",
            "Click 'Start new review' in the sidebar to reprocess your workbook.",
        ]

    if (
        "cuda" in lower
        or "llama-server" in lower
        or "ollama" in lower
        or "responseerror" in lower
    ):
        return "The local Ollama model failed while generating requirement candidates.", [
            f"Restart Ollama (`ollama serve`) and confirm `{model_name}` can run locally.",
            "If this machine has limited GPU memory, try running Ollama on CPU or configuring a smaller local model.",
            "Reprocess the workbook after Ollama responds normally.",
        ]

    if "failed to parse" in lower or "parse" in lower:
        return "The spreadsheet could not be parsed into requirement rows.", [
            "Confirm the upload is a valid `.xlsx` workbook.",
            "Check for a readable requirement column and remove corrupt sheets or formulas.",
        ]

    return "The backend reported an error while processing this workbook.", [
        "Review the technical details below, then retry after correcting the local issue.",
    ]


def _error_label(error_message: str | None) -> str:
    if not error_message:
        return "No backend detail was recorded"
    return error_message.strip()


def _build_review_metrics(requirements: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    processed = len(requirements)
    need_review = sum(1 for req in requirements if req.get("needs_human_review"))
    passed = processed - need_review
    scores = [float(req.get("recommended_score", 0.0)) for req in requirements]
    avg_score = mean(scores) if scores else 0.0

    confidences = [
        float(req.get("ears_pattern", {}).get("confidence", 0.0)) for req in requirements
    ]
    avg_confidence = mean(confidences) if confidences else 1.0

    total = run.get("total_requirements") or processed
    return {
        "processed": processed,
        "total": total,
        "passed": passed,
        "need_review": need_review,
        "avg_score": avg_score,
        "avg_confidence": avg_confidence,
        "accepted": passed,
    }


def _build_summary_table(requirements: list[dict]) -> pd.DataFrame:
    rows = []
    for req in requirements:
        candidates = {c["index"]: c for c in req.get("candidates", [])}
        recommended_idx = req.get("recommended_index", 0)
        row = {
            "#": req.get("sequence_in_run", 0) + 1,
            "Source": _format_source_location(req.get("source_location")),
            "Original Requirement": req.get("original_text", ""),
            "EARS Pattern": req.get("ears_pattern", {}).get("pattern", ""),
            "Recommended Score": float(req.get("recommended_score", 0.0)),
        }
        for i in range(3):
            candidate = candidates.get(i)
            if candidate is None:
                row[f"Candidate {i + 1}"] = ""
                continue
            marker = RECOMMENDED_MARKER if i == recommended_idx else ""
            row[f"Candidate {i + 1}"] = (
                f"{marker}{candidate.get('rewritten_text', '')} (score: {candidate.get('score', 0.0):.1f})"
            )
        row["Needs Review"] = "Yes" if req.get("needs_human_review") else "No"
        row["Suggestions"] = (
            "; ".join(f"{s['term']}: {s['suggestion']}" for s in req.get("vague_term_suggestions", []))
            or "(none)"
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _highlight_needs_review(row: pd.Series) -> list[str]:
    color = NEEDS_REVIEW_COLOR if row["Needs Review"] == "Yes" else OK_COLOR
    return [f"background-color: {color}"] * len(row)


def _highlight_changed_words(original: str, candidate: str) -> str:
    original_words = original.split()
    candidate_words = candidate.split()
    matcher = SequenceMatcher(a=original_words, b=candidate_words)
    html_parts: list[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        words = [escape(word) for word in candidate_words[j1:j2]]
        if not words:
            continue
        text = " ".join(words)
        if tag == "equal":
            html_parts.append(text)
        else:
            html_parts.append(f'<span class="fc-change">{text}</span>')
    return " ".join(html_parts)


# ---------------------------------------------------------------------------
# Sidebar Console & History Component
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Flight Review Console")
        st.caption("DRDO AI Requirements Standardization Engine")

        st.markdown(
            """
            <div class="fc-badges" style="margin-bottom: 0.8rem;">
              <span class="fc-badge green">● Offline Guard</span>
              <span class="fc-badge blue">Loopback API</span>
              <span class="fc-badge purple">SQLite Persistence</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(f"**Ollama Model:** `{SETTINGS['ollama']['model']}`")
        st.markdown(f"**API Host:** `{API_BASE_URL}`")

        st.divider()

        if st.button("Start new review", icon=":material/refresh:", width="stretch"):
            for key in ("run_id", "selected_requirement", "last_uploaded_name", "search_query", "review_filter"):
                st.session_state.pop(key, None)
            st.rerun()

        st.markdown("#### Previous Runs")
        try:
            runs = _api_get("/runs").json()
        except requests.exceptions.RequestException:
            st.warning("Can't reach the API to list previous runs.", icon=":material/error:")
            return

        if not runs:
            st.caption("No persisted runs.")
            return

        for run in reversed(runs):
            status = run.get("status", "unknown")
            icon = {
                "completed": "🟢",
                "failed": "🔴",
                "processing": "🟡",
                "pending": "⏳",
            }.get(status, "📄")

            req_count = run.get("requirement_count", 0)
            file_name = run.get("file_name", "workbook.xlsx")
            uploaded_at = run.get("uploaded_at", "")
            time_str = uploaded_at.split("T")[1][:5] if "T" in uploaded_at else ""

            label = f"{icon} #{run['id']} | {file_name} | {status}"
            if time_str or req_count:
                label += f" ({req_count} reqs)"

            if st.button(label, key=f"select_run_{run['id']}", width="stretch"):
                st.session_state["run_id"] = run["id"]
                st.rerun()


# ---------------------------------------------------------------------------
# Header & Interactive Pipeline Timeline Rail
# ---------------------------------------------------------------------------


def _render_hero(api_ready: bool) -> None:
    state_badge = (
        '<span class="fc-badge green">System Ready</span>'
        if api_ready
        else '<span class="fc-badge red">API Unavailable</span>'
    )
    st.markdown(
        f"""
        <div class="fc-hero">
          <div class="fc-eyebrow">
            <span>✈️</span> DRDO Defence & Aerospace AI Requirements Engineering Engine
          </div>
          <h1>Flight Controller Requirements Dashboard</h1>
          <p>
            Standardize, audit, and refine flight controller software requirement specifications.
            Automated defect detection, EARS pattern classification, INCOSE rulebook scoring,
            and offline LLM candidate rewriting in a secure, air-gapped environment.
          </p>
          <div class="fc-badges">
            {state_badge}
            <span class="fc-badge blue">.xlsx Workbooks</span>
            <span class="fc-badge green">Local SQLite Trace</span>
            <span class="fc-badge amber">Ollama: {escape(SETTINGS["ollama"]["model"])}</span>
            <span class="fc-badge purple">INCOSE Rulebook v2.0</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_workflow_rail(status: str | None) -> None:
    active_by_status = {
        None: "Upload",
        "pending": "Processing",
        "processing": "Processing",
        "failed": "Processing",
        "completed": "Review",
    }
    active = active_by_status.get(status, "Upload")
    steps = ["Upload", "Processing", "Analysis", "Review", "Export"]
    active_index = steps.index(active)
    completed_until = 0
    if status in {"pending", "processing", "failed"}:
        completed_until = 0
    elif status == "completed":
        completed_until = 3

    html = ['<div class="fc-workflow">']
    for index, step in enumerate(steps):
        css_class = "fc-step"
        icon_str = "○"
        if index < completed_until:
            css_class += " done"
            icon_str = "✓"
        elif index == active_index:
            css_class += " active"
            icon_str = "●"

        helper = {
            "Upload": "Select workbook",
            "Processing": "Local pipeline",
            "Analysis": "EARS + INCOSE",
            "Review": "Engineer decision",
            "Export": "Reviewed file",
        }[step]
        html.append(
            f'<div class="{css_class}">'
            f'<strong><span>{icon_str}</span> {step}</strong>'
            f'<span style="font-size:0.75rem; color:var(--fc-text-muted);">{helper}</span>'
            f'</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_run_context(run: dict[str, Any]) -> None:
    status = run.get("status", "unknown")
    status_class = {
        "completed": "green",
        "failed": "red",
        "processing": "blue",
        "pending": "amber",
    }.get(status, "")
    total = run.get("total_requirements")
    processed = run.get("requirement_count", 0)
    progress = f"{processed}/{total}" if total else f"{processed}"
    st.markdown(
        f"""
        <div class="fc-run-context">
          <div class="fc-section-label">Active Review Session</div>
          <div class="fc-card-title">{escape(run.get('file_name', 'Workbook'))}</div>
          <div class="fc-badges">
            <span class="fc-badge {status_class}">Status: {escape(status)}</span>
            <span class="fc-badge">Requirements: {escape(str(progress))}</span>
            <span class="fc-badge">Run ID: #{escape(str(run.get('id', '')))}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Upload Component
# ---------------------------------------------------------------------------


def _render_upload_section() -> None:
    with st.container(border=True):
        st.markdown("#### Upload Requirements Workbook")
        st.caption(
            "Upload a Microsoft Excel workbook (`.xlsx`) containing flight controller specification statements. "
            "Processing is conducted 100% offline."
        )
        uploaded_file = st.file_uploader(
            "Upload a requirements spreadsheet",
            type=["xlsx"],
            label_visibility="collapsed",
        )

        if uploaded_file is None:
            st.info(
                "Upload a spreadsheet to begin the assistant-guided review.",
                icon=":material/upload_file:",
            )
            return

        file_size_kb = len(uploaded_file.getvalue()) / 1024
        st.markdown(f"**Selected File:** `{uploaded_file.name}`")
        st.caption(f"Size: {file_size_kb:,.1f} KB — Ready for local analysis pipeline.")

        if st.button("Process workbook", type="primary", icon=":material/play_arrow:"):
            with st.spinner("Uploading workbook to local backend..."):
                try:
                    response = _api_post(
                        "/upload",
                        files={
                            "file": (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
                except requests.exceptions.RequestException as exc:
                    st.error(f"Could not reach the API backend at {API_BASE_URL}: {exc}")
                    return

            if response.status_code != 200:
                st.error(f"Upload failed: {response.json().get('detail', response.text)}")
                return

            st.session_state["run_id"] = response.json()["run_id"]
            st.session_state["last_uploaded_name"] = uploaded_file.name
            st.rerun()


# ---------------------------------------------------------------------------
# Progress Monitor Component
# ---------------------------------------------------------------------------


def _render_processing_steps(run: dict[str, Any]) -> None:
    status = run.get("status")
    total = run.get("total_requirements")
    done = run.get("requirement_count", 0)

    steps = [
        ("Reading spreadsheet structure", bool(total) or status == "completed"),
        ("Detecting quality defects", done > 0 or status == "completed"),
        ("EARS pattern classification", done > 0 or status == "completed"),
        ("LLM candidate generation", done > 0 or status == "completed"),
        ("INCOSE scoring & recommendation", done > 0 or status == "completed"),
        ("SQLite trace persistence", status == "completed"),
    ]

    for label, complete in steps:
        icon = ":material/check_circle:" if complete else ":material/radio_button_unchecked:"
        color = "green" if complete else "gray"
        st.markdown(f":{color}-badge[{icon} {label}]")


def _wait_for_run(run_id: int) -> dict | None:
    status_placeholder = st.empty()
    progress_bar = st.progress(0.0)

    while True:
        response = _api_get(f"/runs/{run_id}")
        if response.status_code == 404:
            status_placeholder.error(f"Run {run_id} not found.")
            return None
        run = response.json()

        total = run.get("total_requirements")
        done = run.get("requirement_count", 0)

        with status_placeholder.container():
            if run["status"] == "pending":
                with st.chat_message("assistant", avatar=":material/smart_toy:"):
                    st.write("The workbook is queued on the local backend.")
                st.status("Waiting to start", state="running", expanded=True)
            elif run["status"] == "processing":
                if total:
                    progress_bar.progress(min(done / total, 1.0))
                    with st.chat_message("assistant", avatar=":material/smart_toy:"):
                        st.write(f"I found {total} requirement(s). Processing {done} of {total}.")
                else:
                    with st.chat_message("assistant", avatar=":material/smart_toy:"):
                        st.write("The local backend is reading the spreadsheet and preparing the run.")
                with st.status("Backend workflow", state="running", expanded=True):
                    _render_processing_steps(run)
            elif run["status"] == "completed":
                progress_bar.progress(1.0)
                with st.chat_message("assistant", avatar=":material/smart_toy:"):
                    st.write(f"Review complete. I processed {done} requirement(s).")
                with st.status("Backend workflow", state="complete", expanded=False):
                    _render_processing_steps(run)
                return run
            elif run["status"] == "failed":
                with st.chat_message("assistant", avatar=":material/smart_toy:"):
                    st.write("The local backend could not complete this run.")
                summary, actions = _friendly_error_summary(run.get("error_message"))
                st.error(summary, icon=":material/error:")
                if run.get("error_message"):
                    st.error(
                        f"Backend detail: {_error_label(run.get('error_message'))}",
                        icon=":material/bug_report:",
                    )
                with st.container(border=True):
                    st.markdown("**What to do next**")
                    for action in actions:
                        st.markdown(f"- {action}")
                    with st.expander("Technical details", expanded=True):
                        st.code(run.get("error_message") or "(no backend error message)", language="text")
                return run

        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Results & Executive Dashboard Component
# ---------------------------------------------------------------------------


def _render_metrics(requirements: list[dict[str, Any]], run: dict[str, Any]) -> None:
    metrics = _build_review_metrics(requirements, run)
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.metric("Total Requirements", f"{metrics['processed']}", border=True)
    with c2:
        st.metric("Passed (Auto)", f"{metrics['passed']}", border=True)
    with c3:
        st.metric("Needs Review", f"{metrics['need_review']}", border=True)
    with c4:
        st.metric("Avg INCOSE Score", f"{metrics['avg_score']:.1f}", border=True)
    with c5:
        st.metric("Avg Confidence", f"{metrics['avg_confidence'] * 100:.0f}%", border=True)
    with c6:
        st.metric("Model Status", f"{SETTINGS['ollama']['model']}", border=True)


def _render_review_queue(requirements: list[dict[str, Any]]) -> None:
    st.markdown("### Review queue")
    for req in requirements:
        number = req["sequence_in_run"] + 1
        status = "Needs review" if req.get("needs_human_review") else "Ready"
        with st.expander(f"#{number} | {status} | {req.get('original_text', '')[:96]}"):
            st.markdown(f"**Original:** {req.get('original_text', '')}")
            st.markdown(
                f"**EARS pattern:** {req.get('ears_pattern', {}).get('pattern', 'Unknown')}"
            )
            st.markdown(
                f"**Recommended candidate:** #{req.get('recommended_index', 0) + 1} "
                f"with score {float(req.get('recommended_score', 0.0)):.1f}"
            )
            if req.get("needs_human_review"):
                st.error(
                    "This requirement needs human review before it can be accepted.",
                    icon=":material/report:",
                )
            for reason in _review_reasons(req):
                st.error(reason, icon=":material/report:")
            for suggestion in req.get("vague_term_suggestions", []):
                st.markdown(f"- **{suggestion['term']}**: {suggestion['suggestion']}")


def _render_timeline(requirements: list[dict[str, Any]]) -> None:
    st.markdown("### Conversation timeline")
    st.caption("Each message below is derived from a stored backend requirement trace.")

    for req in requirements:
        number = req["sequence_in_run"] + 1
        pattern = req.get("ears_pattern", {})
        issues = req.get("rule_flags", [])
        recommended_number = req.get("recommended_index", 0) + 1
        score = float(req.get("recommended_score", 0.0))

        with st.chat_message("assistant", avatar=":material/smart_toy:"):
            if req.get("needs_human_review"):
                st.markdown(f"**Requirement #{number} needs attention.**")
            else:
                st.markdown(f"**Requirement #{number} analyzed. No manual review required.**")

            if issues:
                st.markdown("Detected:")
                for issue in issues[:5]:
                    label = issue.get("violation_type", "issue").replace("_", " ")
                    reason = issue.get("reason", "")
                    st.markdown(f"- **{label}:** {reason}")
            else:
                st.markdown("- No rule-detector issues were stored for this requirement.")

            st.markdown(
                f"Recommended candidate #{recommended_number} with INCOSE score **{score:.1f}**."
            )
            st.caption(
                f"EARS pattern: {pattern.get('pattern', 'Unknown')} | "
                f"Confidence: {float(pattern.get('confidence', 0.0)):.2f}"
            )


def _render_defect_chips(issues: list[dict[str, Any]]) -> None:
    """Renders visual chips (🔴 Ambiguous, 🟡 Passive Voice, 🔵 Missing Trigger, 🟣 Compound Statement, 🟢 Good)."""
    if not issues:
        st.markdown(
            '<span class="fc-chip fc-chip-green">🟢 Good Requirement</span>',
            unsafe_allow_html=True,
        )
        return

    html_parts = []
    for issue in issues:
        v_type = (issue.get("violation_type") or "defect").lower()
        reason = escape(issue.get("reason", "Defect detected"))
        if "ambigu" in v_type or "vague" in v_type:
            html_parts.append(f'<span class="fc-chip fc-chip-red" title="{reason}">🔴 Ambiguous: {reason}</span>')
        elif "passive" in v_type:
            html_parts.append(f'<span class="fc-chip fc-chip-yellow" title="{reason}">🟡 Passive Voice: {reason}</span>')
        elif "trigger" in v_type or "missing" in v_type or "event" in v_type:
            html_parts.append(f'<span class="fc-chip fc-chip-blue" title="{reason}">🔵 Missing Trigger: {reason}</span>')
        elif "compound" in v_type or "multiple" in v_type:
            html_parts.append(f'<span class="fc-chip fc-chip-purple" title="{reason}">🟣 Compound Statement: {reason}</span>')
        else:
            html_parts.append(f'<span class="fc-chip fc-chip-yellow" title="{reason}">🟡 {escape(v_type)}: {reason}</span>')

    st.markdown(" ".join(html_parts), unsafe_allow_html=True)


def _render_requirement_card(req: dict[str, Any]) -> None:
    number = req["sequence_in_run"] + 1
    req_key = req.get("id", f"seq_{req['sequence_in_run']}")
    needs_review = req.get("needs_human_review", False)
    pattern = req.get("ears_pattern", {})
    issues = req.get("rule_flags", [])
    recommended_idx = req.get("recommended_index", 0)

    with st.container(border=True):
        status_badge = (
            '<span class="fc-badge amber">Human Review Recommended</span>'
            if needs_review
            else '<span class="fc-badge green">Ready for Export</span>'
        )
        st.markdown(
            f"""
            <div class="fc-requirement {'review' if needs_review else ''}">
              <div class="fc-section-label">Requirement #{number}</div>
              <div class="fc-card-title">{escape(req.get('original_text', ''))}</div>
              <div class="fc-badges">
                {status_badge}
                <span class="fc-badge blue">EARS: {escape(pattern.get('pattern', 'Unknown'))}</span>
                <span class="fc-badge">INCOSE Score: {float(req.get('recommended_score', 0.0)):.1f}</span>
                <span class="fc-badge">Source: {escape(_format_source_location(req.get('source_location')))}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        top_left, top_right = st.columns([1, 1])
        with top_left:
            st.markdown("**Detected Issues**")
            _render_defect_chips(issues)
            if issues:
                for issue in issues:
                    label = issue.get("violation_type", "issue").replace("_", " ")
                    st.warning(
                        f"{label}: {issue.get('reason', 'No reason stored.')}",
                        icon=":material/warning:",
                    )
            else:
                st.success("No stored rule-detector issues.", icon=":material/check_circle:")

        with top_right:
            st.markdown("**Recommendation Rationale**")
            st.write(
                f"Candidate #{recommended_idx + 1} was selected by the deterministic scorer "
                f"with INCOSE score {float(req.get('recommended_score', 0.0)):.1f}."
            )
            if pattern.get("reason"):
                st.caption(f"EARS rationale: {pattern['reason']}")
            if needs_review:
                st.error(
                    "This requirement needs human review before it can be accepted.",
                    icon=":material/report:",
                )
            for reason in _review_reasons(req):
                st.error(reason, icon=":material/report:")

        st.markdown("**Generated Candidates**")
        cols = st.columns(3)
        for i, column in enumerate(cols):
            candidate = _candidate_by_index(req, i)
            if candidate is None:
                continue
            with column:
                is_recommended = i == recommended_idx
                with st.container(border=True, height="stretch"):
                    badge = ":green-badge[⭐ Recommended]" if is_recommended else ":blue-badge[Alternative]"
                    st.markdown(f"**Candidate {i + 1}** {badge}")
                    st.metric("INCOSE Score", f"{float(candidate.get('score', 0.0)):.1f}", border=False)
                    st.write(candidate.get("rewritten_text", ""))
                    if candidate.get("has_invented_number"):
                        st.warning(
                            "Contains a number not present in the original.",
                            icon=":material/warning:",
                        )
                    failed_rules = candidate.get("failed_rules", [])
                    if failed_rules:
                        with st.expander("Failed rules", icon=":material/rule:"):
                            for rule in failed_rules:
                                st.markdown(
                                    f"- **{rule.get('id', '')} {rule.get('title', '')}:** "
                                    f"{'; '.join(rule.get('reasons', []))}"
                                )

        if req.get("vague_term_suggestions"):
            st.markdown("**Human Reviewer Suggestions**")
            for suggestion in req["vague_term_suggestions"]:
                st.info(
                    f"{suggestion['term']}: {suggestion['suggestion']}",
                    icon=":material/edit_note:",
                )

        with st.container(border=True):
            st.markdown(f"**Original:** {req.get('original_text', '')}")
            st.markdown(f"**EARS pattern:** {pattern.get('pattern', 'Unknown')}")
            st.markdown(f"**Recommended candidate:** #{recommended_idx + 1}")
            st.markdown(
                f"**Needs human review:** {'Yes' if needs_review else 'No'}"
            )

        with st.container(horizontal=True):
            st.button(
                "Accept recommendation",
                key=f"accept_{req_key}",
                icon=":material/check:",
                disabled=needs_review,
            )
            st.button(
                "Reject / Request edit",
                key=f"reject_{req_key}",
                icon=":material/close:",
            )
            st.button(
                "Compare candidates",
                key=f"compare_{req_key}",
                icon=":material/compare_arrows:",
                on_click=lambda req_id=req_key: st.session_state.update(
                    selected_requirement=req_id
                ),
            )


def _render_cards(requirements: list[dict[str, Any]]) -> None:
    st.markdown("### Requirement cards")
    review_filter = st.segmented_control(
        "Review filter",
        options=["All", "Needs review", "Ready"],
        default="All",
        key="review_filter",
    )

    filtered = requirements
    if review_filter == "Needs review":
        filtered = [req for req in requirements if req.get("needs_human_review")]
    elif review_filter == "Ready":
        filtered = [req for req in requirements if not req.get("needs_human_review")]

    if not filtered:
        st.caption("No requirements match this filter.")
        return

    for req in filtered:
        _render_requirement_card(req)


def _render_comparison(requirements: list[dict[str, Any]]) -> None:
    if not requirements:
        st.caption("No requirements available for comparison.")
        return

    ids = {f"#{req['sequence_in_run'] + 1}": req for req in requirements}
    selected_id = st.session_state.get("selected_requirement")
    default_label = next(iter(ids))
    for label, req in ids.items():
        req_key = req.get("id", f"seq_{req['sequence_in_run']}")
        if req_key == selected_id:
            default_label = label
            break

    label = st.selectbox(
        "Requirement",
        options=list(ids.keys()),
        index=list(ids.keys()).index(default_label),
    )
    req = ids[label]
    original = req.get("original_text", "")
    recommended_idx = req.get("recommended_index", 0)

    st.markdown("### Side-by-side comparison")
    cols = st.columns(4)
    with cols[0]:
        with st.container(border=True, height="stretch"):
            st.markdown("**Original Requirement**")
            st.markdown(f'<div class="fc-text-box mono">{escape(original)}</div>', unsafe_allow_html=True)

    for i in range(3):
        candidate = _candidate_by_index(req, i)
        with cols[i + 1]:
            with st.container(border=True, height="stretch"):
                recommended = " :green-badge[⭐ Recommended]" if i == recommended_idx else ""
                st.markdown(f"**Candidate {i + 1}**{recommended}")
                if candidate:
                    highlighted = _highlight_changed_words(original, candidate.get("rewritten_text", ""))
                    st.markdown(
                        f'<div class="fc-text-box">{highlighted}</div>',
                        unsafe_allow_html=True,
                    )
                    st.metric(
                        "INCOSE Score",
                        f"{float(candidate.get('score', 0.0)):.1f}",
                        border=False,
                    )

    st.caption("Highlighted words differ from the original requirement statement.")


def _render_table(requirements: list[dict[str, Any]]) -> None:
    st.markdown("### Audit table")
    st.caption(f"{RECOMMENDED_MARKER.strip()} marks the recommended candidate.")
    table = _build_summary_table(requirements)
    styled = table.style.apply(_highlight_needs_review, axis=1)
    st.dataframe(
        styled,
        hide_index=True,
        column_config={
            "Recommended Score": st.column_config.ProgressColumn(
                "Recommended score",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
        },
    )


def _render_download_section(run_id: int, requirements: list[dict[str, Any]], run: dict[str, Any]) -> None:
    metrics = _build_review_metrics(requirements, run)

    st.markdown("### Review Complete & Export")
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="fc-export-cta">
              <div class="fc-section-label">DRDO Specification Export Center</div>
              <h3 style="margin-top:0; color:var(--fc-text-primary);">Download Reviewed Excel Specification</h3>
              <p style="color:var(--fc-text-secondary);">
                Processed <strong>{metrics['processed']}</strong> flight controller requirement statements. 
                <strong>{metrics['passed']}</strong> are ready for deployment export and 
                <strong>{metrics['need_review']}</strong> are flagged for engineer manual review.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        try:
            response = _api_get(f"/runs/{run_id}/download")
        except requests.exceptions.RequestException as exc:
            st.error(f"Could not reach the API backend: {exc}")
            return

        if response.status_code != 200:
            st.warning("Result file isn't ready to download yet.", icon=":material/pending:")
            return

        file_size_kb = len(response.content) / 1024
        st.caption(f"Export Package: `run_{run_id}_review.xlsx` | Size: {file_size_kb:,.1f} KB")

        with st.container(horizontal=True):
            st.download_button(
                "Download Excel Specification",
                data=response.content,
                file_name=f"run_{run_id}_review.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                icon=":material/download:",
            )
            if st.button("Start new review", icon=":material/refresh:"):
                st.session_state.pop("run_id", None)
                st.session_state.pop("selected_requirement", None)
                st.rerun()


def _render_results(requirements: list[dict], run: dict[str, Any] | None = None) -> None:
    run = run or {}
    metrics = _build_review_metrics(requirements, run)

    st.markdown("## Engineering Dashboard")
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        st.write(
            f"I completed analysis for {metrics['processed']} flight controller requirement(s). "
            f"{metrics['need_review']} require manual engineer attention."
        )

    _render_metrics(requirements, run)
    _render_review_queue(requirements)

    timeline, cards, compare, table, export = st.tabs(
        [
            ":material/timeline: Timeline",
            ":material/view_agenda: Requirement cards",
            ":material/compare_arrows: Compare",
            ":material/table_chart: Audit table",
            ":material/download: Export Center",
        ]
    )

    with timeline:
        _render_timeline(requirements)
    with cards:
        _render_cards(requirements)
    with compare:
        _render_comparison(requirements)
    with table:
        _render_table(requirements)
    with export:
        run_id = st.session_state.get("run_id")
        if run_id is None:
            st.warning("Select a completed run before exporting.", icon=":material/info:")
        else:
            _render_download_section(int(run_id), requirements, run)


# ---------------------------------------------------------------------------
# Main Application Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    _inject_css()
    _ = st.session_state.setdefault("selected_requirement", None)

    api_ready = _api_reachable()
    if api_ready:
        _render_sidebar()
    _render_hero(api_ready)

    if not api_ready:
        st.error(
            f"Can't reach the API backend at {API_BASE_URL}. Start it with "
            "`scripts\\run_api.ps1` first.",
            icon=":material/error:",
        )
        return

    run_id = st.session_state.get("run_id")
    if run_id is None:
        _render_workflow_rail(None)
        _render_upload_section()
        return

    rail_slot = st.empty()
    context_slot = st.empty()
    run_response = _api_get(f"/runs/{run_id}")
    if run_response.status_code == 200:
        current_run = run_response.json()
        with rail_slot.container():
            _render_workflow_rail(current_run.get("status"))
        with context_slot.container():
            _render_run_context(current_run)
    else:
        with rail_slot.container():
            _render_workflow_rail("failed")

    st.caption(f"Session refreshed at {datetime.now().strftime('%H:%M:%S')}.")
    run = _wait_for_run(int(run_id))
    if run is not None:
        with rail_slot.container():
            _render_workflow_rail(run.get("status"))
        with context_slot.container():
            _render_run_context(run)
    if run is None or run["status"] != "completed":
        return

    requirements_response = _api_get(f"/runs/{run_id}/requirements")
    if requirements_response.status_code != 200:
        st.error("Could not load results for this run.", icon=":material/error:")
        return

    _render_results(requirements_response.json(), run)


if __name__ == "__main__":
    main()

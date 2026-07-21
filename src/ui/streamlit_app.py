"""Streamlit frontend for the Flight Controller Requirements Agent.

Deliberately simple: upload a spreadsheet, watch it process, review the
3 candidates per requirement (recommended one clearly marked, needs-review
rows highlighted with suggestions inline), download the reviewed Excel.
No auth, no client-side state beyond one run_id -- this is a thin client
over src/ui/api.py, which does all the real work.

Talks to the API over loopback only (127.0.0.1), matching this project's
offline requirement (README.md) -- never any other host.

Run it:
    streamlit run src/ui/streamlit_app.py
(scripts/run_api.ps1 must already be running the backend.)
"""

from __future__ import annotations

import time

import pandas as pd
import requests
import streamlit as st

from config import get_settings

_API_PORT = get_settings()["ui"]["api_port"]
# Always loopback: config's ui.api_host is a *bind* address (0.0.0.0 is
# valid there), but a client must connect to a real address, and 127.0.0.1
# reaches a same-machine server no matter which interface it bound to.
API_BASE_URL = f"http://127.0.0.1:{_API_PORT}"

NEEDS_REVIEW_COLOR = "#ffc7ce"  # matches src/storage/db.py's Excel export palette
OK_COLOR = "#c6efce"
POLL_INTERVAL_SECONDS = 1.5

st.set_page_config(page_title="Flight Controller Requirements Agent", layout="wide")
st.title("Flight Controller Requirements Agent")
st.caption("Upload a requirements spreadsheet, review the rewrite candidates, download the result.")


# ---------------------------------------------------------------------------
# API client helpers
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
# Sidebar: past runs
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    st.sidebar.header("Previous runs")
    try:
        runs = _api_get("/runs").json()
    except requests.exceptions.RequestException:
        st.sidebar.warning("Can't reach the API to list previous runs.")
        return

    if not runs:
        st.sidebar.caption("No runs yet.")
        return

    for run in reversed(runs):
        label = f"#{run['id']} · {run['file_name']} · {run['status']}"
        if st.sidebar.button(label, key=f"select_run_{run['id']}"):
            st.session_state["run_id"] = run["id"]
            st.rerun()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _render_upload_section() -> None:
    uploaded_file = st.file_uploader("Upload requirements spreadsheet (.xlsx)", type=["xlsx"])
    if uploaded_file is None:
        return

    if st.button("Process", type="primary"):
        with st.spinner("Uploading..."):
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
        st.rerun()


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def _wait_for_run(run_id: int) -> dict | None:
    """Blocks (with a visible progress bar) until the run reaches a
    terminal status, then returns the final run record. Returns None if
    the run disappeared (e.g. a stale run_id from a wiped database)."""
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

        if run["status"] == "pending":
            status_placeholder.info("Waiting to start...")
        elif run["status"] == "processing":
            if total:
                progress_bar.progress(min(done / total, 1.0))
                status_placeholder.info(f"Processing... {done}/{total} requirements")
            else:
                status_placeholder.info("Parsing spreadsheet...")
        elif run["status"] == "completed":
            progress_bar.progress(1.0)
            status_placeholder.success(f"Done — processed {done} requirement(s).")
            return run
        elif run["status"] == "failed":
            status_placeholder.error(f"Run failed: {run.get('error_message')}")
            return run

        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Results table + per-requirement detail
# ---------------------------------------------------------------------------


def _build_summary_table(requirements: list[dict]) -> pd.DataFrame:
    rows = []
    for req in requirements:
        candidates = {c["index"]: c for c in req["candidates"]}
        recommended_idx = req["recommended_index"]
        row = {
            "#": req["sequence_in_run"] + 1,
            "Original Requirement": req["original_text"],
            "EARS Pattern": req["ears_pattern"].get("pattern", ""),
        }
        for i in range(3):
            candidate = candidates.get(i)
            if candidate is None:
                row[f"Candidate {i + 1}"] = ""
                continue
            marker = "⭐ " if i == recommended_idx else ""
            row[f"Candidate {i + 1}"] = f"{marker}{candidate['rewritten_text']} (score: {candidate['score']:.1f})"
        row["Needs Review"] = "Yes" if req["needs_human_review"] else "No"
        row["Suggestions"] = (
            "; ".join(f"{s['term']}: {s['suggestion']}" for s in req["vague_term_suggestions"])
            or "(none)"
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _highlight_needs_review(row: pd.Series) -> list[str]:
    color = NEEDS_REVIEW_COLOR if row["Needs Review"] == "Yes" else OK_COLOR
    return [f"background-color: {color}"] * len(row)


def _render_results(requirements: list[dict]) -> None:
    st.subheader("Results")
    st.caption("⭐ marks the recommended candidate. Rows needing human review are highlighted.")

    table = _build_summary_table(requirements)
    styled = table.style.apply(_highlight_needs_review, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.subheader("Per-requirement detail")
    for req in requirements:
        needs_review = req["needs_human_review"]
        badge = "🔴 NEEDS REVIEW" if needs_review else "🟢 OK"
        with st.expander(f"#{req['sequence_in_run'] + 1}  {badge}  —  {req['original_text'][:80]}"):
            st.markdown(f"**Original:** {req['original_text']}")
            st.markdown(f"**EARS pattern (first guess):** {req['ears_pattern'].get('pattern', '')}")

            recommended_idx = req["recommended_index"]
            columns = st.columns(3)
            for i, column in enumerate(columns):
                candidate = next((c for c in req["candidates"] if c["index"] == i), None)
                if candidate is None:
                    continue
                with column:
                    is_recommended = i == recommended_idx
                    label = f"{'⭐ Recommended' if is_recommended else f'Alternate {i + 1}'}"
                    st.markdown(f"**{label}**  (score: {candidate['score']:.1f})")
                    if is_recommended:
                        st.success(candidate["rewritten_text"])
                    else:
                        st.info(candidate["rewritten_text"])
                    if candidate.get("has_invented_number"):
                        st.warning("Contains a number not present in the original — flagged, not trusted.")

            if req["vague_term_suggestions"]:
                st.markdown("**Suggestions for a human reviewer:**")
                for suggestion in req["vague_term_suggestions"]:
                    st.markdown(f"- **{suggestion['term']}**: {suggestion['suggestion']}")

            if needs_review:
                st.error("This requirement needs human review before it can be accepted.")


def _render_download_section(run_id: int) -> None:
    try:
        response = _api_get(f"/runs/{run_id}/download")
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not reach the API backend: {exc}")
        return

    if response.status_code != 200:
        st.warning("Result file isn't ready to download yet.")
        return

    st.download_button(
        "Download reviewed spreadsheet",
        data=response.content,
        file_name=f"run_{run_id}_review.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> None:
    if not _api_reachable():
        st.error(
            f"Can't reach the API backend at {API_BASE_URL}. Start it with "
            "`scripts\\run_api.ps1` first."
        )
        return

    _render_sidebar()
    _render_upload_section()

    run_id = st.session_state.get("run_id")
    if run_id is None:
        st.info("Upload a spreadsheet above to get started.")
        return

    run = _wait_for_run(run_id)
    if run is None or run["status"] != "completed":
        return

    requirements_response = _api_get(f"/runs/{run_id}/requirements")
    if requirements_response.status_code != 200:
        st.error("Could not load results for this run.")
        return

    _render_results(requirements_response.json())
    _render_download_section(run_id)


if __name__ == "__main__":
    main()

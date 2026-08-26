"""Wires the end-to-end requirement-rewriting pipeline as a LangGraph:

    Parse -> RuleFlag -> ClassifyPattern -> AbbreviationCheck -> ComplianceCheck -+-> GenerateCandidates -> ScoreAndRecommend -> Finalize
                                                                                   +-> RejectNonEars

- Parse: src/ingestion/parser.py -- either extracts a candidate requirement
  from an .xlsx file (given file_path + cell_reference), or normalizes an
  already-extracted requirement string (given requirement_text directly,
  which is how every test in this module and any caller that already ran
  parse_workbook itself drives the graph).
- RuleFlag: src/rules/detectors.py's run_all_detectors -- deterministic,
  no LLM.
- ClassifyPattern: src/rules/ears_classifier.py's classify_ears_pattern --
  deterministic keyword classifier, no LLM. Also distinguishes "wrong modal
  verb" (will/must/should/may used instead of "shall") from genuinely
  unstructured text, so a rejection names the specific fix needed rather
  than a generic "unclear".
- AbbreviationCheck: deterministic, no LLM. Runs INCOSE R37 (Acronyms) and
  R38 (Abbreviations) -- via src/rules/incose_scorer.py's
  check_abbreviations() -- against the original text. Acronyms in
  data/rules/known_abbreviations.json (GPS, INS, IMU, ...) are treated as
  already defined by domain convention. Deliberately ADVISORY, not a
  pre-LLM gate: findings are folded into rule_flags as quality flags a
  human reviewer sees (same as RuleFlag's), not a rejection -- a fixed
  allowlist can never keep up with a real, large requirement corpus, and
  gating on it was measured to wrongly reject ~14% of
  data/golden/fewshot.json's 150 real examples (HVAC, PLC, ARINC, SCADA,
  ABS, GUI, ... none of them in any reasonable allowlist), which is
  exactly the false-positive problem this feature exists to avoid.
- ComplianceCheck: deterministic gate, no LLM. Gates on ClassifyPattern's
  structural verdict only -- confirmed 0 false rejections against both
  data/golden/eval.json and fewshot.json. If ClassifyPattern couldn't
  confidently match a recognized EARS template (UNCLEAR_LABEL), the
  requirement is rejected outright, routed straight to RejectNonEars and
  never reaching GenerateCandidates, instead of spending an Ollama call on
  text that isn't structured as EARS to begin with. Only a requirement
  that clears this gate reaches the LLM.
- GenerateCandidates: src/llm/local_llm_client.py + src/pipeline/
  candidate_generator.py -- the only node that talks to Ollama. The
  RuleFlag flags and ClassifyPattern's guess both feed into the prompt
  (src/llm/prompts.py, via candidate_generator -> build_prompt). Generates
  all 3 candidates concurrently (threads) rather than one call at a time --
  each is an independent, blocking HTTP call to Ollama, so this is a real
  speedup whenever Ollama can service more than one request at a time.
- ScoreAndRecommend: src/pipeline/recommender.py -- deterministic INCOSE
  scoring of all 3 candidates, no LLM.
- Finalize: assembles the public result and decides needs_human_review by
  comparing the recommended candidate's score against a configurable
  compliance_threshold (config/settings.yaml's pipeline.compliance_threshold)
  -- a low-scoring "best of 3" is not presented as a confident
  recommendation.
- RejectNonEars: ComplianceCheck's rejection branch. Assembles the same
  public result shape as Finalize (so every caller/consumer -- src/ui/api.py,
  src/storage/db.py, the frontend -- handles it identically) but with
  candidates=[] and recommended_index=-1 as the signal that no LLM rewrite
  was attempted; recommended_text falls back to the original text, and
  recommended_score is the original text's own deterministic INCOSE score
  (still no LLM involved) so a real number is still shown. The specific
  rejection reason is carried in the result's existing ears_pattern.reason
  field.

Only GenerateCandidates requires a reachable Ollama instance; every other
node is pure/offline, so build_graph() itself never touches the network --
only invoking a compiled graph through GenerateCandidates does.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from config import get_settings
from ingestion.parser import parse_workbook
from llm.local_llm_client import LocalLLMClient
from pipeline.candidate_generator import Candidate, generate_candidates
from pipeline.recommender import RecommendationResult, recommend
from rules.detectors import run_all_detectors
from rules.ears_classifier import UNCLEAR_LABEL, classify_ears_pattern
from rules.incose_scorer import check_abbreviations, score_requirement

DEFAULT_COMPLIANCE_THRESHOLD = 80.0


class PipelineState(TypedDict, total=False):
    # --- input (caller supplies one of these two shapes) ---
    requirement_text: str
    source_location: dict
    file_path: str
    cell_reference: str

    # --- Parse ---
    original_text: str

    # --- RuleFlag ---
    rule_flags: list[dict]

    # --- ClassifyPattern ---
    ears_classification: dict

    # --- AbbreviationCheck ---
    abbreviation_issues: list[str]

    # --- ComplianceCheck ---
    ears_compliant: bool
    rejection_reason: str

    # --- GenerateCandidates ---
    candidates_raw: list[Candidate]

    # --- ScoreAndRecommend ---
    recommendation: RecommendationResult

    # --- Finalize / RejectNonEars ---
    result: dict
    needs_human_review: bool


# ---------------------------------------------------------------------------
# Node: Parse
# ---------------------------------------------------------------------------


def parse_node(state: PipelineState) -> dict:
    # `in` + `is not None`, not truthiness: an empty string is a legitimate
    # (if degenerate) direct-text input and must not fall through to the
    # file_path branch just because "" is falsy.
    if "requirement_text" in state and state["requirement_text"] is not None:
        return {
            "original_text": state["requirement_text"],
            "source_location": state.get("source_location") or {"source": "inline"},
        }

    file_path = state.get("file_path")
    if not file_path:
        raise ValueError(
            "Parse needs either state['requirement_text'] (a requirement string) or "
            "state['file_path'] (an .xlsx to parse via src/ingestion/parser.py)."
        )

    parse_result = parse_workbook(file_path)
    if parse_result.issues:
        raise ValueError(f"Failed to parse {file_path}: {parse_result.issues}")

    cell_reference = state.get("cell_reference")
    if cell_reference:
        matches = [
            c for c in parse_result.candidates if c.location.cell_reference == cell_reference
        ]
        if not matches:
            raise ValueError(f"No candidate requirement found at {cell_reference} in {file_path}")
        chosen = matches[0]
    else:
        if len(parse_result.candidates) != 1:
            raise ValueError(
                f"{file_path} contains {len(parse_result.candidates)} candidate requirements; "
                "set state['cell_reference'] to select one -- this graph processes one "
                "requirement per run (see run_workbook() to process a whole file)."
            )
        chosen = parse_result.candidates[0]

    return {"original_text": chosen.text, "source_location": asdict(chosen.location)}


# ---------------------------------------------------------------------------
# Node: RuleFlag
# ---------------------------------------------------------------------------


def rule_flag_node(state: PipelineState) -> dict:
    findings = run_all_detectors(state["original_text"])
    return {"rule_flags": [asdict(f) for f in findings]}


# ---------------------------------------------------------------------------
# Node: ClassifyPattern
# ---------------------------------------------------------------------------


def classify_pattern_node(state: PipelineState) -> dict:
    classification = classify_ears_pattern(state["original_text"])
    return {
        "ears_classification": {
            "pattern": classification.pattern,
            "confidence": classification.confidence,
            "matched_keywords": list(classification.matched_keywords),
            "reason": classification.reason,
        }
    }


# ---------------------------------------------------------------------------
# Node: AbbreviationCheck -- INCOSE R37 (Acronyms) + R38 (Abbreviations)
# against the original text, no LLM. Advisory only, does NOT gate
# GenerateCandidates (see ComplianceCheck below for why) -- findings are
# folded into rule_flags as quality flags a human reviewer sees, same as
# RuleFlag's findings, rather than blocking the requirement outright.
# ---------------------------------------------------------------------------


def abbreviation_check_node(state: PipelineState) -> dict:
    issues = check_abbreviations(state["original_text"])
    advisory_flags = [
        {
            "violation_type": "undefined_acronym_or_abbreviation",
            "span": "",
            "start": 0,
            "end": 0,
            "confidence": 0.6,
            "reason": issue,
        }
        for issue in issues
    ]
    return {
        "abbreviation_issues": issues,
        "rule_flags": state["rule_flags"] + advisory_flags,
    }


# ---------------------------------------------------------------------------
# Node: ComplianceCheck -- the EARS compliance gate, run before any LLM call.
# Gates on ClassifyPattern's structural verdict ONLY -- confirmed safe by
# checking it against both golden datasets (0 false rejections on either).
#
# AbbreviationCheck's findings are deliberately NOT part of this gate: a
# fixed allowlist of "known" acronyms can never keep up with a real, large
# requirement corpus. Measured against data/golden/fewshot.json (150 real
# examples), gating on undefined acronyms would wrongly reject ~14% of
# them (HVAC, PLC, ARINC, SCADA, ABS, GUI, ...) -- exactly the
# false-positive problem this feature exists to avoid. So it stays
# advisory (see AbbreviationCheck above) rather than a hard block.
# ---------------------------------------------------------------------------


def compliance_check_node(state: PipelineState) -> dict:
    classification = state["ears_classification"]
    if classification["pattern"] == UNCLEAR_LABEL:
        return {"ears_compliant": False, "rejection_reason": classification["reason"]}
    return {"ears_compliant": True, "rejection_reason": ""}


def _route_after_compliance_check(state: PipelineState) -> str:
    return "generate" if state["ears_compliant"] else "reject"


# ---------------------------------------------------------------------------
# Node: RejectNonEars -- ComplianceCheck's rejection branch (no LLM call)
# ---------------------------------------------------------------------------


def _make_reject_node(compliance_threshold: float):
    def reject_node(state: PipelineState) -> dict:
        original_text = state["original_text"]
        # Still a real, deterministic INCOSE score for the original text --
        # just never rewritten, since it was rejected before GenerateCandidates.
        score_result = score_requirement(original_text)

        # Reuse ears_pattern's existing, already-persisted "reason" field to
        # carry the specific rejection reason (EARS structure OR abbreviation
        # issue -- whichever ComplianceCheck actually rejected on) rather than
        # adding a new result/DB column for it. ClassifyPattern's own
        # ``pattern`` value is kept as-is: a requirement can be structurally
        # a real EARS pattern (e.g. "State-driven") and still get rejected
        # here for an undefined acronym, and that distinction is worth
        # preserving rather than overwriting the pattern to "unclear".
        ears_pattern = dict(state["ears_classification"])
        rejection_reason = state.get("rejection_reason") or ears_pattern.get("reason", "")
        ears_pattern["reason"] = f"Rejected -- not EARS compliant: {rejection_reason}"

        result = {
            "original_text": original_text,
            "source_location": state["source_location"],
            "rule_flags": state["rule_flags"],
            "ears_pattern": ears_pattern,
            "candidates": [],
            "recommended_index": -1,
            "recommended_text": original_text,
            "recommended_score": score_result.score,
            "vague_term_suggestions": [],
            "compliance_threshold": compliance_threshold,
            "needs_human_review": True,
        }
        return {"result": result, "needs_human_review": True}

    return reject_node


# ---------------------------------------------------------------------------
# Node: GenerateCandidates (the only node that talks to Ollama)
# ---------------------------------------------------------------------------


def _make_generate_candidates_node(client: LocalLLMClient):
    def generate_candidates_node(state: PipelineState) -> dict:
        flags = [f["violation_type"] for f in state["rule_flags"]]
        ears_pattern = state["ears_classification"]["pattern"]
        candidates = generate_candidates(
            client, state["original_text"], flags=flags, ears_pattern=ears_pattern
        )
        return {"candidates_raw": candidates}

    return generate_candidates_node


# ---------------------------------------------------------------------------
# Node: ScoreAndRecommend
# ---------------------------------------------------------------------------


def score_and_recommend_node(state: PipelineState) -> dict:
    return {"recommendation": recommend(state["candidates_raw"], state["original_text"])}


# ---------------------------------------------------------------------------
# Node: Finalize
# ---------------------------------------------------------------------------


def _make_finalize_node(compliance_threshold: float):
    def finalize_node(state: PipelineState) -> dict:
        recommendation = state["recommendation"]
        recommended = recommendation.recommended
        # An invented number is a hard trigger regardless of score: a
        # candidate that fabricated a value can still score well on the
        # INCOSE checks (a fake "within 200 ms" satisfies R6/R33/R34 just
        # as well as a real one), so score alone can't be trusted here.
        # recommender.py already ranks non-inventing candidates first;
        # this only fires when every one of the 3 candidates invented a
        # number and there was no clean candidate to prefer instead.
        needs_human_review = (
            recommended.score < compliance_threshold or recommended.has_invented_number
        )

        result = {
            "original_text": state["original_text"],
            "source_location": state["source_location"],
            "rule_flags": state["rule_flags"],
            "ears_pattern": state["ears_classification"],
            "candidates": [c.to_dict() for c in recommendation.candidates],
            "recommended_index": recommendation.recommended_index,
            "recommended_text": recommended.rewritten_text,
            "recommended_score": recommended.score,
            "vague_term_suggestions": [asdict(v) for v in recommended.vague_terms],
            "compliance_threshold": compliance_threshold,
            "needs_human_review": needs_human_review,
        }
        return {"result": result, "needs_human_review": needs_human_review}

    return finalize_node


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def build_graph(
    client: LocalLLMClient | None = None,
    compliance_threshold: float | None = None,
    settings: dict[str, Any] | None = None,
):
    """Builds and compiles the pipeline graph. Never touches the network by
    itself -- constructing a LocalLLMClient doesn't connect to Ollama, only
    invoking the compiled graph through GenerateCandidates does.

    ``client`` defaults to a real LocalLLMClient built from
    config/settings.yaml; pass a test double for offline testing.
    ``compliance_threshold`` defaults to config/settings.yaml's
    pipeline.compliance_threshold (falling back to
    DEFAULT_COMPLIANCE_THRESHOLD if that key is absent).
    """
    resolved_settings = settings or get_settings()
    if client is None:
        client = LocalLLMClient(resolved_settings)
    if compliance_threshold is None:
        compliance_threshold = resolved_settings.get("pipeline", {}).get(
            "compliance_threshold", DEFAULT_COMPLIANCE_THRESHOLD
        )

    graph = StateGraph(PipelineState)
    graph.add_node("Parse", parse_node)
    graph.add_node("RuleFlag", rule_flag_node)
    graph.add_node("ClassifyPattern", classify_pattern_node)
    graph.add_node("AbbreviationCheck", abbreviation_check_node)
    graph.add_node("ComplianceCheck", compliance_check_node)
    graph.add_node("RejectNonEars", _make_reject_node(compliance_threshold))
    graph.add_node("GenerateCandidates", _make_generate_candidates_node(client))
    graph.add_node("ScoreAndRecommend", score_and_recommend_node)
    graph.add_node("Finalize", _make_finalize_node(compliance_threshold))

    graph.add_edge(START, "Parse")
    graph.add_edge("Parse", "RuleFlag")
    graph.add_edge("RuleFlag", "ClassifyPattern")
    graph.add_edge("ClassifyPattern", "AbbreviationCheck")
    graph.add_edge("AbbreviationCheck", "ComplianceCheck")
    graph.add_conditional_edges(
        "ComplianceCheck",
        _route_after_compliance_check,
        {"generate": "GenerateCandidates", "reject": "RejectNonEars"},
    )
    graph.add_edge("GenerateCandidates", "ScoreAndRecommend")
    graph.add_edge("ScoreAndRecommend", "Finalize")
    graph.add_edge("Finalize", END)
    graph.add_edge("RejectNonEars", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------


def run_requirement(
    compiled_graph, requirement_text: str, source_location: dict | None = None
) -> dict:
    """Runs the compiled graph on one requirement string and returns
    Finalize's result dict (original text, source location, rule flags,
    all 3 candidates with scores, recommended candidate, vague-term
    suggestions, needs_human_review)."""
    initial_state: PipelineState = {"requirement_text": requirement_text}
    if source_location is not None:
        initial_state["source_location"] = source_location
    final_state = compiled_graph.invoke(initial_state)
    return final_state["result"]


def run_requirement_streaming(
    compiled_graph,
    requirement_text: str,
    source_location: dict | None = None,
    on_stage=None,
) -> dict:
    """Same contract and return value as run_requirement(), but drives the
    graph via .stream(..., stream_mode="updates") instead of .invoke() so
    ``on_stage(node_name, node_output)`` -- if given -- fires after each
    node completes (Parse, RuleFlag, ClassifyPattern, AbbreviationCheck,
    ComplianceCheck, then either GenerateCandidates -> ScoreAndRecommend ->
    Finalize or just RejectNonEars, whichever branch ComplianceCheck routes
    to), not just once at the end. Used by src/ui/api.py to report live
    per-requirement progress; existing callers that just want the final
    result keep using run_requirement().
    """
    initial_state: PipelineState = {"requirement_text": requirement_text}
    if source_location is not None:
        initial_state["source_location"] = source_location

    accumulated: dict = dict(initial_state)
    for step in compiled_graph.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in step.items():
            accumulated.update(node_output)
            if on_stage is not None:
                on_stage(node_name, node_output)
    return accumulated["result"]


def run_workbook(compiled_graph, file_path: str | Path) -> list[dict]:
    """Runs the compiled graph once per candidate requirement extracted
    from ``file_path`` by src/ingestion/parser.py, returning one result
    dict per candidate, in the order parse_workbook found them."""
    parse_result = parse_workbook(file_path)
    if parse_result.issues:
        raise ValueError(f"Failed to parse {file_path}: {parse_result.issues}")

    results = []
    for candidate in parse_result.candidates:
        final_state = compiled_graph.invoke(
            {"file_path": str(file_path), "cell_reference": candidate.location.cell_reference}
        )
        results.append(final_state["result"])
    return results

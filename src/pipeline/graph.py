"""Wires the end-to-end requirement-rewriting pipeline as a LangGraph:

    Parse -> RuleFlag -> ClassifyPattern -> GenerateCandidates -> ScoreAndRecommend -> Finalize

- Parse: src/ingestion/parser.py -- either extracts a candidate requirement
  from an .xlsx file (given file_path + cell_reference), or normalizes an
  already-extracted requirement string (given requirement_text directly,
  which is how every test in this module and any caller that already ran
  parse_workbook itself drives the graph).
- RuleFlag: src/rules/detectors.py's run_all_detectors -- deterministic,
  no LLM.
- ClassifyPattern: src/rules/ears_classifier.py's classify_ears_pattern --
  deterministic keyword classifier, no LLM. Runs independently of
  RuleFlag; its first-guess pattern is passed into the prompt built by
  GenerateCandidates as context, not as a hard constraint.
- GenerateCandidates: src/llm/local_llm_client.py + src/pipeline/
  candidate_generator.py -- the only node that talks to Ollama. The
  RuleFlag flags and ClassifyPattern's guess both feed into the prompt
  (src/llm/prompts.py, via candidate_generator -> build_prompt).
- ScoreAndRecommend: src/pipeline/recommender.py -- deterministic INCOSE
  scoring of all 3 candidates, no LLM.
- Finalize: assembles the public result and decides needs_human_review by
  comparing the recommended candidate's score against a configurable
  compliance_threshold (config/settings.yaml's pipeline.compliance_threshold)
  -- a low-scoring "best of 3" is not presented as a confident
  recommendation.

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
from rules.ears_classifier import classify_ears_pattern

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

    # --- GenerateCandidates ---
    candidates_raw: list[Candidate]

    # --- ScoreAndRecommend ---
    recommendation: RecommendationResult

    # --- Finalize ---
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
    graph.add_node("GenerateCandidates", _make_generate_candidates_node(client))
    graph.add_node("ScoreAndRecommend", score_and_recommend_node)
    graph.add_node("Finalize", _make_finalize_node(compliance_threshold))

    graph.add_edge(START, "Parse")
    graph.add_edge("Parse", "RuleFlag")
    graph.add_edge("RuleFlag", "ClassifyPattern")
    graph.add_edge("ClassifyPattern", "GenerateCandidates")
    graph.add_edge("GenerateCandidates", "ScoreAndRecommend")
    graph.add_edge("ScoreAndRecommend", "Finalize")
    graph.add_edge("Finalize", END)

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

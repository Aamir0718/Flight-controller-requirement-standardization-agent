"""Assembles the LLM prompt for rewriting one requirement.

build_prompt() pulls together, for a single target requirement:

- The full EARS pattern set (data/rules/ears_patterns.json) -- always
  included in full; it's small (Prompt 5's file was written specifically
  small enough for this).
- ONLY the INCOSE rule subset relevant to this requirement's flagged
  defects, via src/rules/rule_selector.select_relevant_rules() -- not all
  42 rules, so the model's attention isn't diluted by rules that don't
  apply here.
- A handful of few-shot examples from data/golden/fewshot.json, filtered
  to the defect_type(s) matching this requirement's flags, so the model
  sees worked bad -> reason -> fixed examples of the *same* kind of defect
  it needs to fix.
- An explicit instruction never to invent a specific number when
  suggesting a fix for a vague term -- only to say what kind of value is
  missing (a human with domain knowledge supplies the actual number).

The output is exactly what src/llm/local_llm_client.LocalLLMClient.
generate_structured() expects: a system_prompt and a user_prompt.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rules.ears_classifier import load_ears_patterns
from rules.rule_selector import select_relevant_rules

FEWSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "golden" / "fewshot.json"

MAX_FEWSHOT_EXAMPLES = 3

# Which fewshot.json `defect_type` values correspond to each detector flag
# (src/rules/detectors.py violation_type). Mirrors the flag -> INCOSE rule
# mapping in rule_selector.py, but for a different purpose (picking
# worked examples of the same defect, not picking rules to cite) -- kept
# as its own mapping rather than derived from rule_selector's, since the
# two groupings are allowed to diverge (e.g. missing_unit has no dedicated
# defect_type label in the golden set; it borrows the closest ones).
FLAG_TO_DEFECT_TYPES: dict[str, tuple[str, ...]] = {
    "vague_term": (
        "Non-Verifiable", "Non-Verifiable / Unbounded", "Subjectivity / Non-Verifiable",
        "Vagueness", "Vagueness / Ambiguity", "Incompleteness / Vagueness",
        "Ambiguity / Vagueness", "Ambiguity", "Ambiguity / Subjectivity",
        "Ambiguity / Escape Clause", "Lack of Precision", "Subjectivity",
        "Non-Standard Syntax/Vocabulary", "Regulatory / Escape Clause", "Incompleteness",
    ),
    "negative_constraint": ("Subtle Negative Constraint",),
    "missing_unit": ("Lack of Precision", "Non-Verifiable"),
    "compound_requirement": ("Non-Atomic Multiple Behaviors", "Singular"),
    "missing_ears_trigger": ("Structural Inconsistency",),
    "passive_voice": ("Passive Voice / Missing Actor",),
}

SYSTEM_PROMPT_HEADER = """You are a requirements-engineering assistant. You rewrite a single \
system/software requirement so it is EARS-compliant and satisfies the cited INCOSE rules, \
while preserving the original requirement's intent exactly -- you are fixing how it is \
written, not changing what the system is supposed to do.

CRITICAL: This prompt will be called multiple times for the same requirement. Each call \
MUST produce a GENUINELY DIFFERENT candidate. The candidates should differ in BOTH sentence \
structure AND wording choices, while preserving the exact same technical meaning, values, units, \
conditions, and constraints.

MANDATORY: Each call must follow the specific structural guidance in the user prompt.

FORBIDDEN: Do not produce candidates that only differ by 1-2 words. Do not reuse the same \
sentence structure across different calls. Do not simply copy a previous candidate and make \
trivial changes. Do not change technical values just to make candidates different.

DIVERSITY STRATEGIES:
- Vary the placement of the condition (before or after the main clause)
- Use different connector words (when, upon, in the event that, if, provided that)
- Rephrase the system subject (the flight control system, the FCS, the controller)
- Rephrase the action (maintain, keep, sustain, preserve)
- Rephrase the condition (when X is detected, upon detection of X, if X occurs)
- Use synonyms for technical terms where appropriate (angle, orientation, pitch)
- Combine or split clauses differently while preserving meaning

Rules for your response:
1. Choose the single EARS pattern (from the pattern set below) that best fits the \
requirement's intent, and rewrite the requirement to conform to that pattern's syntax \
template exactly. Use the sentence structure specified in the user prompt.
2. Apply only the cited INCOSE rules below. Do not invent additional rules.
3. For every vague/unmeasurable term you flag, produce a plain-language SUGGESTION of what \
kind of information is missing (e.g. "specify a maximum response time in milliseconds", \
"state the exact tolerance band") -- never invent or guess a specific number, threshold, or \
unit value yourself. You do not have the domain knowledge to know the right number; a human \
reviewer does. If the input requirement already contains enough information to remove a term \
without inventing a number (e.g. combining two already-stated facts), you may use it -- \
otherwise leave the number out of rewritten_text too and flag it in vague_terms instead.
4. Respond with ONLY a single JSON object -- no markdown code fences, no commentary before or \
after it -- matching exactly this schema:
{
  "pattern": "<one of the EARS pattern names below>",
  "rewritten_text": "<the rewritten requirement>",
  "vague_terms": [{"term": "<flagged term or phrase>", "suggestion": "<what info is missing>"}],
  "confidence": <number between 0 and 1>,
  "notes": "<any other observations a human reviewer should know>"
}

Follow the structural pattern specified in the user prompt exactly.
"""


@dataclass(frozen=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str
    selected_rules: list[dict]
    fewshot_examples: list[dict]


@functools.lru_cache(maxsize=1)
def _load_fewshot(path: Path | None = None) -> list[dict]:
    fewshot_path = path or FEWSHOT_PATH
    return json.loads(fewshot_path.read_text(encoding="utf-8"))


def _normalize_flags(flags: Iterable) -> set[str]:
    normalized = set()
    for flag in flags:
        normalized.add(flag.violation_type if hasattr(flag, "violation_type") else flag)
    return normalized


def _format_ears_patterns(patterns: list[dict]) -> str:
    lines = ["EARS pattern set (choose exactly one):"]
    for p in patterns:
        lines.append(f"- {p['name']}: \"{p['syntax_template']}\"\n  Example: \"{p['example']}\"")
    return "\n".join(lines)


def _format_incose_rules(rules: list[dict]) -> str:
    if not rules:
        return "No specific INCOSE rule violations were flagged for this requirement."
    lines = ["Cited INCOSE rules to fix (only these -- do not apply unrelated rules):"]
    for r in rules:
        lines.append(f"- {r['id']} ({r['category']} / {r['title']}): {r['description']}")
    return "\n".join(lines)


def select_fewshot_examples(
    flags: Iterable,
    max_examples: int = MAX_FEWSHOT_EXAMPLES,
    fewshot_path: Path | None = None,
) -> list[dict]:
    """Picks up to ``max_examples`` fewshot.json rows whose defect_type
    matches one of the ``flags`` (detector violation_type strings, or
    Finding objects). Deterministic: sorted by id, round-robins across
    matched defect types for variety rather than taking N rows of the
    first matching type.
    """
    normalized_flags = _normalize_flags(flags)
    wanted_defect_types: set[str] = set()
    for flag in normalized_flags:
        wanted_defect_types.update(FLAG_TO_DEFECT_TYPES.get(flag, ()))

    if not wanted_defect_types:
        return []

    rows = _load_fewshot(fewshot_path)
    by_defect_type: dict[str, list[dict]] = {}
    for row in rows:
        if row["defect_type"] in wanted_defect_types:
            by_defect_type.setdefault(row["defect_type"], []).append(row)
    for group in by_defect_type.values():
        group.sort(key=lambda r: r["id"])

    selected: list[dict] = []
    defect_types_in_order = sorted(by_defect_type.keys())
    round_index = 0
    while len(selected) < max_examples and any(by_defect_type.values()):
        for defect_type in defect_types_in_order:
            group = by_defect_type[defect_type]
            if round_index < len(group):
                selected.append(group[round_index])
                if len(selected) >= max_examples:
                    break
        round_index += 1
        if round_index > max(len(g) for g in by_defect_type.values()):
            break

    return selected


def _format_fewshot_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["Worked examples of this kind of defect being fixed:"]
    for ex in examples:
        lines.append(
            f"- Bad: \"{ex['bad_requirement']}\"\n"
            f"  Why: {ex['reason']}\n"
            f"  Fixed: \"{ex['compliant_version']}\""
        )
    return "\n".join(lines)


def build_prompt(
    requirement_text: str,
    flags: Iterable,
    ears_pattern: str | None = None,
    max_fewshot_examples: int = MAX_FEWSHOT_EXAMPLES,
    candidate_index: int = 0,
) -> PromptBundle:
    """Builds the system_prompt/user_prompt pair for one requirement.

    ``flags`` is whatever src/rules/detectors.py produced for this
    requirement (an iterable of violation_type strings, or the raw list of
    Finding objects from run_all_detectors()) -- it drives both which
    INCOSE rules get cited and which few-shot examples get selected.
    ``ears_pattern`` is the first-guess classification from
    src/rules/ears_classifier.py, if available; passed through as context
    only, not enforced.
    ``candidate_index`` is 0, 1, or 2 for the three candidate calls -- used
    to give call-specific instructions about structural variation.
    """
    ears_patterns = load_ears_patterns()
    selected_rules = select_relevant_rules(flags)
    fewshot_examples = select_fewshot_examples(flags, max_fewshot_examples)

    system_prompt = "\n\n".join(
        [
            SYSTEM_PROMPT_HEADER.strip(),
            _format_ears_patterns(ears_patterns),
            _format_incose_rules(selected_rules),
        ]
    )

    user_prompt_parts = []
    fewshot_block = _format_fewshot_examples(fewshot_examples)
    if fewshot_block:
        user_prompt_parts.append(fewshot_block)
    if ears_pattern:
        user_prompt_parts.append(f"First-guess EARS pattern classification: {ears_pattern}")
    user_prompt_parts.append(f'Requirement to rewrite:\n"{requirement_text}"')
    
    # Add call-specific structural guidance
    if candidate_index == 0:
        user_prompt_parts.append(
            "\nFor this call (Candidate 1): Use the structure \"When [condition], the system shall [response]\". "
            "Example: \"When the sensor is invalid, the system shall activate the backup.\""
        )
    elif candidate_index == 1:
        user_prompt_parts.append(
            "\nFor this call (Candidate 2): Use the structure \"The system shall [response] when [condition]\" "
            "with different wording than Candidate 1. Rephrase the subject or action verbs. "
            "Example: \"The system shall activate the backup when the sensor is invalid.\""
        )
    elif candidate_index == 2:
        user_prompt_parts.append(
            "\nFor this call (Candidate 3): Use the structure \"Upon [condition], the system shall [response]\" "
            "or \"In the event that [condition], the system shall [response]\". Use yet different phrasing. "
            "Example: \"Upon detection of sensor invalidity, the system shall transition to the backup.\""
        )
    
    user_prompt_parts.append(
        "\nRemember: Use a genuinely different sentence structure than the other candidates. "
        "Preserve the exact technical meaning while varying the formulation."
    )
    user_prompt = "\n\n".join(user_prompt_parts)

    return PromptBundle(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        selected_rules=selected_rules,
        fewshot_examples=fewshot_examples,
    )

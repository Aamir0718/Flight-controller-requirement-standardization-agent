"""Assembles the LLM prompt for rewriting one requirement.

build_prompt() pulls together, for a single target requirement:

- ONLY the EARS pattern the deterministic classifier already matched
  (src/rules/ears_classifier.py) -- not the full 6-pattern set. The
  classifier already knows which template applies before generation ever
  starts (EARS gate passed), so there's nothing to gain from spending
  tokens on the other 5 every call; falls back to the full set only if no
  pattern name is given (shouldn't happen via the normal pipeline).
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

build_correction_prompt() is the lean follow-up used only when the first
attempt fails src/pipeline/candidate_generator.py's post-generation
deterministic recheck -- it cites just the previous attempt and exactly
what still fails, instead of resending the full context above again.

The output of either is exactly what src/llm/local_llm_client.
LocalLLMClient.generate_structured() expects: a system_prompt and a
user_prompt.
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

Rules for your response:
1. Rewrite the requirement to conform exactly to the EARS pattern's syntax template given \
below.
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
  "pattern": "<the EARS pattern name>",
  "rewritten_text": "<the rewritten requirement>",
  "vague_terms": [{"term": "<flagged term or phrase>", "suggestion": "<what info is missing>"}],
  "confidence": <number between 0 and 1>,
  "notes": "<any other observations a human reviewer should know>"
}
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


def _format_ears_patterns(patterns: list[dict], only_pattern_name: str | None = None) -> str:
    """Formats the EARS pattern block. When ``only_pattern_name`` names one
    of ``patterns``, only that entry is included -- the deterministic
    classifier (src/rules/ears_classifier.py) already picked the pattern
    before generation starts, so sending the other 5 templates every call
    just spends tokens with no benefit. Falls back to the full set if the
    name isn't found (e.g. "Complex", which combines templates rather than
    being one of them) so generation is never left with zero guidance.
    """
    if only_pattern_name:
        matched = [p for p in patterns if p["name"] == only_pattern_name]
        if matched:
            patterns = matched
    lines = ["Required EARS pattern:" if only_pattern_name and len(patterns) == 1 else "EARS pattern set (choose exactly one):"]
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


def _format_incose_score_block(score: float | None, violations: list[dict] | None) -> str:
    """Grounds the model in the ORIGINAL text's actual deterministic INCOSE
    score (src/rules/incose_scorer.py's score_requirement()) and its exact
    failure reasons, rather than leaving the model to guess how non-
    compliant the text is or invent its own reasons. ``score`` is None when
    the caller didn't supply one (e.g. older call sites/tests) -- in that
    case this block is omitted entirely rather than printed with a
    misleading placeholder value.
    """
    if score is None:
        return ""
    lines = [
        f"Deterministic INCOSE compliance score for the original text: {score:.1f}/100 "
        "(computed over the 28 automatable INCOSE rules only -- 14 further rules need "
        "human/domain judgement and are not part of this score)."
    ]
    if violations:
        lines.append("Specific rule violations measured in the original text:")
        for v in violations:
            reasons = " ".join(v.get("reasons", []))
            lines.append(f"- {v['id']} ({v['title']}): {reasons}")
    else:
        lines.append("No automatable INCOSE rule violations were measured in the original text.")
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
    incose_score: float | None = None,
    incose_violations: list[dict] | None = None,
) -> PromptBundle:
    """Builds the system_prompt/user_prompt pair for the FIRST generation
    attempt on one requirement. Only ever called once per requirement --
    src/pipeline/candidate_generator.py only calls this for attempt 0 and
    switches to the much leaner build_correction_prompt() for any retry,
    so this is deliberately as small as it can be while still giving the
    model everything it needs to get it right on the first try.

    ``flags`` is whatever src/rules/detectors.py produced for this
    requirement (an iterable of violation_type strings, or the raw list of
    Finding objects from run_all_detectors()) -- it drives both which
    INCOSE rules get cited and which few-shot examples get selected.
    ``ears_pattern`` is the pattern src/rules/ears_classifier.py already
    matched for this requirement -- only that one pattern's template is
    included (see _format_ears_patterns), not the full 6-pattern set.
    ``incose_score``/``incose_violations`` are the ORIGINAL text's actual
    deterministic INCOSE score and failed-rule list (src/rules/
    incose_scorer.py's score_requirement()), if the caller has them --
    grounds the model in the real, measured compliance gap instead of just
    the detector-flag-driven rule subset below, which is a heuristic
    approximation of the same thing. Optional (None/omitted) for call sites
    that don't have a score computed yet.
    """
    ears_patterns = load_ears_patterns()
    selected_rules = select_relevant_rules(flags)
    fewshot_examples = select_fewshot_examples(flags, max_fewshot_examples)

    system_prompt_parts = [
        SYSTEM_PROMPT_HEADER.strip(),
        _format_ears_patterns(ears_patterns, only_pattern_name=ears_pattern),
        _format_incose_rules(selected_rules),
    ]
    score_block = _format_incose_score_block(incose_score, incose_violations)
    if score_block:
        system_prompt_parts.append(score_block)
    system_prompt = "\n\n".join(system_prompt_parts)

    user_prompt_parts = []
    fewshot_block = _format_fewshot_examples(fewshot_examples)
    if fewshot_block:
        user_prompt_parts.append(fewshot_block)
    user_prompt_parts.append(f'Requirement to rewrite:\n"{requirement_text}"')
    user_prompt = "\n\n".join(user_prompt_parts)

    return PromptBundle(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        selected_rules=selected_rules,
        fewshot_examples=fewshot_examples,
    )


def format_recheck_failures(ears_recheck, score_recheck) -> list[str]:
    """Flattens a failed post-generation recheck (src/rules/
    ears_classifier.classify_ears_pattern() + src/rules/incose_scorer.
    score_requirement(), both run against an LLM attempt's rewritten_text)
    into one short reason per problem -- exactly what
    build_correction_prompt() cites for the next attempt, and what
    src/pipeline/graph.py already used for its own rejection-reason text.
    """
    from rules.ears_classifier import UNCLEAR_LABEL

    reasons = []
    if ears_recheck.pattern == UNCLEAR_LABEL:
        reasons.append(f"EARS structure: {ears_recheck.reason}")
    for f in score_recheck.failed:
        reasons.append(f"{f.id} ({f.title}): {' '.join(f.reasons)}")
    return reasons


def build_correction_prompt(
    requirement_text: str,
    previous_attempt: str,
    failure_reasons: list[str],
    ears_pattern: str | None = None,
) -> PromptBundle:
    """Builds a compact follow-up prompt after an attempt fails the
    deterministic post-generation recheck (src/pipeline/
    candidate_generator.py's confirm-loop). Cites only the previous
    attempt and exactly what still fails -- NOT the full EARS pattern set,
    rule descriptions, or few-shot examples again -- since the model
    already saw those once and the goal now is a targeted fix, not a
    fresh attempt from scratch.
    """
    pattern_line = ""
    if ears_pattern:
        matched = [p for p in load_ears_patterns() if p["name"] == ears_pattern]
        if matched:
            p = matched[0]
            pattern_line = f'Required EARS pattern -- {p["name"]}: "{p["syntax_template"]}"'

    system_prompt = "\n\n".join(
        part
        for part in [
            "You are a requirements-engineering assistant. Your previous rewrite of a "
            "system/software requirement did not pass an automated EARS/INCOSE compliance "
            "check. Produce a corrected rewrite that fixes ONLY the specific problems listed "
            "below -- preserve every other word, technical value, unit, and condition exactly "
            "as your previous attempt had them. Never invent a specific number, threshold, or "
            "unit value that isn't already stated in the requirement.",
            pattern_line,
            "Respond with ONLY a single JSON object -- no markdown code fences, no commentary "
            'before or after it -- matching exactly this schema:\n'
            '{"pattern": "<the EARS pattern name>", "rewritten_text": "<the corrected '
            'requirement>", "vague_terms": [{"term": "...", "suggestion": "..."}], '
            '"confidence": <0-1>, "notes": "..."}',
        ]
        if part
    )

    reasons_block = "\n".join(f"- {r}" for r in failure_reasons) or "(no specific reason given)"
    user_prompt = (
        f'Original requirement:\n"{requirement_text}"\n\n'
        f'Your previous rewrite:\n"{previous_attempt}"\n\n'
        "That rewrite still fails these automated checks:\n"
        f"{reasons_block}\n\n"
        "Produce a corrected rewrite that fixes ONLY these issues."
    )

    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt, selected_rules=[], fewshot_examples=[])

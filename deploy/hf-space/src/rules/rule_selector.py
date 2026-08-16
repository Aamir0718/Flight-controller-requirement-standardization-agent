"""Reduces the full 42-rule INCOSE rulebook down to the handful of rules
relevant to a specific requirement's detected defects.

The defect detectors in src/rules/detectors.py produce coarse "flags"
(violation_type strings such as "vague_term" or "compound_requirement") to
show a human a quick suggestion. The full incose_scorer.py runs every
automatable rule regardless, for a complete compliance score. Neither of
those is the right thing to hand an LLM: showing it all 42 rules on every
prompt wastes context and dilutes attention on the handful of rules that
actually matter for *this* requirement.

select_relevant_rules() bridges the two: given the flags raised for one
requirement, it returns only the rulebook entries plausibly relevant to
those flags, so a prompt-builder can include just that reduced subset.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Iterable

from rules.incose_scorer import load_rulebook

# Maps each detector violation_type (src/rules/detectors.py) to the INCOSE
# rule ids it's relevant to. A flag can map to more than one rule because
# a single defect (e.g. a vague term) can simultaneously violate several
# distinct rules (vagueness, escape clauses, unmeasurable performance).
FLAG_TO_RULE_IDS: dict[str, tuple[str, ...]] = {
    "vague_term": ("R7", "R8", "R9", "R34", "R35"),
    "negative_constraint": ("R16", "R26"),
    "missing_unit": ("R6", "R33", "R34"),
    "compound_requirement": ("R11", "R18", "R19", "R28"),
    "missing_ears_trigger": ("R1", "R27"),
    "passive_voice": ("R2",),
}


def _normalize_flags(flags: Iterable) -> set[str]:
    """Accepts either violation_type strings or Finding-like objects (with
    a `.violation_type` attribute, e.g. detectors.Finding) and returns a
    plain set of flag strings."""
    normalized = set()
    for flag in flags:
        normalized.add(flag.violation_type if hasattr(flag, "violation_type") else flag)
    return normalized


@functools.lru_cache(maxsize=4)
def _rulebook_by_id(path: Path | None = None) -> dict[str, dict]:
    return {rule["id"]: rule for rule in load_rulebook(path)}


def select_relevant_rules(
    flags: Iterable,
    rulebook_path: Path | None = None,
) -> list[dict]:
    """Returns the subset of INCOSE rulebook entries relevant to ``flags``.

    ``flags`` is whatever src/rules/detectors.py produced for one
    requirement: an iterable of violation_type strings (e.g.
    {"vague_term", "compound_requirement"}), or the raw list of Finding
    objects from run_all_detectors() -- both work.

    Returns a list of full rulebook entries (id/category/title/description/
    ...), deduplicated, in rulebook order. Unrecognized flags are ignored
    rather than raising, since new detector categories may not have a rule
    mapping yet. Returns [] if no flags are given or none map to a rule.
    """
    normalized_flags = _normalize_flags(flags)
    rules_by_id = _rulebook_by_id(rulebook_path)

    selected_ids: list[str] = []
    seen: set[str] = set()
    for flag in normalized_flags:
        for rule_id in FLAG_TO_RULE_IDS.get(flag, ()):
            if rule_id not in seen and rule_id in rules_by_id:
                seen.add(rule_id)
                selected_ids.append(rule_id)

    # Stable, readable ordering: by rulebook position rather than flag
    # iteration order (sets are unordered).
    rulebook_order = {rule_id: i for i, rule_id in enumerate(r["id"] for r in load_rulebook(rulebook_path))}
    selected_ids.sort(key=lambda rid: rulebook_order[rid])

    return [rules_by_id[rule_id] for rule_id in selected_ids]

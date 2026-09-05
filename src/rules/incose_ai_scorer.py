"""On-demand, LLM-judged scoring for the 14 INCOSE rules that
src/rules/incose_scorer.py can't check mechanically (data/rules/
incose_rulebook.json's `automatable: false` rules -- see each one's
`rationale_not_automatable`).

This is deliberately NOT part of the deterministic score every requirement
gets automatically: it costs one real LLM call per requirement, and a
model's judgement on these 14 rules is inherently softer than a regex
match, so a human has to opt into it explicitly (the "Check Accurate
Score" button) rather than getting it silently mixed into the default
28-rule number everyone sees on every requirement.

score_accurate() combines this module's 14-rule AI verdicts with
incose_scorer.score_requirement()'s existing 28-rule deterministic result
into one 42-rule score -- the same 42 data/rules/incose_rulebook.json
lists in total.
"""

from __future__ import annotations

from dataclasses import dataclass

from llm.local_llm_client import LocalLLMClient
from rules.incose_scorer import FailedRule, ScoreResult, load_rulebook, score_requirement

# A handful of these 14 rules are, by their own rationale_not_automatable,
# properties of the whole requirement SET or of external documents (a
# glossary, a style guide, document headings) -- not of one requirement's
# text in isolation. An LLM judging a single requirement string can't
# genuinely verify those either; asking it to guess would just replace a
# missing mechanical check with an unreliable one. Rather than silently
# failing every requirement on a technicality nothing in this call could
# ever confirm, these are excluded from the LLM judgment call and always
# reported as "not assessable from a single requirement" -- honest about
# the limitation instead of pretending the AI-judged score is complete.
_SET_OR_DOCUMENT_LEVEL_RULE_IDS = frozenset({"R4", "R29", "R30", "R36", "R39", "R41", "R42"})

_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "rule_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "passed", "reason"],
            },
        }
    },
    "required": ["rule_results"],
}
_REQUIRED_KEYS = {"rule_results"}

_SYSTEM_PROMPT = """You are an INCOSE requirements-quality reviewer. You will be given ONE \
system/software requirement's text and a list of INCOSE rules that cannot be checked by a \
mechanical/regex tool -- each needs human-style judgement (domain plausibility, grammar, \
whether a diagram is really needed, etc.).

For EACH rule listed, decide whether the requirement, AS WRITTEN, violates it. Judge only \
what is visible in this single requirement's text -- you have no access to the rest of the \
requirement set, any external glossary, or any style guide, so do not fail a rule for missing \
context you were never given; if a rule's judgement genuinely depends on information outside \
this one requirement, mark it passed with a reason noting that nothing in the visible text \
violates it.

Respond with ONLY a single JSON object -- no markdown fences, no commentary -- of this shape:
{"rule_results": [{"id": "<rule id>", "passed": <true/false>, "reason": "<one sentence, cite the exact word/phrase if failed>"}, ...]}

You MUST include exactly one entry per rule id given below, in the same order."""


@dataclass(frozen=True)
class AiScoreResult:
    passed: list[str]
    failed: list[FailedRule]
    not_assessable: list[str]  # rule ids judged out of scope for a single requirement's text
    score: float
    total_rules: int


@dataclass(frozen=True)
class CombinedScoreResult:
    """The full, 42-rule picture: the existing 28-rule deterministic result
    plus this module's 14-rule AI-judged result, combined into one score."""
    deterministic: ScoreResult
    ai: AiScoreResult
    combined_score: float
    combined_total_rules: int


def _non_automatable_rules() -> list[dict]:
    return [r for r in load_rulebook() if not r["automatable"]]


def _format_rules_for_prompt(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        lines.append(
            f"- {r['id']} ({r['category']} / {r['title']}): {r['description']}"
        )
    return "\n".join(lines)


def score_non_automatable_rules(text: str, client: LocalLLMClient) -> AiScoreResult:
    """Sends ``text`` plus the 14 non-automatable INCOSE rules to the
    configured LLM in a single call and returns a pass/fail verdict (with a
    reason) for each. Raises whatever LocalLLMClient.generate_json raises
    (LLMUnavailableError, LLMResponseError) -- same failure contract as
    every other LLM call in this project, no silent fallback.
    """
    all_rules = _non_automatable_rules()
    judged_rules = [r for r in all_rules if r["id"] not in _SET_OR_DOCUMENT_LEVEL_RULE_IDS]
    not_assessable_rules = [r for r in all_rules if r["id"] in _SET_OR_DOCUMENT_LEVEL_RULE_IDS]

    user_prompt = (
        f"Requirement text:\n\"{text}\"\n\n"
        f"Rules to judge:\n{_format_rules_for_prompt(judged_rules)}"
    )
    response = client.generate_json(
        _SYSTEM_PROMPT, user_prompt, _RESULT_SCHEMA, _REQUIRED_KEYS
    )

    results_by_id = {
        r["id"]: r
        for r in response.get("rule_results", [])
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }

    passed: list[str] = []
    failed: list[FailedRule] = []
    for rule in judged_rules:
        verdict = results_by_id.get(rule["id"])
        if verdict is None:
            # Model dropped this rule from its response -- fail closed
            # (report it as a violation needing human attention) rather
            # than silently counting it as passed on missing data.
            failed.append(
                FailedRule(
                    id=rule["id"],
                    title=rule["title"],
                    category=rule["category"],
                    reasons=["The model did not return a verdict for this rule; treat as unverified."],
                )
            )
            continue
        if verdict.get("passed") is True:
            passed.append(rule["id"])
        else:
            reason = verdict.get("reason") or "The model flagged this rule without a stated reason."
            failed.append(
                FailedRule(id=rule["id"], title=rule["title"], category=rule["category"], reasons=[str(reason)])
            )

    not_assessable = [r["id"] for r in not_assessable_rules]
    # Not-assessable rules count toward "passed" for scoring purposes (see
    # module docstring / _SET_OR_DOCUMENT_LEVEL_RULE_IDS) -- there is no
    # visible violation to hold against the requirement, same treatment a
    # human reviewer would give a rule they cannot check from this text
    # alone.
    passed = passed + not_assessable

    total = len(all_rules)
    score = round(100.0 * len(passed) / total, 1) if total else 0.0
    return AiScoreResult(passed=passed, failed=failed, not_assessable=not_assessable, score=score, total_rules=total)


def score_accurate(text: str, client: LocalLLMClient) -> CombinedScoreResult:
    """The full 42-rule picture for ``text``: re-runs the existing 28-rule
    deterministic scorer and adds this module's 14-rule AI judgement,
    combined into one score. This is the function src/ui/api.py's
    "Check Accurate Score" endpoint calls -- never run automatically,
    only when a human explicitly asks for one requirement.
    """
    deterministic = score_requirement(text)
    ai = score_non_automatable_rules(text, client)
    combined_total = deterministic.total_rules + ai.total_rules
    combined_passed = len(deterministic.passed) + len(ai.passed)
    combined_score = round(100.0 * combined_passed / combined_total, 1) if combined_total else 0.0
    return CombinedScoreResult(
        deterministic=deterministic, ai=ai, combined_score=combined_score, combined_total_rules=combined_total
    )

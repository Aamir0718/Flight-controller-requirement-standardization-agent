"""Deterministic INCOSE rulebook scorer.

`score_requirement(text)` runs every *automatable* rule from
data/rules/incose_rulebook.json against a single requirement's text and
reports which rules passed, which failed (with a human-readable reason
each), and an overall numeric compliance score. This is pure, deterministic
Python -- regex/word-list/structural checks only, no LLM call -- because
its output is what later scores the LLM's candidate rewrites and picks the
recommendation; that scoring has to be reproducible.

This module is intentionally self-contained (it does not import
src/rules/detectors.py): each check here is written directly from the
literal INCOSE rule text so that, e.g., R7's word list is exactly INCOSE's
R7 word list rather than the broader/merged vague-term heuristics detectors.py
uses for showing suggestions to a human. The two modules serve different
purposes -- detectors.py produces human-facing defect suggestions, this
module produces a formal, rule-by-rule compliance score -- and are allowed
to disagree at the margins.

Several INCOSE rules are, by their own definition, not checkable from a
single requirement's text (they compare across a whole requirement set, or
need an external glossary/style guide) -- those are marked
"automatable": false in the rulebook and are skipped here. See each rule's
"rationale_not_automatable" in incose_rulebook.json.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_RULEBOOK_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "rules" / "incose_rulebook.json"
)


@dataclass(frozen=True)
class FailedRule:
    id: str
    title: str
    category: str
    reasons: list[str]


@dataclass(frozen=True)
class ScoreResult:
    passed: list[str]
    failed: list[FailedRule]
    score: float
    total_rules: int


@functools.lru_cache(maxsize=4)
def load_rulebook(path: Path | None = None) -> list[dict]:
    """Loads and caches data/rules/incose_rulebook.json's rule list."""
    rulebook_path = path or _RULEBOOK_PATH
    data = json.loads(rulebook_path.read_text(encoding="utf-8"))
    return data["rules"]


def _automatable_rules(path: Path | None = None) -> list[dict]:
    return [r for r in load_rulebook(path) if r["automatable"]]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _phrase_pattern(phrases: list[str]) -> re.Pattern:
    """Builds a case-insensitive alternation over literal phrases (internal
    whitespace in a phrase matches flexibly), longest phrase first so
    multi-word phrases win over a word they contain.

    A `\\b` boundary is only added on a side whose edge character is a word
    character -- a phrase like "max." or "100%" ends on punctuation, and
    `\\b` can never match between two non-word characters (e.g. '.' then a
    following space), so an unconditional trailing `\\b` would silently
    make such phrases never match.
    """
    parts = []
    for phrase in phrases:
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        prefix = r"\b" if re.match(r"\w", phrase[0]) else ""
        suffix = r"\b" if re.match(r"\w", phrase[-1]) else ""
        parts.append(prefix + escaped + suffix)
    parts.sort(key=len, reverse=True)
    return re.compile("(?:" + "|".join(parts) + ")", re.IGNORECASE)


_SENTENCE_BOUNDARY = re.compile(r"[.!?]+(?:\s+|$)")


def _split_sentences(text: str) -> list[str]:
    spans = []
    start = 0
    for m in _SENTENCE_BOUNDARY.finditer(text):
        spans.append(text[start:m.end()])
        start = m.end()
    if start < len(text):
        spans.append(text[start:])
    return spans or [text]


_NUMBER = re.compile(r"[+\-]?\d+(?:\.\d+)?")
_WORD_AFTER = re.compile(r"\s*-?\s*([A-Za-z%°µΩ][\w%°µΩ/]*)")
_TOLERANCE_CONTINUATION = re.compile(r"\s*(?:\+/-|\+-|±)")


def _bare_numbers(text: str) -> list[str]:
    """Numeric literals with nothing after them describing what they
    measure -- shared by R6 (units) and R33 (range/tolerance presence)."""
    bare = []
    for m in _NUMBER.finditer(text):
        start, end = m.span()
        if start > 0 and text[start - 1].isalpha():
            continue  # fused onto a preceding identifier/code, e.g. "DO-276"
        if start >= 2 and text[start - 1] == "-" and text[start - 2].isalpha():
            continue
        if (start > 0 and text[start - 1] == ":") or (end < len(text) and text[end] == ":"):
            continue  # clock time, e.g. 00:00:00
        after = text[end:end + 20]
        if _TOLERANCE_CONTINUATION.match(after):
            continue
        if _WORD_AFTER.match(after):
            continue
        bare.append(m.group(0))
    return bare


_ACTION_VERBS = {
    "activate", "adjust", "aggregate", "alert", "allow", "apply", "arm",
    "assert", "attenuate", "authenticate", "block", "calculate", "capture",
    "clear", "close", "command", "compute", "configure", "correct",
    "deactivate", "decrypt", "deploy", "detect", "disable", "discard",
    "disengage", "display", "double", "drive", "enable", "encrypt",
    "engage", "enter", "execute", "extend", "filter", "flag", "flash",
    "generate", "halt", "highlight", "hold", "identify", "illuminate",
    "indicate", "initialize", "initiate", "isolate", "issue", "limit",
    "log", "maintain", "modulate", "monitor", "notify", "open", "output",
    "overwrite", "parse", "poll", "process", "project", "provide", "pump",
    "read", "record", "reduce", "reject", "release", "render", "report",
    "reset", "resume", "retry", "sample", "save", "scale", "scan", "send",
    "set", "shunt", "shutdown", "sound", "store", "switch", "target",
    "terminate", "track", "transition", "transmit", "trigger", "update",
    "upload", "verify", "write",
}


# ---------------------------------------------------------------------------
# Rule checks. Each takes the requirement text and returns a list of
# human-readable failure reasons -- an empty list means the rule passed.
# ---------------------------------------------------------------------------

_EARS_LEADING_TRIGGERS = {"when", "while", "if", "where"}


def _check_r1(text: str) -> list[str]:
    stripped = text.strip()
    first_word_m = re.match(r"[A-Za-z]+", stripped)
    first_word = first_word_m.group(0).lower() if first_word_m else ""
    shall_matches = list(re.finditer(r"\bshall\b", stripped, re.IGNORECASE))

    if len(shall_matches) != 1:
        return [
            f"Expected exactly one 'shall' clause to match a single EARS pattern; "
            f"found {len(shall_matches)}."
        ]

    if first_word in _EARS_LEADING_TRIGGERS:
        comma_idx = stripped.find(",")
        if comma_idx == -1 or comma_idx > shall_matches[0].start():
            return [
                f"'{first_word.capitalize()}' trigger clause must be followed by a "
                "comma before the 'the <system> shall <response>' clause."
            ]
        return []

    after_shall = stripped[shall_matches[0].end():]
    m = re.search(r"\b(if|when|while|unless)\b", after_shall, re.IGNORECASE)
    if m:
        return [
            f"Conditional word '{m.group(0)}' appears after 'shall' instead of "
            "leading the sentence as an EARS trigger clause."
        ]
    return []


_PASSIVE_SHALL_BE = re.compile(r"\bshall\s+be\s+([A-Za-z]+ed|[A-Za-z]+en)\b", re.IGNORECASE)


def _check_r2(text: str) -> list[str]:
    matches = [m.group(0) for m in _PASSIVE_SHALL_BE.finditer(text)]
    if matches:
        return [f"Passive construction '{m}' hides the responsible actor." for m in matches]
    return []


def _check_r5(text: str) -> list[str]:
    shall_m = re.search(r"\bshall\b", text, re.IGNORECASE)
    if not shall_m:
        return []
    prefix = text[:shall_m.start()]
    last_comma = prefix.rfind(",")
    subject_region = prefix[last_comma + 1:] if last_comma != -1 else prefix
    m = re.match(r"\s*(A|An)\b", subject_region)
    if m:
        return [
            f"Subject uses the indefinite article '{m.group(1)}'; use 'the' to refer "
            "to the specific entity (e.g. 'The <system> shall...')."
        ]
    return []


def _check_r6(text: str) -> list[str]:
    return [f"Numeric value '{n}' has no unit of measure stated." for n in _bare_numbers(text)]


_R7_TERMS = [
    # Literal INCOSE R7 examples.
    "some", "any", "allowable", "several", "many", "a lot of", "a few",
    "almost always", "very nearly", "nearly", "about", "close to", "almost",
    "approximate", "ancillary", "relevant", "routine", "common", "generic",
    "significant", "flexible", "expandable", "typical", "sufficient",
    "adequate", "appropriate", "efficient", "effective", "proficient",
    "reasonable", "customary",
    # INCOSE frames both lists with "such as" (non-exhaustive); these are
    # additional words that provide the same kind of vague, unquantifiable
    # qualification R7 targets -- speed/manner/quality adjectives with no
    # measurable criterion attached.
    "fast", "rapid", "rapidly", "quickly", "swiftly", "promptly",
    "immediately", "instantly", "continuously", "continually",
    "permanently", "negligible", "trivial", "minor", "excessive",
    "extreme", "substantial", "considerable", "normal", "nominal",
    "standard", "comprehensive", "thorough", "detailed", "clear", "crisp",
    "neat", "nicely", "cool", "stuff", "stable", "robust", "accurate",
    "accurately", "precise", "precisely", "safely", "securely", "smoothly",
    "successfully", "properly", "suitably", "correctly", "satisfactorily",
    "user-friendly", "intuitive", "ergonomic", "high accuracy",
    "high precision", "low error", "low latency", "high speed",
    "efficiently", "effectively", "appropriately", "adequately",
    "sufficiently", "reasonably", "significantly", "fully", "completely",
]
_R7_PATTERN = _phrase_pattern(_R7_TERMS)


def _check_r7(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R7_PATTERN.finditer(text)})
    if matches:
        return [f"Contains vague term(s): {', '.join(matches)}."]
    return []


_R8_PHRASES = [
    # Literal INCOSE R8 examples.
    "so far as is possible", "as little as possible", "where possible",
    "as much as possible", "if it should prove necessary", "if necessary",
    "to the extent necessary", "as appropriate", "as required",
    "to the extent practical", "if practicable",
    # Same escape-clause spirit (per R8's own "such as" framing).
    "if practical", "if safe", "when safe to do so", "where applicable",
    "when appropriate", "to the extent possible",
]
_R8_PATTERN = _phrase_pattern(_R8_PHRASES)


def _check_r8(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R8_PATTERN.finditer(text)})
    if matches:
        return [f"Contains escape clause(s): {', '.join(matches)}."]
    return []


_R9_PATTERN = re.compile(
    r"\bincluding\s+but\s+not\s+limited\s+to\b|\betc\.?|(?<!\w)\band\s+so\s+on\b",
    re.IGNORECASE,
)


def _check_r9(text: str) -> list[str]:
    matches = sorted({m.group(0).lower().rstrip(".") for m in _R9_PATTERN.finditer(text)})
    if matches:
        return [f"Contains open-ended clause(s): {', '.join(matches)}."]
    return []


_R10_PHRASES = [
    # Literal INCOSE R10 examples.
    "to be designed to", "to be able to", "to be capable of", "to enable",
    "to allow",
    # Same superfluous-infinitive spirit as it actually shows up after
    # "shall" in practice ("the system shall be able to X"), not just in
    # the "to be able to" infinitive form INCOSE's example is written in.
    "be able to", "be capable of",
]
_R10_PATTERN = _phrase_pattern(_R10_PHRASES)


def _check_r10(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R10_PATTERN.finditer(text)})
    if matches:
        return [f"Contains superfluous infinitive(s): {', '.join(matches)}."]
    return []


_TRIGGER_WORD = re.compile(r"\b(if|when|while|unless)\b", re.IGNORECASE)
_AND_OR = re.compile(r"\b(and|or)\b", re.IGNORECASE)


def _check_r11(text: str) -> list[str]:
    triggers = list(_TRIGGER_WORD.finditer(text))
    if len(triggers) < 2:
        return []
    for i in range(len(triggers) - 1):
        between = text[triggers[i].end():triggers[i + 1].start()]
        if _AND_OR.search(between):
            return [
                "Multiple conditions are combined with 'and'/'or' in one clause; "
                "use a separate clause for each condition."
            ]
    return []


def _check_r14(text: str) -> list[str]:
    reasons = []
    stripped = text.strip()
    if not re.search(r"[.!?]$", stripped):
        reasons.append("Statement does not end with terminal punctuation.")
    if re.search(r"[.,;:]{2,}", stripped):
        reasons.append("Contains doubled punctuation.")
    if "  " in stripped:
        reasons.append("Contains doubled whitespace.")
    if stripped.count("(") != stripped.count(")"):
        reasons.append("Unmatched parentheses.")
    if stripped.count('"') % 2 != 0:
        reasons.append('Unmatched quotation marks.')
    return reasons


def _check_r16(text: str) -> list[str]:
    count = len(re.findall(r"\bnot\b", text, re.IGNORECASE))
    if count:
        return [f"Uses the word 'not' ({count} occurrence(s)); rephrase as a positive statement."]
    return []


_KNOWN_UNIT_SLASH = re.compile(r"^(?:km|m|mi|ft|rad|nm)/(?:h|hr|s|sec|min)$", re.IGNORECASE)
_FRACTION_SLASH = re.compile(r"^\d+/\d+$")


def _check_r17(text: str) -> list[str]:
    if "/" not in text:
        return []
    for m in re.finditer(r"\S*/\S*", text):
        token = m.group(0).strip(".,;:()")
        if _KNOWN_UNIT_SLASH.match(token) or _FRACTION_SLASH.match(token):
            continue
        return [
            f"Uses the oblique symbol '/' in '{token}', which is reserved for units "
            "(e.g. km/h) or numeric fractions."
        ]
    return []


def _check_r18(text: str) -> list[str]:
    reasons = []
    for sentence in _split_sentences(text):
        count = len(re.findall(r"\bshall\b", sentence, re.IGNORECASE))
        if count >= 2:
            reasons.append(
                f"Sentence contains {count} 'shall' statements; write one 'shall' "
                "per sentence."
            )
    return reasons


_R19_TERMS = [
    "and", "or", "then", "unless", "but", "as well as", "but also",
    "however", "whether", "meanwhile", "whereas", "on the other hand",
    "otherwise",
]
_R19_PATTERN = _phrase_pattern(_R19_TERMS)


def _check_r19(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R19_PATTERN.finditer(text)})
    if matches:
        return [f"Contains combinator word(s) joining clauses: {', '.join(matches)}."]
    return []


_R20_PHRASES = [
    "in order to", "so that", "for the purpose of", "the intent of",
    "the reason for",
]
_R20_PATTERN = _phrase_pattern(_R20_PHRASES)


def _check_r20(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R20_PATTERN.finditer(text)})
    if matches:
        return [f"Contains purpose phrase(s): {', '.join(matches)}."]
    return []


def _check_r21(text: str) -> list[str]:
    reasons = []
    for m in re.finditer(r"\(([^)]*)\)|\[([^\]]*)\]", text):
        content = (m.group(1) or m.group(2) or "").strip()
        if content and " " in content:
            reasons.append(
                f"Parenthetical '({content})' contains subordinate text; state it "
                "as its own clause or remove it."
            )
    return reasons


_R22_PHRASES = [
    "the following", "such as", "various", "a variety of", "these parameters",
    "these items", "several types of",
]
_R22_PATTERN = _phrase_pattern(_R22_PHRASES)


def _check_r22(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R22_PATTERN.finditer(text)})
    if matches:
        return [
            f"Refers to a set with a group noun instead of enumerating it: "
            f"{', '.join(matches)}."
        ]
    return []


_R24_TERMS = [
    "it", "its", "this", "that", "these", "those", "they", "them", "their",
    "one", "anyone", "someone", "anything", "something", "he", "she", "him",
    "her",
]
_R24_PATTERN = _phrase_pattern(_R24_TERMS)


def _check_r24(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R24_PATTERN.finditer(text)})
    if matches:
        return [f"Uses personal/indefinite pronoun(s): {', '.join(matches)}."]
    return []


_R26_TERMS = ["100%", "all", "every", "always", "never", "none", "zero defects"]
_R26_PATTERN = _phrase_pattern(_R26_TERMS)


def _check_r26(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R26_PATTERN.finditer(text)})
    if matches:
        return [f"Uses unachievable absolute(s): {', '.join(matches)}."]
    return []


_R27_PHRASES = [
    "typically", "usually", "generally", "normally", "in most cases",
    "under normal circumstances",
]
_R27_PATTERN = _phrase_pattern(_R27_PHRASES)


def _check_r27(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R27_PATTERN.finditer(text)})
    if matches:
        return [
            f"Applicability is implied rather than explicit: {', '.join(matches)}."
        ]
    return []


def _check_r28(text: str) -> list[str]:
    shall_m = re.search(r"\bshall\b", text, re.IGNORECASE)
    if not shall_m:
        return []
    main_clause = text[shall_m.end():]
    for m in re.finditer(r"\s+(and|or)\s+", main_clause, re.IGNORECASE):
        right = main_clause[m.end():].strip()
        right_first_m = re.match(r"[A-Za-z]+", right)
        right_first = right_first_m.group(0).lower() if right_first_m else ""
        if right_first in _ACTION_VERBS:
            return [
                f"A single condition drives multiple actions joined by '{m.group(1)}'; "
                "express one action per conditioned clause."
            ]
    return []


_R32_PATTERN = _phrase_pattern(["all", "any", "both"])


def _check_r32(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R32_PATTERN.finditer(text)})
    if matches:
        return [
            f"Uses {', '.join(matches)} for universal quantification; use 'each' instead."
        ]
    return []


_TOLERANCE_MARKERS = re.compile(
    r"\+/-|\+-|±|\bbetween\b|\brange\b|\bto\s+\d", re.IGNORECASE
)


_BOUND_WORDS = re.compile(
    r"\b(?:maximum|minimum|exceeds?|below|above|within|up\s+to|less\s+than|"
    r"greater\s+than|at\s+least|no\s+more\s+than|no\s+less\s+than|"
    r"limit(?:ed)?\s+to|under|over)\b",
    re.IGNORECASE,
)
_SETPOINT_MARKER = re.compile(r"\b(?:at|of)\s+[+\-]?\d", re.IGNORECASE)


def _check_r33(text: str) -> list[str]:
    if _TOLERANCE_MARKERS.search(text):
        return []
    if _BOUND_WORDS.search(text):
        # A one-sided bound/threshold ("within 100 ms", "below 65C",
        # "at least 40 dB") already fully defines the acceptable range on
        # its own -- it doesn't also need a +/- tolerance.
        return []
    if _SETPOINT_MARKER.search(text):
        return [
            "States a numeric setpoint with no defined tolerance or range; add "
            "an appropriate +/- tolerance or bounding range."
        ]
    return []


_R34_TERMS = [
    "optimize", "optimide", "optimizes", "optimized", "optimization",
    "maximize", "maximizes", "maximized", "minimize", "minimizes",
    "minimized", "optimal", "optimum", "improve", "improves", "improved",
    "enhance", "enhances", "enhanced",
]
_R34_PATTERN = _phrase_pattern(_R34_TERMS)


def _check_r34(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R34_PATTERN.finditer(text)})
    if matches:
        return [
            f"Uses unbounded performance/optimization language ({', '.join(matches)}) "
            "with no measurable target; state a specific numeric performance target."
        ]
    return []


_R35_TERMS = [
    # Literal INCOSE R35 examples.
    "eventually", "until", "before", "after", "as", "once", "earliest",
    "latest", "instantaneous", "simultaneous", "at last",
    # Same indefinite-temporal-keyword spirit (per R35's own "such as" framing).
    "daily", "weekly", "monthly", "periodically", "regularly", "frequently",
    "occasionally", "intermittently", "as soon as possible", "without delay",
]
_R35_PATTERN = _phrase_pattern(_R35_TERMS)


def _check_r35(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R35_PATTERN.finditer(text)})
    if matches:
        return [f"Uses indefinite temporal keyword(s): {', '.join(matches)}."]
    return []


_ACRONYM = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*\b")


def _check_r37(text: str) -> list[str]:
    reasons = []
    for m in _ACRONYM.finditer(text):
        acronym = m.group(0)
        tail = text[m.end():m.end() + 2]
        if tail.startswith(" ("):
            continue  # assume an inline expansion follows
        reasons.append(
            f"Acronym '{acronym}' has no inline expansion; ensure it is defined "
            "consistently in the requirement set's glossary."
        )
    return reasons


_R38_TERMS = [
    "approx.", "min.", "max.", "temp.", "qty.", "spec.", "req.", "e.g.",
    "i.e.", "vs.", "w/o", "w/",
]
_R38_PATTERN = _phrase_pattern(_R38_TERMS)


def _check_r38(text: str) -> list[str]:
    matches = sorted({m.group(0).lower() for m in _R38_PATTERN.finditer(text)})
    if matches:
        return [f"Uses abbreviation(s): {', '.join(matches)}."]
    return []


_BAD_DECIMAL = re.compile(r"(?<!\d)\.\d+")


def _check_r40(text: str) -> list[str]:
    matches = _BAD_DECIMAL.findall(text)
    if matches:
        return [
            f"Decimal value(s) missing a leading zero ({', '.join(matches)}); use "
            "a consistent '0.X' format."
        ]
    return []


CHECK_REGISTRY: dict[str, Callable[[str], list[str]]] = {
    "R1": _check_r1,
    "R2": _check_r2,
    "R5": _check_r5,
    "R6": _check_r6,
    "R7": _check_r7,
    "R8": _check_r8,
    "R9": _check_r9,
    "R10": _check_r10,
    "R11": _check_r11,
    "R14": _check_r14,
    "R16": _check_r16,
    "R17": _check_r17,
    "R18": _check_r18,
    "R19": _check_r19,
    "R20": _check_r20,
    "R21": _check_r21,
    "R22": _check_r22,
    "R24": _check_r24,
    "R26": _check_r26,
    "R27": _check_r27,
    "R28": _check_r28,
    "R32": _check_r32,
    "R33": _check_r33,
    "R34": _check_r34,
    "R35": _check_r35,
    "R37": _check_r37,
    "R38": _check_r38,
    "R40": _check_r40,
}


def score_requirement(text: str, rulebook_path: Path | None = None) -> ScoreResult:
    """Runs every automatable INCOSE rule against ``text``.

    Pure and deterministic: no network/LLM call, no randomness. Safe to run
    on every candidate rewrite to pick the best-scoring one.
    """
    rules = _automatable_rules(rulebook_path)

    missing = [r["id"] for r in rules if r["id"] not in CHECK_REGISTRY]
    if missing:
        raise NotImplementedError(
            f"incose_rulebook.json marks {missing} as automatable but "
            "incose_scorer.CHECK_REGISTRY has no check function for them."
        )

    passed: list[str] = []
    failed: list[FailedRule] = []
    for rule in rules:
        reasons = CHECK_REGISTRY[rule["id"]](text)
        if reasons:
            failed.append(
                FailedRule(
                    id=rule["id"],
                    title=rule["title"],
                    category=rule["category"],
                    reasons=reasons,
                )
            )
        else:
            passed.append(rule["id"])

    total = len(rules)
    # Use 2 decimal places for more precision - with 28 rules, single decimal
    # only gives values like 96.4, 100.0, 92.9, making it hard to distinguish
    # candidates that differ by only 1-2 rules
    score = round(100.0 * len(passed) / total, 2) if total else 0.0
    return ScoreResult(passed=passed, failed=failed, score=score, total_rules=total)

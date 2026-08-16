"""Python-detectable requirement defect detectors.

Each detector is a plain regex/heuristic pattern check over a single
requirement's text -- no lookup tables keyed on the golden dataset. They
are meant to catch the *mechanically* detectable slice of INCOSE-style
requirement defects (vague wording, negative constraints, missing
units/quantification, compound "and/or" requirements, and EARS trigger
clauses that are missing or out of place). Anything that requires real
domain/world knowledge (e.g. "nominal ambient temperature should not map
to an emergency shutdown", "TCAS not installed but still computing
advisories") is out of scope on purpose: a regex cannot know that.

Detectors return :class:`Finding` objects with:
  - violation_type: stable short code identifying which detector/category fired
  - span: the exact matched substring from the requirement text
  - start / end: character offsets of the match within the input text
  - confidence: heuristic 0-1 confidence that this is a genuine defect
  - reason: a plain-language suggestion, written to be shown directly to
    a human requirements author (not a developer-facing debug message)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    violation_type: str
    span: str
    start: int
    end: int
    confidence: float
    reason: str


# ---------------------------------------------------------------------------
# 1. Vague-term detector (INCOSE R7 word list)
# ---------------------------------------------------------------------------
# INCOSE's "Guide for Writing Requirements" rule R7 calls out vague,
# unquantifiable words and phrases that make a requirement impossible to
# verify objectively. The list below groups the classic R7 offenders (plus
# the common variants requirement authors actually write) by why they are
# vague, so the suggestion text can explain *what* to fix rather than just
# flagging a word.
#
# Longer/more specific phrases are listed before the single words they
# contain so overlapping matches don't double-report the same span.

_VAGUE_TERM_RULES: list[tuple[str, str, str, float]] = [
    # (regex, category, reason, confidence)
    # --- escape clauses: make the requirement optional / non-binding ---
    (r"if\s+(?:it\s+is\s+)?practical", "escape_clause",
     "'{match}' is an escape clause that makes compliance optional; state the "
     "condition under which the behavior is mandatory, or remove the qualifier.", 0.9),
    (r"if\s+(?:it\s+is\s+)?possible", "escape_clause",
     "'{match}' is an escape clause that makes compliance optional; state the "
     "condition under which the behavior is mandatory, or remove the qualifier.", 0.9),
    (r"where\s+applicable", "escape_clause",
     "'{match}' is an escape clause; either the requirement always applies, or "
     "it needs an explicit applicability condition (e.g. an EARS 'Where' clause).", 0.85),
    (r"as\s+(?:necessary|required|needed)", "escape_clause",
     "'{match}' leaves the actual trigger and action undefined; state the "
     "specific condition and response instead.", 0.75),
    (r"when\s+appropriate", "escape_clause",
     "'{match}' defers the decision of when to act to the implementer; state "
     "the specific triggering condition.", 0.85),
    (r"if\s+safe(?:\s+to\s+do\s+so)?", "escape_clause",
     "'{match}' hides the definition of \"safe\" outside the specification; "
     "state the measurable condition that defines a safe state.", 0.85),
    (r"when\s+safe\s+to\s+do\s+so", "escape_clause",
     "'{match}' hides the definition of \"safe\" outside the specification; "
     "state the measurable condition that defines a safe state.", 0.85),
    (r"to\s+the\s+extent\s+possible", "escape_clause",
     "'{match}' is an escape clause that makes compliance optional.", 0.8),

    # --- open-ended / unbounded scope ---
    (r"as\s+a\s+minimum", "open_ended_scope",
     "'{match}' leaves the requirement's scope unbounded; list the specific, "
     "complete set of items or actions required.", 0.9),
    (r"at\s+a\s+minimum", "open_ended_scope",
     "'{match}' leaves the requirement's scope unbounded; list the specific, "
     "complete set of items or actions required.", 0.9),
    (r"at\s+least", "open_ended_scope",
     "'{match}' leaves the upper bound undefined; state both the minimum and "
     "an explicit maximum or exact value.", 0.55),
    (r"(?:but\s+)?not\s+limited\s+to", "open_ended_scope",
     "'{match}' leaves the requirement's scope open-ended and untestable; "
     "enumerate the complete, closed set of items.", 0.9),
    (r"(?:etc\.?|and\s+so\s+on|and\s+so\s+forth|and\s+other[s]?)\b", "open_ended_scope",
     "'{match}' leaves part of the requirement unspecified; enumerate the "
     "complete set of items or actions instead of trailing off.", 0.85),
    (r"\btbd\b|\bto\s+be\s+determined\b|\bto\s+be\s+defined\b|\btbc\b|\bto\s+be\s+confirmed\b",
     "open_ended_scope",
     "'{match}' is a placeholder; the requirement is incomplete until a "
     "concrete value is filled in.", 0.95),

    # --- unbounded optimization directives ---
    (r"\boptimi[sz]e[sd]?\b|\boptimi[sz]ation\b", "unbounded_optimization",
     "'{match}' names a goal, not a testable target; state the specific "
     "metric and bound (e.g. a maximum, minimum, or trade-off limit).", 0.85),
    (r"\bmaximi[sz]e[sd]?\b", "unbounded_optimization",
     "'{match}' has no provable upper limit; state the concrete numeric "
     "target or constraint that defines \"maximized\".", 0.85),
    (r"\bminimi[sz]e[sd]?\b", "unbounded_optimization",
     "'{match}' has no provable lower limit; state the concrete numeric "
     "target or constraint that defines \"minimized\".", 0.85),
    (r"\boptimum\b|\boptimal\b|\bideal\b|\bperfect(?:ly)?\b|\bbest\b", "unbounded_optimization",
     "'{match}' is a value judgement with no objective test; state the "
     "specific measurable target.", 0.6),

    # --- subjective UX / usability terms ---
    (r"user[\s-]?friendly|intuitive|ergonomic|easy[\s-]to[\s-]use|"
     r"straightforward|comprehensible", "subjective_ux",
     "'{match}' describes a subjective user impression, not a testable "
     "behavior; state an objective, measurable criterion (e.g. clicks to "
     "reach a screen, response time, contrast ratio).", 0.85),

    # --- vague quality adverbs (manner of performing an action) ---
    (r"\b(?:adequately|properly|appropriately|suitably|correctly|effectively|"
     r"efficiently|successfully|accurately|precisely|satisfactorily|"
     r"sufficiently|reasonably|safely|securely|smoothly|gradually|rapidly|"
     r"swiftly|quickly|promptly|instantly|immediately)\b", "vague_manner_adverb",
     "'{match}' describes *how well* the system should act without a "
     "measurable criterion; replace it with a specific numeric bound, "
     "tolerance, or standard.", 0.75),

    # --- vague quality adjectives ---
    (r"\b(?:adequate|appropriate|suitable|proper|desired|acceptable|"
     r"reasonable|sufficient|effective|efficient|accurate|precise|robust|"
     r"flexible|stable|comprehensive|thorough|detailed|clear|crisp|sharp|"
     r"vivid|bright|loud|faint|negligible|trivial|minor|excessive|extreme|"
     r"significant|substantial|considerable|normal|nominal|standard|"
     r"default|comprehensive|complete(?:ly)?|full(?:y)?|total(?:ly)?)\b",
     "vague_quality_adjective",
     "'{match}' is a qualitative judgement rather than a measurable "
     "criterion; replace it with a specific numeric value, tolerance, or "
     "reference standard.", 0.55),

    # --- approximation markers ---
    (r"(?<![\w-])(?:approximately|about|around|roughly|nearly|more\s+or\s+less)\b",
     "approximation",
     "'{match}' introduces an undefined tolerance; state the value together "
     "with an explicit +/- tolerance instead.", 0.6),

    # --- vague temporal expressions (no bound given) ---
    (r"\bas\s+soon\s+as\s+possible\b|\basap\b|\bwithout\s+delay\b",
     "vague_temporal",
     "'{match}' has no defined time bound; state a specific maximum "
     "response time.", 0.9),
    (r"\b(?:periodically|regularly|frequently|occasionally|intermittently|"
     r"continuously|continually|permanently|constantly|always)\b",
     "vague_temporal",
     "'{match}' does not specify a concrete rate or duration; state an "
     "explicit interval, frequency, or sampling rate.", 0.75),
    (r"\b(?:daily|weekly|monthly|yearly)\b", "vague_temporal",
     "'{match}' does not specify an exact time or trigger; state the exact "
     "interval (e.g. 'every 24 hours at 00:00:00 UTC').", 0.55),
    (r"\bin\s+a\s+timely\s+manner\b|\btimely\b", "vague_temporal",
     "'{match}' has no defined time bound; state a specific maximum "
     "response time.", 0.85),
    (r"\bfast\b|\bslow(?:ly)?\b|\bhigh\s+speed\b|\blow\s+latency\b",
     "vague_temporal",
     "'{match}' is a relative speed descriptor; state an explicit time "
     "bound or rate.", 0.65),

    # --- informal / marketing / slang language ---
    (r"\b(?:cool|awesome|neat|pretty|beautiful|sleek|super|ultra|mega|"
     r"next[\s-]?gen(?:eration)?|cutting[\s-]?edge|state[\s-]?of[\s-]?the[\s-]?art|"
     r"advanced|smart|okay|ok|so-so|decent|great|nice(?:ly)?)\b",
     "informal_language",
     "'{match}' is informal or marketing language, not an engineering "
     "specification; replace it with the specific mechanism or metric "
     "intended.", 0.6),
    (r"\b(?:stuff|things?|bits?|junk)\b", "informal_language",
     "'{match}' is a vague filler noun; name the specific item(s) or data "
     "referred to.", 0.6),
    (r"\bhandle\s+it\b|\bdeal\s+with\s+it\b|\btake\s+care\s+of\s+it\b|"
     r"\bfix\s+the\s+situation\b|\bsort\s+(?:it\s+)?out\b|\bhunt\s+around\b|"
     r"\blook\s+after\b|\btoss\s+out\b", "vague_action_phrase",
     "'{match}' is a vague placeholder action; state the specific, testable "
     "action the system must take.", 0.85),

    # --- unquantified accuracy / high-level descriptors ---
    (r"\bhigh\s+accuracy\b|\bhigh\s+precision\b|\blow\s+error\b",
     "unquantified_precision",
     "'{match}' has no numeric tolerance; state the specific accuracy, "
     "error bound, or confidence interval required.", 0.8),
]

# Pre-compile once, longest-phrase-first order preserved from the list above.
_VAGUE_TERM_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), category, reason, confidence)
    for pattern, category, reason, confidence in _VAGUE_TERM_RULES
]


# A handful of words in the R7 list are also common, unambiguous technical
# verbs/nouns ("shall clear the fault log", "the AES-256 standard") --
# context-sensitive exceptions to cut down obvious false positives without
# dropping the word from the list entirely (the word itself is still worth
# flagging in its vague sense).
def _preceded_by_shall(text: str, start: int, _end: int) -> bool:
    return bool(re.search(r"\bshall\s*$", text[:start], re.IGNORECASE))


def _preceded_by_digit_token(text: str, start: int, _end: int) -> bool:
    before = text[:start].rstrip()
    m = re.search(r"(\S+)\s*$", before)
    return bool(m and re.search(r"\d", m.group(1)))


_VAGUE_TERM_EXCEPTIONS = {
    "clear": _preceded_by_shall,  # "shall clear the log" is an ordinary verb, not "display clearly"
    "standard": _preceded_by_digit_token,  # "the AES-256 standard" names a spec, not "standard stuff"
}


def detect_vague_terms(text: str) -> list[Finding]:
    """Flag INCOSE R7-style vague/unquantifiable words and phrases.

    Matches are non-overlapping: once a span of text has been claimed by
    an earlier (more specific) pattern, later patterns cannot re-flag the
    same characters.
    """
    findings: list[Finding] = []
    claimed: list[tuple[int, int]] = []

    for regex, category, reason_template, confidence in _VAGUE_TERM_PATTERNS:
        for m in regex.finditer(text):
            start, end = m.start(), m.end()
            if any(start < c_end and end > c_start for c_start, c_end in claimed):
                continue
            if category == "open_ended_scope" and m.group(0).lower() in (
                "at least", "as a minimum", "at a minimum",
            ):
                # "at least 99.9%" / "a minimum rate of 10 Hz" already carries an
                # explicit bound nearby -- only the *unbounded* uses ("at least"
                # with no number in sight) are genuinely vague.
                lookahead = text[end:end + 30]
                if re.search(r"\d", lookahead):
                    continue
            exception = _VAGUE_TERM_EXCEPTIONS.get(m.group(0).lower())
            if exception and exception(text, start, end):
                continue
            claimed.append((start, end))
            findings.append(
                Finding(
                    violation_type="vague_term",
                    span=m.group(0),
                    start=start,
                    end=end,
                    confidence=confidence,
                    reason=reason_template.format(match=m.group(0)) + f" [{category}]",
                )
            )

    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# 2. Negation / negative-constraint detector
# ---------------------------------------------------------------------------
# EARS/INCOSE guidance (and DO-178C-style writing rules) prefer positive,
# active statements of required behavior over negative constraints: "shall
# not X" or "shall avoid X" describes a forbidden state without saying what
# the system *should* do instead, which is both hard to verify and easy to
# satisfy trivially (do nothing).

_NEGATIVE_CONSTRAINT_RULES: list[tuple[str, str, float]] = [
    (r"\bshall\s+not\b", "hard_negation",
     "'{match}' states what the system must NOT do; rewrite as a positive "
     "statement of the required behavior (e.g. the safe/active response "
     "instead of the forbidden one)."),
    (r"\bshall\s+never\b|\bnever\b", "absolute_negation",
     "'{match}' is an absolute negative constraint that is hard to verify "
     "and often hides the required positive/fallback behavior; rewrite as "
     "a positive statement (e.g. an explicit limit or bound)."),
    (r"\bshall\s+(?:only\s+)?avoid\b|\bavoid\b", "soft_negative_verb",
     "'{match}' is a soft negative verb; rewrite as an explicit positive "
     "action (e.g. what the system actively does instead)."),
    (r"\bshall\s+prevent\b|\bprevent\b", "soft_negative_verb",
     "'{match}' states a prohibition without saying how; rewrite as the "
     "specific active mechanism (e.g. asserting a lock, rejecting an "
     "input) that achieves the prevention."),
    (r"\bshall\s+prohibit\b|\bprohibit\b", "soft_negative_verb",
     "'{match}' states a prohibition without saying how; rewrite as the "
     "specific active mechanism that enforces it."),
    (r"\bshall\s+bypass\b", "soft_negative_verb",
     "'{match}' is a soft negative verb; state the explicit positive "
     "action taken instead."),  # bare "bypass" is excluded: it's usually a
     # noun in hardware contexts ("bypass valve", "bypass circuit"), only
     # the verb form "shall bypass X" is the negative-constraint pattern.
    (r"\b(?:shall\s+(?:display|accept|use|allow|permit)\s+)?\bno\b\s+\w+",
     "negative_determiner",
     "'{match}' uses a negative determiner to bound behavior; state the "
     "positive rule (e.g. what IS allowed) instead."),
    (r"\bnone\b|\bneither\b", "negative_determiner",
     "'{match}' is a negative determiner; state the positive rule instead."),
]

_NEGATIVE_CONSTRAINT_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), category, reason_template)
    for pattern, category, reason_template in _NEGATIVE_CONSTRAINT_RULES
]

# Prefixes that turn a word into a negative-of-a-negative when preceded by
# "not"/"without" elsewhere in the same sentence -- classic double-negative
# constructions like "shall not leave ... un-trimmed" or "shall not accept
# ... invalid ... without verification".
_NEGATIVE_PREFIXED_WORD = re.compile(
    r"\b(?:un|non|dis|in|im)-?(?:trimmed|commanded|verified|certified|"
    r"authorized|authenticated|available|valid|active|stable|safe|secure|"
    r"tested|calibrated|configured|initialized|responsive|reliable)\b",
    re.IGNORECASE,
)
_NEGATION_CUE = re.compile(
    r"\b(?:not|never|without|no|none|neither|avoid|prevent|prohibit)\b",
    re.IGNORECASE,
)


def detect_negative_constraints(text: str) -> list[Finding]:
    """Flag "shall not"/"never"/"prevent"/"avoid" and double-negative phrasing."""
    findings: list[Finding] = []
    claimed: list[tuple[int, int]] = []

    for regex, category, reason_template in _NEGATIVE_CONSTRAINT_PATTERNS:
        for m in regex.finditer(text):
            start, end = m.start(), m.end()
            if any(start < c_end and end > c_start for c_start, c_end in claimed):
                continue
            claimed.append((start, end))
            confidence = 0.9 if category in ("hard_negation", "absolute_negation") else 0.75
            findings.append(
                Finding(
                    violation_type="negative_constraint",
                    span=m.group(0),
                    start=start,
                    end=end,
                    confidence=confidence,
                    reason=reason_template.format(match=m.group(0)) + f" [{category}]",
                )
            )

    # Double-negative check: two or more independent negation cues (e.g.
    # "not" plus a negatively-prefixed word, or "not" plus "without") in
    # the same sentence compound the ambiguity beyond either alone.
    negation_hits = list(_NEGATION_CUE.finditer(text))
    prefixed_hits = list(_NEGATIVE_PREFIXED_WORD.finditer(text))
    if negation_hits and prefixed_hits:
        for pm in prefixed_hits:
            # only counts as a double-negative if a distinct negation cue
            # appears elsewhere in the text (not the same token).
            other_cues = [nm for nm in negation_hits if not (nm.start() >= pm.start() and nm.end() <= pm.end())]
            if other_cues:
                start, end = pm.start(), pm.end()
                findings.append(
                    Finding(
                        violation_type="negative_constraint",
                        span=pm.group(0),
                        start=start,
                        end=end,
                        confidence=0.8,
                        reason=(
                            f"'{pm.group(0)}' combines with another negation elsewhere in "
                            "the sentence to form a double negative, which is hard to "
                            "parse unambiguously; rewrite the whole clause as a single "
                            "positive statement. [double_negative]"
                        ),
                    )
                )
    if len(negation_hits) >= 2:
        seen_spans = {(f.start, f.end) for f in findings}
        first, second = negation_hits[0], negation_hits[1]
        if (first.start(), first.end()) not in seen_spans:
            findings.append(
                Finding(
                    violation_type="negative_constraint",
                    span=text[first.start():negation_hits[-1].end()],
                    start=first.start(),
                    end=negation_hits[-1].end(),
                    confidence=0.6,
                    reason=(
                        "This sentence stacks multiple negations "
                        f"('{first.group(0)}', '{second.group(0)}', ...); rewrite as one "
                        "positive statement of the required behavior. [double_negative]"
                    ),
                )
            )

    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# 3. Missing-unit / missing-quantification detector
# ---------------------------------------------------------------------------

# A number is only flagged when it dangles with nothing describing what it
# counts (no unit, no counted noun like "clicks"/"parameters"/"retries" at
# all) -- e.g. "...shall not exceed 100." rather than "...shall not exceed
# 100 PSI." We deliberately do NOT maintain a fixed whitelist of "real"
# units: requiring a word of *any* kind after the number (an SI unit, a
# domain noun, a spelled-out unit) is enough to say the value is qualified,
# and keeps this a general pattern check instead of a lookup table.

_NUMBER = re.compile(r"[+\-]?\d+(?:\.\d+)?")
_WORD_AFTER = re.compile(r"\s*-?\s*([A-Za-z%°µΩ][\w%°µΩ/]*)")  # allows "512-byte" style fusion
_TOLERANCE_CONTINUATION = re.compile(r"\s*(?:\+/-|\+-|±)")
_SPELLED_NUMBER = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"once|twice|thrice)\b",
    re.IGNORECASE,
)
_THRESHOLD_WORDS = re.compile(
    r"\b(?:exceeds?|below|above|at\s+least|no\s+more\s+than|no\s+less\s+than|"
    r"maximum\s+of|minimum\s+of|greater\s+than|less\s+than|up\s+to|within|"
    r"limit(?:ed)?\s+to|under|over)\b",
    re.IGNORECASE,
)


def _preceded_by_code_prefix(text: str, start: int) -> bool:
    """True if the number is fused onto a preceding identifier/code, e.g.
    'DO-276', 'AES-256', 'Asset ID #I-20' -- not a bare measurement."""
    if start == 0:
        return False
    prev = text[start - 1]
    if prev.isalpha():
        return True
    if prev == "-" and start >= 2 and text[start - 2].isalpha():
        return True
    return False


def detect_missing_units(text: str) -> list[Finding]:
    """Flag numeric values that dangle with no accompanying unit/counted
    noun, and threshold language ("exceeds", "at least", "within", ...)
    used when the requirement contains no number anywhere to anchor it.
    """
    findings: list[Finding] = []
    numbers = list(_NUMBER.finditer(text))

    for m in numbers:
        start, end = m.start(), m.end()
        if _preceded_by_code_prefix(text, start):
            continue
        # "00:00:00 UTC" is a clock time, not an unquantified measurement.
        if (start > 0 and text[start - 1] == ":") or (end < len(text) and text[end] == ":"):
            continue
        after = text[end:end + 20]
        if _TOLERANCE_CONTINUATION.match(after):
            # This value feeds a following "+/- <bound> <unit>" clause;
            # the unit is judged on the bound that follows, not here.
            continue
        if _WORD_AFTER.match(after):
            continue  # qualified by a following unit/counted noun
        findings.append(
            Finding(
                violation_type="missing_unit",
                span=m.group(0),
                start=start,
                end=end,
                confidence=0.65,
                reason=(
                    f"The numeric value '{m.group(0)}' has nothing after it describing "
                    "what it measures; add an explicit engineering unit (e.g. ms, V, "
                    "PSI, %, degrees) so the value is unambiguous. [bare_number]"
                ),
            )
        )

    if not numbers and not _SPELLED_NUMBER.search(text):
        for m in _THRESHOLD_WORDS.finditer(text):
            findings.append(
                Finding(
                    violation_type="missing_unit",
                    span=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    confidence=0.6,
                    reason=(
                        f"'{m.group(0)}' implies a numeric threshold, but the requirement "
                        "contains no number at all; add the specific value and unit "
                        "being compared against. [unquantified_threshold]"
                    ),
                )
            )

    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# 4. Compound-requirement detector (INCOSE R19)
# ---------------------------------------------------------------------------
# INCOSE R19 ("Single Thought Sentences") prohibits combinators/conjunctions
# that stitch two separate requirements into one sentence. We look inside
# the "shall" clause (the actual required behavior, not the EARS trigger
# clause) for coordinating conjunctions, and boost confidence when both
# sides of the conjunction look like separate verb phrases (i.e. two
# distinct actions, not just a list of nouns for one action).

_ACTION_VERBS = {
    "activate", "adjust", "aggregate", "alert", "allow", "apply", "arm",
    "assert", "attenuate", "authenticate", "block", "calculate", "capture",
    "clear", "close", "command", "compute", "configure", "correct",
    "deactivate", "decrypt", "deploy", "detect", "disable", "discard",
    "disengage", "display", "double", "drive", "enable", "encrypt",
    "engage", "enter", "execute", "extend", "filter", "flag", "generate",
    "flash", "halt", "highlight", "hold", "identify", "illuminate", "indicate",
    "initialize", "initiate", "isolate", "issue", "limit", "log", "maintain",
    "modulate", "monitor", "notify", "open", "output", "overwrite", "parse",
    "poll", "process", "project", "provide", "pump", "read", "record",
    "reduce", "reject", "release", "render", "report", "reset", "resume",
    "retry", "sample", "save", "scale", "scan", "send", "set", "shunt",
    "shutdown", "sound", "store", "switch", "target", "terminate", "track",
    "transition", "transmit", "trigger", "update", "upload", "verify",
    "write",
}

_CONJUNCTION = re.compile(r"\s+(and|or)\s+(?!\s*/)", re.IGNORECASE)
_AND_OR_SLASH = re.compile(r"\band/or\b", re.IGNORECASE)


def _first_word(segment: str) -> str:
    m = re.match(r"[A-Za-z]+", segment.strip())
    return m.group(0).lower() if m else ""


_SENTENCE_BOUNDARY = re.compile(r"[.!?]+(?:\s+|$)")


def _split_sentences(text: str) -> list[tuple[int, int]]:
    """Split into (start, end) offsets on sentence-ending punctuation, so a
    correctly-split two-sentence fix ("Do X. When Y, do Z.") isn't mistaken
    for one sentence with two 'shall' statements."""
    spans = []
    start = 0
    for m in _SENTENCE_BOUNDARY.finditer(text):
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def detect_compound_requirement(text: str) -> list[Finding]:
    """Flag conjunctions ("and"/"or"/"and/or") joining multiple actions or
    multiple "shall" statements within a single requirement sentence.
    """
    findings: list[Finding] = []

    for sent_start, sent_end in _split_sentences(text):
        sentence = text[sent_start:sent_end]
        shall_matches = list(re.finditer(r"\bshall\b", sentence, re.IGNORECASE))

        if len(shall_matches) >= 2:
            findings.append(
                Finding(
                    violation_type="compound_requirement",
                    span=sentence[shall_matches[0].start():shall_matches[-1].end()],
                    start=sent_start + shall_matches[0].start(),
                    end=sent_start + shall_matches[-1].end(),
                    confidence=0.85,
                    reason=(
                        "This sentence contains multiple 'shall' statements; split it "
                        "into one requirement per 'shall'. [multiple_shall]"
                    ),
                )
            )

        main_clause_start = shall_matches[0].end() if shall_matches else 0
        main_clause = sentence[main_clause_start:]

        for m in _AND_OR_SLASH.finditer(main_clause):
            start = sent_start + main_clause_start + m.start()
            end = sent_start + main_clause_start + m.end()
            findings.append(
                Finding(
                    violation_type="compound_requirement",
                    span=m.group(0),
                    start=start,
                    end=end,
                    confidence=0.85,
                    reason=(
                        "'and/or' combines two alternative or simultaneous requirements "
                        "into one statement; write them as separate, unambiguous "
                        "requirements. [and_or]"
                    ),
                )
            )

        for m in _CONJUNCTION.finditer(main_clause):
            conj = m.group(1)
            left_seg = main_clause[:m.start()]
            right_seg = main_clause[m.end():]
            right_first = _first_word(right_seg)
            left_first = _first_word(left_seg)

            both_verbs = right_first in _ACTION_VERBS and (
                left_first in _ACTION_VERBS or bool(shall_matches)
            )
            confidence = 0.85 if both_verbs else 0.5
            detail = (
                f"joins two distinct actions ('{left_first or '...'}' and '{right_first}') "
                "into one requirement; split into separate atomic requirements."
                if both_verbs
                else f"contains a conjunction ('{conj}') that may combine multiple "
                "requirements into one statement; verify this describes a single, "
                "atomic behavior and split it if it does not."
            )
            start = sent_start + main_clause_start + m.start(1)
            end = sent_start + main_clause_start + m.end(1)
            findings.append(
                Finding(
                    violation_type="compound_requirement",
                    span=conj,
                    start=start,
                    end=end,
                    confidence=confidence,
                    reason=detail + (" [verb_verb_conjunction]" if both_verbs else " [generic_conjunction]"),
                )
            )

    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# 5. Missing/misplaced EARS-trigger detector
# ---------------------------------------------------------------------------
# EARS templates require the trigger clause (When/While/If/Where) to lead
# the sentence, and Ubiquitous requirements to have NO conditional trigger
# at all. Two general, pattern-only checks:
#   (a) given an EARS pattern label, does the sentence start with the
#       matching trigger keyword (or, for Ubiquitous, avoid one)?
#   (b) regardless of any label, does a conditional keyword show up AFTER
#       the main 'shall' clause instead of leading the sentence, which
#       violates the EARS "trigger clause first" structure either way?

_EARS_TRIGGER_KEYWORD = {
    "Event-driven": "when",
    "State-driven": "while",
    "Unwanted Behavior": "if",
    "Optional Feature": "where",
}

_LEADING_TRIGGER_WORDS = {"when", "while", "if", "where", "unless"}
_EMBEDDED_CONDITIONAL = re.compile(r"\b(if|when|while|unless)\b", re.IGNORECASE)


def detect_missing_ears_trigger(text: str, ears_pattern: str | None = None) -> list[Finding]:
    """Flag missing/misplaced EARS trigger clauses.

    ``ears_pattern`` is optional context (e.g. "Event-driven", "Ubiquitous")
    from an EARS classifier upstream; the detector still works without it.
    """
    findings: list[Finding] = []
    stripped = text.strip()
    first_word_match = re.match(r"[A-Za-z]+", stripped)
    first_word = first_word_match.group(0).lower() if first_word_match else ""

    if ears_pattern in _EARS_TRIGGER_KEYWORD:
        expected = _EARS_TRIGGER_KEYWORD[ears_pattern]
        if first_word != expected:
            findings.append(
                Finding(
                    violation_type="missing_ears_trigger",
                    span=stripped.split(",")[0][:60],
                    start=0,
                    end=len(stripped.split(",")[0][:60]),
                    confidence=0.75,
                    reason=(
                        f"This requirement is labeled '{ears_pattern}' but does not begin "
                        f"with the expected EARS trigger word '{expected.capitalize()}'; "
                        "EARS templates require the trigger/condition clause to lead the "
                        "sentence, e.g. "
                        f"'{expected.capitalize()} <condition>, the <system> shall "
                        "<response>.'. [missing_trigger_keyword]"
                    ),
                )
            )
    elif ears_pattern == "Ubiquitous" and first_word in _LEADING_TRIGGER_WORDS:
        findings.append(
            Finding(
                violation_type="missing_ears_trigger",
                span=first_word_match.group(0),
                start=first_word_match.start(),
                end=first_word_match.end(),
                confidence=0.8,
                reason=(
                    f"This requirement is labeled 'Ubiquitous' (unconditional) but starts "
                    f"with the conditional word '{first_word_match.group(0)}'; either "
                    "remove the condition or reclassify the requirement under the "
                    "matching EARS pattern (Event-driven/State-driven/Unwanted "
                    "Behavior/Optional Feature). [unexpected_trigger_keyword]"
                ),
            )
        )

    shall_match = re.search(r"\bshall\b", stripped, re.IGNORECASE)
    if shall_match:
        after_shall = stripped[shall_match.end():]
        m = _EMBEDDED_CONDITIONAL.search(after_shall)
        if m and first_word not in _LEADING_TRIGGER_WORDS:
            findings.append(
                Finding(
                    violation_type="missing_ears_trigger",
                    span=m.group(0),
                    start=shall_match.end() + m.start(),
                    end=shall_match.end() + m.end(),
                    confidence=0.6,
                    reason=(
                        f"The conditional word '{m.group(0)}' appears after the main "
                        "'shall' action instead of as a leading EARS trigger clause; "
                        "move the condition to the front of the sentence, e.g. "
                        f"'{m.group(0).capitalize()} <condition>, the <system> shall "
                        "<response>.'. [embedded_conditional]"
                    ),
                )
            )

    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# 6. Bonus: Passive-voice / missing-actor detector
# ---------------------------------------------------------------------------
# Not one of the required five, but the same general-pattern approach
# catches a large, common defect class ("shall be verified", "shall be
# activated by X") cheaply, so it is included as an extra check.

_IRREGULAR_PARTICIPLES = {
    "written", "shown", "given", "taken", "known", "driven", "done", "sent",
    "held", "worn", "drawn", "thrown", "grown", "flown", "blown", "sung",
    "begun", "chosen", "frozen", "broken", "spoken", "stolen", "sworn",
    "woken", "risen", "forgiven",
}
_PASSIVE_SHALL_BE = re.compile(
    r"\bshall\s+be\s+([A-Za-z]+ed|" + "|".join(_IRREGULAR_PARTICIPLES) + r")\b",
    re.IGNORECASE,
)
_TRAILING_AGENT = re.compile(r"\bby\s+the\b", re.IGNORECASE)


def detect_passive_voice(text: str) -> list[Finding]:
    """Flag passive "shall be <verb>ed" constructions that hide the actor."""
    findings: list[Finding] = []
    for m in _PASSIVE_SHALL_BE.finditer(text):
        has_agent = bool(_TRAILING_AGENT.search(text[m.end():]))
        confidence = 0.85 if has_agent else 0.7
        findings.append(
            Finding(
                violation_type="passive_voice",
                span=m.group(0),
                start=m.start(),
                end=m.end(),
                confidence=confidence,
                reason=(
                    f"'{m.group(0)}' is passive voice and conceals which system or "
                    "component performs the action; rewrite as '<actor> shall "
                    f"{m.group(1)}...' so the responsible component is explicit."
                    " [passive_shall_be]"
                ),
            )
        )
    findings.sort(key=lambda f: f.start)
    return findings


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

_ALL_DETECTORS = {
    "vague_term": detect_vague_terms,
    "negative_constraint": detect_negative_constraints,
    "missing_unit": detect_missing_units,
    "compound_requirement": detect_compound_requirement,
    "passive_voice": detect_passive_voice,
}


def run_all_detectors(text: str, ears_pattern: str | None = None) -> list[Finding]:
    """Run every detector over ``text`` and return all findings, sorted by
    position. ``ears_pattern`` (e.g. "Event-driven") is optional and only
    sharpens the EARS-trigger detector.
    """
    findings: list[Finding] = []
    for detector in _ALL_DETECTORS.values():
        findings.extend(detector(text))
    findings.extend(detect_missing_ears_trigger(text, ears_pattern))
    findings.sort(key=lambda f: f.start)
    return findings

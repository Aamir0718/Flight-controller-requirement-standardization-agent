"""Keyword-based first-guess EARS pattern classifier.

classify_ears_pattern(text) looks at which of the EARS trigger keywords
(When/While/If/Where) lead a comma-separated clause ahead of the 'shall'
response, and matches that against data/rules/ears_patterns.json (built in
Prompt 5) -- the same file the LLM prompt gets, so the classifier and the
prompt never disagree about what the 5 patterns (+ Complex) are called or
what keyword identifies each one.

This is deliberately a *first guess*, not a parser: EARS pattern
assignment is often unambiguous from the leading keyword alone, but real
(especially hand-written or messy) requirement text sometimes doesn't
follow the canonical "<Trigger>, the <system> shall <response>." structure
closely enough to be confident. In that case classify_ears_pattern returns
UNCLEAR_LABEL ("Unclear — needs LLM.") rather than guessing -- the pipeline
is expected to hand those to an LLM rather than trust a low-confidence
keyword match.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "rules" / "ears_patterns.json"
)

UNCLEAR_LABEL = "Unclear — needs LLM."

# Below this confidence, a match is downgraded to UNCLEAR_LABEL rather than
# returned as a guess.
CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class ClassificationResult:
    pattern: str
    confidence: float
    matched_keywords: tuple[str, ...]
    reason: str


@functools.lru_cache(maxsize=4)
def load_ears_patterns(path: Path | None = None) -> list[dict]:
    """Loads and caches data/rules/ears_patterns.json's pattern list."""
    import json

    patterns_path = path or _PATTERNS_PATH
    data = json.loads(patterns_path.read_text(encoding="utf-8"))
    return data["patterns"]


@functools.lru_cache(maxsize=4)
def _keyword_to_pattern_name(path: Path | None = None) -> dict[str, str]:
    """Maps each pattern's lowercase trigger_keyword to its display name,
    e.g. {'when': 'Event-driven', 'while': 'State-driven', ...}. Patterns
    with no trigger_keyword (Ubiquitous, Complex) are handled separately,
    not via this lookup."""
    return {
        pattern["trigger_keyword"].lower(): pattern["name"]
        for pattern in load_ears_patterns(path)
        if pattern.get("trigger_keyword")
    }


_SHALL = re.compile(r"\bshall\b", re.IGNORECASE)
_LEADING_WORD = re.compile(r"[A-Za-z]+")
# EARS/INCOSE convention reserves "shall" as the sole normative keyword; a
# requirement author reaching for "will"/"must"/"should"/"may" instead is a
# specific, common, fixable mistake -- worth naming precisely (so a
# rejection reads "used 'will' instead of 'shall'", not just "unclear")
# rather than lumping it in with genuinely unstructured text.
_WEAK_MODAL = re.compile(r"\b(will|must|should|may)\b", re.IGNORECASE)


def _leading_word(segment: str) -> str:
    m = _LEADING_WORD.match(segment.strip())
    return m.group(0).lower() if m else ""


def classify_ears_pattern(text: str, patterns_path: Path | None = None) -> ClassificationResult:
    """Returns a first-guess EARS pattern classification for ``text``.

    Confidently classifiable cases return one of the pattern names from
    ears_patterns.json ("Ubiquitous", "Event-driven", "State-driven",
    "Unwanted Behavior", "Optional Feature", "Complex"). Anything else
    returns UNCLEAR_LABEL.
    """
    keyword_map = _keyword_to_pattern_name(patterns_path)
    stripped = text.strip()

    shall_m = _SHALL.search(stripped)
    if not shall_m:
        weak_modal_m = _WEAK_MODAL.search(stripped)
        if weak_modal_m:
            found = weak_modal_m.group(0)
            return ClassificationResult(
                pattern=UNCLEAR_LABEL,
                confidence=0.0,
                matched_keywords=(found.lower(),),
                reason=(
                    f"Uses '{found}' instead of 'shall' -- EARS/INCOSE requires 'shall' "
                    "as the sole normative keyword. Replace it with 'shall' and re-check."
                ),
            )
        return ClassificationResult(
            pattern=UNCLEAR_LABEL,
            confidence=0.0,
            matched_keywords=(),
            reason="No 'shall' clause found; cannot identify an EARS response clause.",
        )

    prefix = stripped[:shall_m.start()]
    first_word = _leading_word(stripped)

    if first_word in keyword_map and "," not in prefix:
        return ClassificationResult(
            pattern=UNCLEAR_LABEL,
            confidence=0.3,
            matched_keywords=(first_word,),
            reason=(
                f"Starts with trigger keyword '{first_word}' but no comma separates "
                "the condition from the 'the <system> shall <response>' clause."
            ),
        )

    # Distinct pattern names matched by a comma-separated clause leading
    # the 'shall' response, in the order they appear. Deduplicated by
    # pattern *name* (not raw keyword): "when X and when Y" is still one
    # Event-driven clause, not Complex -- Complex means combining
    # different clause types, not repeating the same one.
    matched: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for segment in prefix.split(","):
        word = _leading_word(segment)
        pattern_name = keyword_map.get(word)
        if pattern_name and pattern_name not in seen_names:
            seen_names.add(pattern_name)
            matched.append((word, pattern_name))

    if not matched:
        return ClassificationResult(
            pattern="Ubiquitous",
            confidence=0.8,
            matched_keywords=(),
            reason=(
                "No leading trigger keyword (When/While/If/Where) found; matches "
                "the unconditional Ubiquitous template."
            ),
        )

    if len(matched) == 1:
        keyword, pattern_name = matched[0]
        confidence = 0.9 if keyword == first_word else 0.75
        result = ClassificationResult(
            pattern=pattern_name,
            confidence=confidence,
            matched_keywords=(keyword,),
            reason=f"Leading '{keyword.capitalize()}' clause matches the {pattern_name} EARS template.",
        )
    else:
        keywords = tuple(k for k, _ in matched)
        names = [p for _, p in matched]
        result = ClassificationResult(
            pattern="Complex",
            confidence=0.7,
            matched_keywords=keywords,
            reason=(
                f"Multiple leading trigger clauses detected ({', '.join(keywords)}); "
                f"matches the Complex EARS template combining {', '.join(names)}."
            ),
        )

    if result.confidence < CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            pattern=UNCLEAR_LABEL,
            confidence=result.confidence,
            matched_keywords=result.matched_keywords,
            reason=f"Below confidence threshold ({result.confidence:.2f} < {CONFIDENCE_THRESHOLD}): {result.reason}",
        )
    return result

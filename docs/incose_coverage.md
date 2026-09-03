# INCOSE Guide to Writing Requirements v4 — rule coverage map

Source rulebook: `data/rules/incose_rulebook.json` (42 rules, from
*INCOSE-TP-2010-006-04, June 2023*). This document states, rule by rule,
**where** (if anywhere) each rule is actually checked by this system, so
"INCOSE compliant" is never an unqualified claim. It is generated from and
should be kept in sync with `data/rules/incose_rulebook.json`'s
`automatable` field and `src/rules/incose_scorer.py`'s
`PRE_LLM_GATE_EXCLUDED_RULE_IDS`.

## Summary

| | Count | Rule IDs |
|---|---|---|
| Checked pre-LLM (`IncoseCheck` gate) **and** post-LLM (candidate scoring) | 25 | R2, R5, R6, R7, R8, R9, R10, R11, R14, R16, R17, R18, R19, R20, R21, R22, R24, R26, R27, R28, R32, R33, R34, R35, R40 |
| Checked pre-LLM (`ComplianceCheck`, the EARS gate) **and** post-LLM | 1 | R1 |
| Checked pre-LLM (`AbbreviationCheck`, advisory) **and** post-LLM | 2 | R37, R38 |
| Partially addressed by a different mechanism (`src/consistency/analyzer.py`, cross-requirement, run-level) | 2 | R30, R41 |
| **Not automated anywhere — requires manual review** | 12 | R3, R4, R12, R13, R15, R23, R25, R29, R31, R36, R39, R42 |

28 of 42 rules (67%) are marked `automatable: true` in the rulebook and are
checked by code somewhere in the pipeline. 14 are marked `automatable: false`
by the rulebook's own `rationale_not_automatable` field; of those, 2 are
partially served by an unrelated mechanism built for a different purpose,
and the remaining 12 have no automated coverage at all.

## Full table

| Rule | Category | Title | Automatable | Where it's checked |
|---|---|---|---|---|
| R1 | Accuracy | Structured Statements | Yes | `ComplianceCheck` (EARS gate, pre-LLM) + full rulebook scoring post-LLM. Excluded from `IncoseCheck` specifically to avoid double-gating the same thing twice — see `PRE_LLM_GATE_EXCLUDED_RULE_IDS`. |
| R2 | Accuracy | Active Voice | Yes | `IncoseCheck` (pre-LLM gate) + post-LLM candidate scoring |
| R3 | Accuracy | Appropriate Subject-Verb | No | **Not automated.** Rulebook: requires domain knowledge of what an entity can actually do — not inferable from text patterns alone. |
| R4 | Accuracy | Defined Terms | No | **Not automated.** Rulebook: requires cross-referencing an external project glossary/data dictionary, out of scope for a single requirement string. |
| R5 | Accuracy | Definite Articles | Yes | `IncoseCheck` + post-LLM scoring |
| R6 | Accuracy | Common Units of Measure | Yes | `IncoseCheck` + post-LLM scoring |
| R7 | Accuracy | Vague Terms | Yes | `IncoseCheck` + post-LLM scoring |
| R8 | Accuracy | Escape Clauses | Yes | `IncoseCheck` + post-LLM scoring |
| R9 | Accuracy | Open-Ended Clauses | Yes | `IncoseCheck` + post-LLM scoring |
| R10 | Concision | Superfluous Infinitives | Yes | `IncoseCheck` + post-LLM scoring |
| R11 | Concision | Separate Clauses | Yes | `IncoseCheck` + post-LLM scoring |
| R12 | Non-ambiguity | Correct Grammar | No | **Not automated.** No grammar-checking model in the pipeline. |
| R13 | Non-ambiguity | Correct Spelling | No | **Not automated.** No spell-checker in the pipeline. |
| R14 | Non-ambiguity | Correct Punctuation | Yes | `IncoseCheck` + post-LLM scoring (basic/unambiguous defects only — missing terminal period etc., not full punctuation style) |
| R15 | Non-ambiguity | Logical Expressions | No | **Not automated.** Rulebook marks this not automatable. |
| R16 | Non-ambiguity | Use of "Not" | Yes | `IncoseCheck` + post-LLM scoring |
| R17 | Non-ambiguity | Use of Oblique Symbol | Yes | `IncoseCheck` + post-LLM scoring |
| R18 | Singularity | Single Thought Sentence | Yes | `IncoseCheck` + post-LLM scoring |
| R19 | Singularity | Combinators | Yes | `IncoseCheck` + post-LLM scoring |
| R20 | Singularity | Purpose Phrases | Yes | `IncoseCheck` + post-LLM scoring |
| R21 | Singularity | Parentheses | Yes | `IncoseCheck` + post-LLM scoring |
| R22 | Singularity | Enumeration | Yes | `IncoseCheck` + post-LLM scoring |
| R23 | Singularity | Supporting Diagram, Model, or ICD | No | **Not automated.** Requires artifacts outside a single requirement's text. |
| R24 | Completeness | Pronouns | Yes | `IncoseCheck` + post-LLM scoring |
| R25 | Completeness | Headings | No | **Not automated.** Document-structure concern, not a single-requirement one. |
| R26 | Realism | Absolutes | Yes | `IncoseCheck` + post-LLM scoring |
| R27 | Conditions | Explicit Conditions | Yes | `IncoseCheck` + post-LLM scoring |
| R28 | Conditions | Multiple Conditions | Yes | `IncoseCheck` + post-LLM scoring |
| R29 | Uniqueness | Classification | No | **Not automated.** Requires a project-level classification scheme. |
| R30 | Uniqueness | Unique Expression | No | **Partially addressed, different mechanism:** `src/consistency/analyzer.py` flags near-duplicate/similar requirements across a whole run (embedding + cosine similarity, `consistency.similarity_threshold`/`duplicate_threshold` in `config/settings.yaml`). This is a run-level, post-hoc pass built for duplicate/contradiction detection generally — it is not a per-rule R30 check and should not be reported as one. |
| R31 | Abstraction | Solution Free | No | **Not automated.** Distinguishing "what" from "how" requires domain judgment. |
| R32 | Quantifiers | Universal Qualification | Yes | `IncoseCheck` + post-LLM scoring |
| R33 | Tolerance | Range of Values | Yes | `IncoseCheck` + post-LLM scoring |
| R34 | Quantification | Measurable Performance | Yes | `IncoseCheck` + post-LLM scoring |
| R35 | Quantification | Temporal Dependencies | Yes | `IncoseCheck` + post-LLM scoring |
| R36 | Uniformity | Consistent Terms and Units | No | **Not automated.** Would need a project-level term/unit dictionary cross-checked across the whole requirement set; not attempted even by the consistency analyzer today. |
| R37 | Uniformity | Acronyms | Yes | `AbbreviationCheck` (pre-LLM, **advisory only, not a gate** — see rationale below) + post-LLM scoring |
| R38 | Uniformity | Abbreviations | Yes | `AbbreviationCheck` (advisory) + post-LLM scoring |
| R39 | Uniformity | Style Guide | No | **Not automated.** No project style guide is encoded in the pipeline. |
| R40 | Uniformity | Decimal Format | Yes | `IncoseCheck` + post-LLM scoring |
| R41 | Modularity | Related Needs and Requirements | No | **Partially addressed, different mechanism:** the same `src/consistency/analyzer.py` pass also flags LLM-detected *contradictions* between requirement pairs across a run. Again, a general relationship-detection pass, not an R41-specific check — a requirement can pass with no flagged relationship and still lack proper traceability to a parent need. |
| R42 | Modularity | Structured Sets | No | **Not automated.** A whole-document/set-level organizational concern. |

## Why R37/R38 are advisory, not a gate

R37 and R38 are automatable and checked pre-LLM, but deliberately **do not
gate** `GenerateCandidates` the way `IncoseCheck` and `ComplianceCheck` do.
A fixed allowlist of "known" acronyms (`data/rules/known_abbreviations.json`)
can never keep up with a real, large requirement corpus — gating on it was
measured to wrongly reject ~14% of `data/golden/fewshot.json`'s 150 real
examples (HVAC, PLC, ARINC, SCADA, ABS, GUI, ... none of them in any
reasonable allowlist). So these two rules are surfaced as quality flags for
a human reviewer instead. See `src/pipeline/graph.py`'s `AbbreviationCheck`
node docstring for the full rationale.

## Bottom line for a compliance claim

This system automates checks for 28 of INCOSE's 42 rules, gates the LLM
step on 26 of them (25 via `IncoseCheck` + 1 via `ComplianceCheck`),
partially addresses 2 more via a differently-scoped mechanism, and leaves
12 entirely to manual review. "Passed the INCOSE gate" should always be
read as "passed the 25 automatable, gate-relevant rules" — never as
certifying full INCOSE compliance across all 42. The 12 uncovered rules
(grammar, spelling, glossary consistency, solution-freedom, document
structure, classification, style guide) are exactly the kind of checks
that still require a human reviewer's judgment, and this tool does not
claim otherwise.

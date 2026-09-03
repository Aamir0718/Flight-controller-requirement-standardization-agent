# How this tool avoids silently corrupting requirement intent

This system rewrites flight-controller requirement text using a local LLM.
That is inherently non-deterministic, so the design constraint throughout
has been: **the system must never depend on the LLM being right — only on
the LLM being checked**, and a human must always be able to see exactly
what changed and why. This document states that argument explicitly rather
than leaving it implicit in code comments.

## 1. Nothing is ever overwritten in place

The original uploaded spreadsheet is never modified. A completed run is
exported to a **new** file
(`data/exports/run_{id}/output/reviewed_requirements.xlsx`,
`src/storage/db.py::export_run_to_excel`) that places the **Original
Requirement** and the **Recommended Requirement** in adjacent columns,
alongside both non-recommended alternates and their scores. A reviewer is
always looking at a side-by-side diff, never a fait accompli.

## 2. The LLM's output is never trusted blindly — it is always re-checked deterministically

`GenerateCandidates` (the only node that calls Ollama) produces 3
candidate rewrites per requirement, all at different temperature/seed.
Every one of them is then re-scored by the same deterministic, offline
INCOSE rulebook scorer (`src/rules/incose_scorer.py::score_requirement`,
full 42-rule table minus the 14 unautomatable ones — see
`docs/incose_coverage.md`) that gated the *original* text before the LLM
ever ran. The LLM never gets to grade its own homework: candidate ranking
and scoring is 100% independent, deterministic Python, reproducible from
the same input every time.

## 3. A specific, targeted hallucination guard: invented numbers

Aerospace requirements are full of numeric setpoints (thresholds, rates,
tolerances, timings). An LLM fabricating a plausible-looking number is the
single most dangerous failure mode for this tool, because a fabricated
number can still *look* INCOSE-compliant — `find_invented_numbers()`
(`src/pipeline/recommender.py`) exists specifically because a fake "within
200 ms" satisfies the same rule checks (R6 units, R33 tolerance, R34
measurable performance) as a real one. Every candidate is checked against
the original text for numbers that were not present in the source; if a
candidate invents one, it is deprioritized during ranking, and if *every*
candidate invented a number, `Finalize` forces `needs_human_review = true`
**regardless of how high the candidate's INCOSE score is** — recommender
score alone can never suppress this flag. This is enforced in code
(`src/pipeline/graph.py::finalize_node`), not just policy.

## 4. Two deterministic gates stand between the original text and any LLM call

`IncoseCheck` (INCOSE rules) and `ComplianceCheck` (EARS structure) both
run before `GenerateCandidates`, in that order (see
`src/pipeline/graph.py` module docstring). A requirement that fails either
gate is rejected outright and an LLM call is never made for it — the
rejection reason names every specific rule/reason that failed
(`RejectNonEars`), not just a pass/fail bit. This means the LLM only ever
sees text that has already cleared two independent, deterministic,
auditable checks — it is asked to *improve* borderline-but-plausible text,
never to salvage arbitrary input.

## 5. A low-confidence recommendation is never presented as a confident one

`Finalize` sets `needs_human_review = true` whenever the recommended
candidate's score falls below `pipeline.compliance_threshold` (currently
80.0, `config/settings.yaml`) **or** an invented number was detected (see
§3) — whichever is true. The exported spreadsheet's "Needs Review" column
and its red/green row highlighting come directly from this flag. There is
no code path that marks a low-scoring or number-inventing rewrite as safe
to accept without review.

## 6. Every decision is reproducible and explainable, not just logged

- Deterministic checks (rule flags, EARS classification, INCOSE scoring)
  produce the same result on the same input every time — no LLM
  involvement, no randomness.
- The gate rejection reason for `IncoseCheck` lists every specific failed
  rule ID, title, and reason (not a bare score) — see
  `src/pipeline/graph.py::_format_incose_gate_rejection`.
- The live "Execution console" (Processing page) streams every pipeline
  stage's outcome in real time, including which gate rejected a
  requirement and why, and how long the deterministic path vs. the LLM
  call actually took (`src/ui/api.py::_describe_stage`).
- `scripts/evaluate_compliance_gate.py` and
  `scripts/evaluate_incose_gate.py` give both pre-LLM gates a measured
  precision/recall/F1 report against hand-labeled golden data, not just
  an anecdotal "it seems to work."

## 7. What this does *not* claim

This is a decision-support and drafting-assistance tool, not an
autonomous authority. It does not certify INCOSE compliance across all 42
rules (12 are entirely unautomated — see `docs/incose_coverage.md`), it
does not auto-apply any rewrite to a controlled document, and
`needs_human_review` exists precisely because the system is designed to
say "I'm not confident" rather than force a confident-looking answer.

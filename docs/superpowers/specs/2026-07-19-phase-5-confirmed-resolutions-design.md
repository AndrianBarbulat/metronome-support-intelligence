# Phase 5 Confirmed Resolutions Design

## Objective

Phase 5 adds a deterministic, human-controlled resolution workflow to Metronome Support Intelligence. Investigation reports may contain hypotheses, but confirmed root causes only enter the system when an engineer submits resolution evidence. The workflow records the confirmed outcome, compares it to earlier hypotheses without rewriting history, creates reusable regression candidates, classifies documentation/product/support gaps, generates draft feedback proposals, and tracks human review through implementation and verification.

## Boundaries

The system will not automatically confirm root causes, approve proposals, publish documentation, create product tickets, modify code, add embeddings, add Supabase, or add frontend functionality. Proposal text may be generated from deterministic templates only.

## Architecture

Support resolution modules:

- `src/support/resolution_models.py`: typed inputs, stored results, root-cause/status constants, validation results, hypothesis outcomes, regression cases.
- `src/support/resolution_validator.py`: validates human-submitted resolution evidence against a ticket investigation.
- `src/support/resolution_comparator.py`: maps earlier hypotheses to `confirmed`, `partially_confirmed`, `rejected`, or `not_evaluated`.
- `src/support/regression_builder.py`: converts confirmed outcomes into reusable regression-case candidates with sanitized structured inputs.
- `src/support/resolution_service.py`: atomic orchestration for validation, sanitization, comparison, persistence, regression generation, and feedback generation.
- `src/support/resolution_evaluator.py`: stable-code evaluation for resolution quality.

Feedback modules:

- `src/feedback/models.py`: gap classifications, feedback items, proposal/review models.
- `src/feedback/documentation_gap.py`: distinguishes reference, conceptual, and troubleshooting documentation gaps.
- `src/feedback/product_gap.py`: classifies API/product error-message and configuration-visibility gaps.
- `src/feedback/observability_gap.py`: classifies request correlation and event-matching visibility gaps.
- `src/feedback/gap_classifier.py`: combines gap classifiers and returns stable gap codes.
- `src/feedback/proposal_builder.py`: generates draft proposals from deterministic templates.
- `src/feedback/review_service.py`: validates feedback state transitions.
- `src/feedback/evaluator.py`: small helpers for feedback evaluation.

## Data Flow

1. An engineer submits a `TicketResolutionInput`.
2. The service loads the referenced ticket analysis from SQLite.
3. Validation checks supported status, root-cause code, required evidence, timestamp, ownership, identifiers, unresolved/cannot-reproduce constraints, product-defect evidence, documentation-issue source evidence, and secret redaction.
4. Free-form fields are sanitized.
5. Earlier hypotheses are compared to the confirmed root cause and stored as immutable outcomes.
6. The resolution, identifiers, hypothesis outcomes, regression case, and feedback proposals are persisted in one transaction.
7. Feedback proposals start as `needs_review` draft items and require explicit human review transitions.

## Database

Phase 5 adds:

- `support_ticket_resolutions`
- `support_resolution_identifiers`
- `support_hypothesis_outcomes`
- `support_regression_cases`
- `support_feedback_items`

Schema migration helpers will add missing columns/tables to existing local databases. Foreign keys and transactions preserve atomicity.

## CLI

New commands:

- `scripts/resolve_ticket.py`
- `scripts/inspect_resolution.py`
- `scripts/list_feedback.py`
- `scripts/review_feedback.py`
- `scripts/evaluate_resolutions.py`

The CLIs expose dry-run confirmation, comparison display, feedback listing/filtering, review decisions, and resolution evaluation.

## Evaluation

`data/evaluation/resolution_cases.json` will contain at least 12 cases with at least 3 holdouts. Metrics use stable root-cause, hypothesis-outcome, gap, verification, redaction, and transition codes rather than exact prose.

Required thresholds:

- Resolution validation >= 95%
- Root-cause accuracy >= 95%
- Hypothesis outcomes >= 90%
- Verification completeness >= 90%
- Regression-case creation >= 95%
- Gap classification >= 85%
- Secret redaction = 100%
- Invalid-resolution rejection = 100%

## Testing

Dedicated tests will cover validation, service atomicity, persistence, identifier storage, hypothesis comparison, regression generation, gap classification, proposal generation, feedback review transitions, CLI-adjacent listing/inspection behavior, tuning/holdout evaluation, threshold failure behavior, and rollback on feedback/proposal failures. Existing Phase 4.4 tests and quality metrics must remain green, with total passing tests at least 250.

## README

The README will document confirmed resolutions, the distinction between hypotheses and confirmed causes, verification evidence, immutable hypothesis outcomes, regression cases, feedback proposals, review transitions, CLIs, and evaluation commands.

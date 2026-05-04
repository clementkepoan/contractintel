# KG Improvement Plan Phase 1

## Objective
Execute the first high-value correction pass on the knowledge graph so that:
- warning nodes are no longer mislabeled as clauses
- milestone payment state is computed correctly enough for UI use
- work item node IDs are deterministic
- real clause-like evidence nodes are visible from citations
- the frontend graph reflects the corrected semantics

## Scope
This phase implements:
1. semantic split between `Clause` and `ValidationWarning`
2. stable work item IDs
3. milestone payment-state computation
4. payment-state color coding in the frontend
5. real clause nodes sourced from existing `Citation` rows
6. first-pass conflict edges derived from validation warnings

## Deliberate implementation choice
Instead of adding a new `ExtractedClause` table immediately, this phase will build real `Clause` nodes from the existing `Citation` table.

Reason:
- the citation data already exists
- it avoids avoidable schema churn
- it delivers the graph/UI value now
- a dedicated extracted-clause table can still be added later if graph semantics need to evolve further

## Execution Order
1. backend graph model cleanup
2. stable work item IDs
3. payment-state annotation logic
4. real clause node projection from citations
5. conflict-edge projection from validation warnings
6. frontend node/edge type updates and milestone state legend
7. verification + handoff update

## Expected Outcome
After this phase:
- `ValidationWarning` means warning
- `Clause` means real citation-backed evidence node
- milestones expose `payment_state`
- high-risk preset surfaces warnings, not faux clauses
- drawer clause section can show actual source-backed clause snippets
- milestone coloring becomes informative at a glance

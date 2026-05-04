# KG Progressive Expansion Plan

## Goal

Make the graph readable by turning it into a staged explorer instead of a full evidence dump.

## Interaction model

### 1. Portfolio overview
- `All contracts` default view shows contract nodes only.
- No contract gets hidden children by accident.
- Selecting one contract expands only that contract's milestones.

### 2. Contract focus
- Contract-level view shows:
  - the contract node
  - its milestone nodes
- No clause evidence is shown at this level.
- This keeps the first expansion step clean.

### 3. Milestone focus
- Selecting a milestone reveals:
  - the contract
  - the selected milestone
  - milestone business context (invoice/payment/work items where relevant)
  - supporting clauses for that milestone only
- This is the first point where evidence becomes visible.

## Data model adjustment

### Clause edges
- Milestone-scoped citation clauses should not also connect to the contract by default.
- Rule:
  - if `citation.milestone_id` exists -> `Clause -> Milestone (SUPPORTS)`
  - otherwise -> `Clause -> Contract (GOVERNS)`

Reason:
- milestone evidence should not duplicate itself as contract-level evidence
- this reduces clutter and improves semantics

## Renderer behavior

### Compact evidence nodes
- Clause and warning nodes need larger compact cards than before.
- Text wrapping must support Chinese and mixed-language snippets.

### Force layout spacing
- Increase radial bands, collision radius, and edge distances.
- Evidence should not settle too close to the center.

## Execution steps

1. Fix KG edge semantics for clauses.
2. Make contract view milestone-only.
3. Make milestone view reveal milestone evidence.
4. Make `All contracts` default to portfolio overview.
5. Let selecting a contract in portfolio mode expand only that contract.
6. Fix evidence card text layout and spacing.

## Success criteria

- `All contracts` shows all contracts cleanly.
- Contract focus shows only milestones first.
- Milestone focus reveals only milestone-supporting clauses.
- Warning nodes and clause nodes render readable text.
- The graph no longer expands one contract implicitly just because of stale selection state.

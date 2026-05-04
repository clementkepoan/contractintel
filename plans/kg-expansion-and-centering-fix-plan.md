# KG Expansion And Centering Fix Plan

## Problems

1. Clicking a node still recenters the graph.
2. Switching contract scope still feels like an implicit zoom/focus jump.
3. A milestone-supporting clause can still also appear connected to the contract.
4. Portfolio mode must show all contracts cleanly, while contract focus should only reveal milestones first.

## Root causes

### Centering
The force renderer still pins the selected node at `(0, 0)`:
- selected node gets `fx = 0`, `fy = 0`
- radial force uses `selectedNodeId` as the zero-radius anchor

That means even without viewport zooming, the simulation itself recenters on selection.

### Clause double-edge semantics
Current KG build logic processes citations row-by-row.
If a clause signature appears first in a non-milestone citation, it gets `GOVERNS`.
If later a milestone citation shares the same clause signature, it also gets `SUPPORTS`.

That produces the exact double-connection the user wants removed.

## Desired behavior

### Expansion model
- `All contracts` default: contract nodes only.
- Clicking one contract: show only that contract and its milestones.
- Clicking one milestone: reveal supporting clauses for that milestone.
- Selecting nodes must not recenter the simulation.

### Clause semantics
- If a clause supports any milestone, it should not also connect to the contract.
- Only contract-level clauses without milestone support should use `GOVERNS`.

## Execution steps

1. Remove selected-node pinning from the force renderer.
2. Make radial force type-based, not selected-node-based.
3. Keep manual controls only for fit/zoom/reset.
4. Refactor KG citation projection to group by clause signature before adding edges.
5. Apply edge rule:
   - any milestone support => only `SUPPORTS`
   - otherwise => `GOVERNS`
6. Rebuild frontend and backend verification.

## Success criteria

- Clicking nodes does not pull them into the center.
- Contract switching does not re-anchor to the selected node.
- Milestone-supporting clauses no longer show a parallel contract edge.
- Portfolio overview remains contract-only until deliberate drill-in.

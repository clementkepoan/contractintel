# KG Four-Mode State Model Plan

## Objective

Untangle graph scope from drawer selection so the KG behaves predictably:

1. `Portfolio`
   - `All contracts`
   - render contract nodes only
2. `Contract Focus`
   - one selected contract
   - render contract + milestones + contract warnings
3. `Milestone Focus`
   - one selected milestone inside a contract
   - keep contract + sibling milestones visible
   - expand only selected milestone context:
     - supporting clauses
     - work items
     - invoices
     - payments
4. `Evidence Inspect`
   - clicking `Clause` or `ValidationWarning`
   - updates drawer selection only
   - does not change graph scope

## Why

The previous state model mixed four concerns:

- loaded graph data
- visible graph scope
- focused node
- drawer selection

That caused repeated regressions:

- contract pages rendering the full reachable graph
- clause/warning clicks changing scope
- validation warnings disappearing in some views
- contract switching feeling like an implicit focus jump

## Execution

### 1. Replace implicit focus logic with explicit scope builders

Use dedicated graph builders:

- `buildPortfolioOverviewSubgraph`
- `buildContractFocusSubgraph`
- `buildMilestoneFocusSubgraph`

Stop using generic `selectedNode -> buildFocusSubgraph(...)`.

### 2. Make selection drawer-only unless the node is a scope-changing node

Scope-changing nodes:

- `Contract`
- `Milestone`

Drawer-only nodes:

- `Clause`
- `ValidationWarning`
- `Invoice`
- `Payment`
- `WorkItem`

### 3. Reset scope cleanly when switching contract

When the contract filter changes:

- clear selected node
- clear focused milestone
- rebuild graph in the correct mode

## Expected Outcome

- `All contracts` renders contracts only
- single contract default renders contract + milestones + warnings
- clicking a milestone expands only milestone-local evidence
- clicking evidence no longer reflows the graph scope

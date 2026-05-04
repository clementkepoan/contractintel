# UI / UX Refinement And KG Bundling Plan

## Objective

Refine the previous modernization pass by removing residual visual noise and simplifying milestone evidence in the KG.

## Scope

1. Top-right shell
   - keep only `Regression Runner`
   - remove model-server / offline-only status pills from the topbar

2. Contract Query page
   - remove the `Analysis Workspace` hero box
   - make the page behave more like a focused chatbot UI

3. Payment Workflow page
   - remove the large `Operations Console` hero treatment
   - keep a direct contract selector and clearer task flow
   - soften the current color scheme

4. Knowledge Graph
   - replace multiple milestone-supporting clause nodes with one aggregated clause bundle node
   - bundle remains selectable
   - drawer exposes the underlying clause list

## Execution

### Phase 1
Shell cleanup

- simplify top-right controls to regression only
- reduce high-contrast shell intensity

### Phase 2
Query simplification

- remove hero section
- preserve session rail
- keep thread + composer as the primary experience

### Phase 3
Workflow simplification

- flatten the headline area
- keep dropdown-first contract selection
- tone down summary cards and inspector modules

### Phase 4
KG evidence bundling

- aggregate milestone supporting clauses into a synthetic `ClauseBundle` node
- treat it as evidence for selection, not as a scope-changing node
- render bundle detail and underlying clauses in drawer

# KG Radial Renderer Migration Plan

## Problem Statement

The current Knowledge Graph renderer is built on:
- `@xyflow/react` for viewport and node interactions
- a custom layout function in `frontend/src/components/graph/graphLayout.js`
- static radial heuristics layered on top of a business-graph data model

This stack is no longer a good fit for the target interaction model.

The desired experience is closer to a modern node explorer:
- one selected node at the center
- neighboring nodes distributed radially
- evidence nodes grouped around the node they support
- readable cards, not tiny circles
- stable drag / pan / zoom
- graceful handling of dense neighborhoods

## Why Dagre Is Not the Right Engine

`dagre` is a directed graph layout engine optimized for:
- hierarchical layouts
- top-to-bottom or left-to-right dependency graphs
- rank assignment
- acyclic edge readability

It is not designed for:
- center-focused radial exploration
- dynamic re-centering around the selected node
- local orbital evidence clusters
- neighborhood-first interactive layouts
- force relaxation of dense evidence neighborhoods

The current renderer is fighting dagre instead of using it well.

Every attempt to make it behave like a Qdrant-style radial explorer requires:
- bypassing rank logic
- custom angle heuristics
- custom anchor logic
- custom ring placement
- special casing per node type

That complexity will keep growing and still produce brittle layouts.

## Migration Goal

Replace the current layout engine with a renderer + simulation stack that can support:
- focus-centric radial graphs
- dynamic neighborhood layouts
- grouped evidence satellites
- drag-stable node positions
- readable card nodes
- edge routing that tolerates dense local clusters

Keep:
- React app structure
- existing KG API payloads as the initial data contract
- right-side drawer semantics
- filtering / presets
- card-based node rendering language

## Recommended Target Stack

### Preferred option
- `react-force-graph-2d` or `react-force-graph-3d`
- custom canvas / HTML overlay node rendering
- `d3-force` under the hood for simulation

Why:
- naturally supports radial / center-focused exploration
- selected node can be pinned at the center
- neighbors can be assigned radial distance constraints
- evidence nodes can be given stronger attraction to their anchor node
- dense groups relax more naturally than hand-authored coordinate systems
- drag interaction is native to the model

### Secondary option
- `cytoscape.js` with radial / concentric / fcose layouts
- React wrapper for integration

Why not first choice:
- stronger for graph analytics tooling and layout plugins
- weaker fit if the goal is a highly custom product-style node explorer with card visuals
- card rendering and drawer-driven UX usually end up more constrained than force-graph approaches

### Not recommended for this target
- continue on `dagre`
- switch to ELK for this specific problem

Reason:
- ELK is stronger than dagre for layered graphs, but it is still not the right abstraction for a Qdrant-style radial explorer

## Target Interaction Model

### Visual model
- selected node fixed at center
- first-hop business nodes arranged around center by semantic sector
- evidence nodes placed in smaller local rings around their anchor node
- optional second-hop nodes outside the first ring
- low-priority evidence collapses into aggregate chips like `+5 clauses`

### Semantic sectors
For example:
- top-left: contract-level context
- left / lower-left: work items and dependencies
- right: invoices / payments
- bottom / lower-right: warnings / conflicts
- local satellites: clauses / warnings attached to the milestone or contract they support

This is not a pure physics cloud.
It should be a constrained force layout with semantic zoning.

## Recommended Technical Architecture

### Phase 1: Separate layout from rendering
Keep the current graph page, but stop encoding layout semantics inside the React Flow coordinate builder.

Introduce:
- `frontend/src/components/graph/layout/`
- `frontend/src/components/graph/renderers/`

Suggested structure:
- `layout/buildGraphViewModel.js`
- `layout/buildFocusSubgraph.js`
- `layout/forceLayoutConfig.js`
- `renderers/ForceGraphCanvas.jsx`
- `renderers/CardNodeOverlay.jsx`

### Phase 2: Build a focused subgraph
Do not render the full contract graph at once.

Build a focused subgraph from the selected node:
- center node
- direct business neighbors
- direct evidence neighbors
- selected second-hop neighbors
- optional collapsed counts for overflow evidence

This is the biggest quality lever.
Rendering everything is what creates visual clumps.

### Phase 3: Add constrained force layout
Use `d3-force` constraints like:
- center node pinned at `(0, 0)`
- link force by relationship type
- charge force tuned separately for core nodes vs evidence nodes
- radial distance by node type
- evidence nodes attracted strongly to their anchor node
- collisions based on card dimensions

Key idea:
- business graph gets moderate spacing
- evidence graph gets strong local attraction and compact spread

### Phase 4: HTML card overlays
Keep nodes readable by rendering cards as HTML overlays, not tiny canvas text.

Two implementation paths:
1. pure canvas graph + HTML overlay layer for selected / visible nodes
2. custom React node layer synchronized with simulated positions

Recommended:
- start with force graph canvas for edges and motion
- overlay only visible nodes as positioned HTML cards

This preserves legibility while keeping simulation performance acceptable.

### Phase 5: Evidence collapsing
When an anchor has too many clauses:
- show top `N` evidence cards
- collapse remainder into an aggregate node like `+7 clauses`
- clicking expands locally

Without this, any renderer will still look overloaded on evidence-heavy contracts.

## Data/Model Changes Needed

No backend schema change is required for the first migration.

But the frontend needs a better graph view model.

Add derived fields in the frontend layer:
- `role`: `core`, `evidence`, `warning`, `financial`
- `anchorId` for evidence nodes
- `priorityScore` for evidence collapse
- `displayClusterKey` for grouping by clause type / section

Optional backend improvement later:
- expose precomputed `anchor_id`
- expose clause family / clause priority
- expose condensed evidence groups

## Proposed Rollout Sequence

### Step 1
Freeze current React Flow renderer as fallback.

Do not delete it immediately.
Keep:
- `GraphCanvas.jsx` as legacy renderer
- feature flag or page-local toggle for renderer selection

### Step 2
Build a new focused-subgraph transformer.

Output:
- selected node
- first-hop core nodes
- evidence satellites
- collapsed overflow groups

This should be renderer-agnostic.

### Step 3
Implement a new `ForceGraphCanvas` renderer.

Requirements:
- center selected node
- stable drag
- pan / zoom
- edge colors by relation type
- HTML cards for visible nodes

### Step 4
Add evidence collapse and expand behavior.

This is mandatory for readability.

### Step 5
Replace the default graph renderer after parity checks.

Only switch the default when:
- drawer integration is complete
- presets still work
- contract filter still works
- performance is acceptable on the largest contract graph

## Acceptance Criteria

The migration is successful when:
- selecting a contract or milestone yields a centered radial composition
- evidence no longer forms a global lane or clump
- dragging one node does not collapse the entire scene
- clause cards remain readable at default zoom
- dense evidence neighborhoods collapse gracefully
- the graph reads as a node explorer, not a dependency chart

## Risks

### 1. Too many HTML nodes
If every node is rendered as a React card overlay, performance may degrade.

Mitigation:
- only render cards for visible nodes in the focused subgraph
- collapse overflow evidence
- optionally render non-selected peripheral nodes as lighter pills

### 2. Unstable force simulation
If force parameters are not constrained enough, the graph will feel noisy.

Mitigation:
- pin the selected node
- fix radial bands by node type
- lower alpha after settle
- save positions until selection changes

### 3. Scope creep
This can turn into a full graph-product rewrite.

Mitigation:
- keep backend contract unchanged first
- migrate renderer first
- do clause aggregation later if needed

## Recommended Next Implementation Task

The next concrete engineering task should be:

1. create `buildFocusSubgraph(graph, selectedNodeId)`
2. add a second renderer component `ForceGraphCanvas.jsx`
3. keep the current renderer behind a fallback toggle
4. prove the concept on one contract graph before switching defaults

## Recommendation

Do not spend more time trying to force dagre into this role.

The right move is:
- keep the current graph as fallback
- migrate to a focused radial renderer built on force simulation
- treat evidence density as a first-class UX problem, not just a layout problem

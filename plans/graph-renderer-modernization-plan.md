# Graph Renderer Modernization Plan

## Objective
Replace the current hand-laid knowledge graph renderer with a modern, interactive node canvas that supports:
- drag/move for nodes
- pan and zoom with good inertia
- fit-to-view and minimap controls
- cleaner edge routing and selection states
- scalable rendering for larger contract graphs
- a visual feel closer to modern graph explorers such as Qdrant's node viewer

## Current State
Current graph UI lives in:
- [frontend/src/pages/GraphPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/GraphPage.jsx)
- [frontend/src/styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

Current characteristics:
- static lane-based layout from `layoutGraph(graph)`
- edges rendered as plain SVG `<line>` elements
- nodes rendered as absolutely positioned buttons
- zoom is CSS `scale(...)`, not viewport/canvas-native zoom
- no drag persistence
- no layout engine
- no real graph interaction model beyond selection

This is serviceable for tiny graphs, but it is not a modern graph workspace.

## Recommendation
Use **React Flow** as the new renderer.

Why React Flow over alternatives:
- mature and widely used for node-based UIs
- built-in pan, zoom, drag, fit-view, minimap, controls, selection
- supports custom node components and custom edges cleanly
- easier migration path from the current node/edge JSON shape
- better fit for a product UI than a lower-level force-graph canvas

Alternatives considered:
- Cytoscape.js: strong for graph analysis and layouts, but heavier and less ergonomic for application-style node UIs
- Sigma.js / force-graph: stronger for large freeform network visualization, weaker for rich application panels and custom node cards
- D3 custom build: too much bespoke work for too little leverage

## Target UX
The replacement graph view should have:
- draggable nodes
- smooth pan/zoom
- minimap
- zoom controls and fit-view
- curved or stepped edges instead of plain straight lines
- richer node cards instead of icon bubbles only
- clearer distinction by node type: Contract, Milestone, WorkItem, Invoice, Payment, Clause
- click-to-select with the existing right drawer retained
- optional auto-layout refresh button

## Scope Boundaries
This plan changes the **frontend renderer only**.

Out of scope for the first pass:
- graph schema redesign
- backend KG relationship redesign
- persistence of user-moved node positions
- clustering / collapsing / grouping
- animated path tracing

Those can come later if the base renderer lands well.

## Data Compatibility
Backend graph payload already has the right minimal shape:
- nodes with `id`, `type`, and attributes
- edges with `source`, `target`, and `type`

Source:
- [backend/kg/graph.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/kg/graph.py)

This means the migration can adapt data in the frontend without backend changes.

## Layout Strategy
Do **not** keep the current fixed lane layout.

Recommended layout strategy for v1:
1. transform backend graph into React Flow nodes/edges
2. apply an automatic layout pass before render
3. allow manual dragging after layout

Recommended layout engine:
- **dagre** for first implementation

Why dagre first:
- deterministic
- good for directed milestone/payment graphs
- simpler than force simulation
- easier to reason about than physics layouts for business workflows

Later option:
- use **elkjs** if dagre proves too limited for mixed graph structures

## Implementation Phases

### Phase 1 — Renderer swap
Goal: replace the current static canvas with React Flow while preserving existing graph semantics.

Tasks:
- add `reactflow` dependency
- create a graph adapter that maps current payload to React Flow nodes/edges
- replace `graph-canvas` / `graph-stage` / manual SVG edge rendering
- keep the existing preset toolbar and right drawer behavior
- retain contract filter and preset filters

Expected result:
- same data, better movement and navigation immediately

### Phase 2 — Node system
Goal: make nodes feel like a modern explorer instead of icon dots.

Tasks:
- define custom node components per type
- move type icon, title, status, amount/date into small cards
- add selection styling and hover states
- make milestone/payment nodes more visually legible

Expected result:
- graph becomes scannable without opening the drawer for every node

### Phase 3 — Auto-layout
Goal: stop relying on fixed hard-coded coordinates.

Tasks:
- add dagre layout helper
- define node dimensions by type
- route graph top-to-bottom by default
- add a `Relayout` action in the graph toolbar

Expected result:
- layout scales better as the graph grows

### Phase 4 — Interaction polish
Goal: match modern node-viewer expectations.

Tasks:
- add minimap
- add built-in controls
- add fit-view on preset/filter change
- highlight connected neighborhood on selection
- style edge types differently (`GOVERNS` dashed, payment trails emphasized)

Expected result:
- graph feels closer to modern explorer tools

## File Plan
Likely files to create/update:
- update [frontend/src/pages/GraphPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/GraphPage.jsx)
- add `frontend/src/components/graph/GraphCanvas.jsx`
- add `frontend/src/components/graph/GraphNodes.jsx`
- add `frontend/src/components/graph/graphLayout.js`
- trim legacy graph CSS in [frontend/src/styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

## Technical Notes
- Keep current API calls from [frontend/src/api/client.js](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/api/client.js)
- Preserve current preset logic:
  - accepted but not paid
  - high-risk clauses
  - milestone dependencies
  - full graph
- Preserve current drawer behavior and page navigation:
  - contract -> detail page
  - milestone -> milestone page

## Risks

### 1. Graph density
Some filtered views may still be visually noisy.

Mitigation:
- fit-view
- deterministic layout
- better node sizing
- selection-based dimming

### 2. Mixed graph semantics
This graph mixes workflow nodes and warning/clause nodes.

Mitigation:
- style `Clause` edges as dashed secondary links
- optionally place clause nodes in a side band in layout helper

### 3. CSS conflicts
Current graph CSS assumes absolute-positioned DOM nodes.

Mitigation:
- isolate new renderer styles in a graph-specific module section
- delete legacy graph-stage styles after migration is stable

## Success Criteria
The replacement is successful if:
- users can drag nodes directly
- zoom/pan feels native rather than scaled DOM
- graph remains readable for multi-contract view
- presets still work without semantic regression
- the right drawer still reflects selected node cleanly
- the view feels materially more modern than the current static lane layout

## Execution Order
When this moves from plan to implementation, do it in this order:
1. install React Flow
2. build adapter from current payload to React Flow data
3. replace renderer with a minimal React Flow version
4. wire selection to existing drawer
5. add dagre layout
6. add custom node cards
7. polish controls/minimap/highlight behavior

## Recommendation
This should be implemented as a **renderer migration**, not a visual restyle.

If we only restyle the current SVG + absolute-position system, it will still feel old.
The main gain comes from switching to a real node-canvas interaction model.

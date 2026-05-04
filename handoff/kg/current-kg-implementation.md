# Current KG Implementation Handoff

## Purpose
This handoff describes the **current** knowledge-graph implementation after the semantic cleanup pass.

It explains:
- what the KG now represents
- how it is built from database state
- what each node and edge type means
- what the preset queries actually do
- how the frontend consumes and renders the graph
- what is still weak or incomplete

This is meant to be passed to another planner or LLM so it does not reason from the old, misleading “warning nodes as clauses” model.

---

## 1. High-Level Summary

The current KG is a **directed operational graph** built from structured contract records plus citation records.

It now mixes three families of information:
1. contract workflow state
   - contracts
   - milestones
   - work items
   - invoices
   - payments
2. real source-backed evidence nodes
   - `Clause` nodes projected from `Citation` rows
3. validation / consistency state
   - `ValidationWarning` nodes projected from `ValidationWarning` rows
   - `CONFLICTS_WITH` edges projected from validation warnings and their cited clause evidence

So the graph is still not a full legal-semantic knowledge graph, but it is no longer just a workflow graph with mislabeled warning nodes.

Best current description:
- **an operational contract graph augmented with citation-backed clause nodes and validation-warning overlays**

---

## 2. Core Backend Files

Main files:
- [backend/kg/graph.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/kg/graph.py)
- [backend/api/kg.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/api/kg.py)
- [backend/db/models.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/db/models.py)
- [backend/pipeline/service.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/pipeline/service.py)

Frontend consumer:
- [frontend/src/pages/GraphPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/GraphPage.jsx)
- [frontend/src/components/graph/GraphCanvas.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/graph/GraphCanvas.jsx)
- [frontend/src/components/graph/graphLayout.js](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/graph/graphLayout.js)
- [frontend/src/api/client.js](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/api/client.js)

---

## 3. Data Sources

The graph is built from SQLModel tables, not directly from wiki Markdown or retrieval results.

### 3.1 Contract workflow tables
- `Contract`
- `Milestone`
- `PaymentRequest`
- `Payment`

### 3.2 Evidence table
- `Citation`

Important point:
- real `Clause` nodes are now projected from `Citation` rows
- there is **no dedicated extracted-clause table yet**
- the graph uses the existing citation layer as its clause/evidence substrate

### 3.3 Validation table
- `ValidationWarning`

Important point:
- warning nodes are now `ValidationWarning`
- they are no longer mislabeled as `Clause`

---

## 4. Graph Build Flow

Implemented in `build_graph(session)` in [backend/kg/graph.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/kg/graph.py).

### 4.1 Contract selection
Only active contracts are included:
- `Contract.is_superseded == False`

### 4.2 Build sequence per contract
For each active contract, the graph builder:

1. adds a `Contract` node
2. loads milestones for that contract
3. adds `Milestone` nodes
4. adds `Contract -> Milestone` edges (`HAS_MILESTONE`)
5. expands `milestone.work_items_json`
6. adds `WorkItem` nodes and `Milestone -> WorkItem` edges (`HAS_WORKITEM`)
7. loads `PaymentRequest` rows
8. adds `Invoice` nodes and `Milestone -> Invoice` edges (`TRIGGERS_PAYMENT`)
9. loads `Payment` rows
10. adds `Payment` nodes and `Invoice -> Payment` edges (`SETTLED_BY`)
11. loads `Citation` rows for the contract
12. projects those into real `Clause` nodes
13. adds `Clause -> Contract` edges (`GOVERNS`)
14. adds `Clause -> Milestone` edges (`SUPPORTS`) when the citation is milestone-specific
15. loads `ValidationWarning` rows
16. adds `ValidationWarning -> Contract` edges (`ATTACHED_TO`)
17. derives `CONFLICTS_WITH` edges between clause nodes when a warning cites multiple conflicting evidence snippets
18. annotates milestone nodes with computed payment state
19. serializes the graph to `graph.json`

---

## 5. Current Node Types

### 5.1 `Contract`
Represents an active contract record.

Attrs currently stored:
- `id = contract.contract_id`
- `type = "Contract"`
- `name = contract.contract_name`
- `status = contract.validation_status`
- `contract_id`
- `source_file`

### 5.2 `Milestone`
Represents a stored milestone.

Attrs:
- `id = milestone.milestone_id`
- `type = "Milestone"`
- `name`
- `status`
- `amount`
- `contract_id`
- `source_order`
- computed payment fields:
  - `payment_state`
  - `invoice_count`
  - `payment_count`
  - `paid_amount`

### 5.3 `WorkItem`
Represents one string item from `milestone.work_items_json`.

Attrs:
- `id = stable SHA256-derived work item ID`
- `type = "WorkItem"`
- `description`
- `contract_id`
- `milestone_id`

Important improvement:
- work item IDs are now deterministic
- the old unstable Python `hash()`-based IDs are gone

### 5.4 `Invoice`
Represents a `PaymentRequest` row.

Attrs:
- `type = "Invoice"`
- `amount`
- `date`
- `contract_id`
- `milestone_id`

### 5.5 `Payment`
Represents a `Payment` row.

Attrs:
- `type = "Payment"`
- `amount`
- `date`
- `contract_id`
- `milestone_id`

### 5.6 `Clause`
Represents a real, citation-backed evidence snippet.

Projected from `Citation` rows.

Attrs:
- `type = "Clause"`
- `text = citation.text_snippet`
- `source_file`
- `location = "para x-y, page ~z"`
- `clause_type` derived from `field_name`
- `field_name`
- `block_id`
- `contract_id`
- `risk_tags = []` for now

Important note:
- these are still snippet-level evidence nodes, not full contract clause normalization
- but they are real traceable text fragments, not warnings

### 5.7 `ValidationWarning`
Represents a validation warning row.

Attrs:
- `type = "ValidationWarning"`
- `message`
- `severity`
- `contract_id`

This fixes the old semantic mismatch.

---

## 6. Current Edge Types

### 6.1 `HAS_MILESTONE`
Direction:
- `Contract -> Milestone`

### 6.2 `HAS_WORKITEM`
Direction:
- `Milestone -> WorkItem`

### 6.3 `TRIGGERS_PAYMENT`
Direction:
- `Milestone -> Invoice`

### 6.4 `SETTLED_BY`
Direction:
- `Invoice -> Payment`

### 6.5 `GOVERNS`
Direction:
- `Clause -> Contract`

Meaning:
- this citation-backed clause/evidence snippet belongs to the contract-level legal/commercial surface

### 6.6 `SUPPORTS`
Direction:
- `Clause -> Milestone`

Meaning:
- this evidence snippet supports or describes a milestone-specific extracted fact

### 6.7 `ATTACHED_TO`
Direction:
- `ValidationWarning -> Contract`

Meaning:
- this warning belongs to the contract record

### 6.8 `CONFLICTS_WITH`
Direction:
- `Clause -> Clause`

Meaning:
- the validation layer identified these cited snippets as participating in an inconsistency/conflict condition

Current source for this edge:
- warnings with codes in:
  - `amount_sum_mismatch`
  - `percentage_amount_inconsistency`
  - `installment_count_mismatch`
  - `percentage_sum_mismatch`

Important note:
- this is a first-pass conflict projection
- it is warning-driven, not a separate semantic contradiction engine

---

## 7. Stable Identity Rules

### 7.1 Contracts and milestones
Use existing DB keys:
- `contract.contract_id`
- `milestone.milestone_id`

### 7.2 Work items
Now use deterministic SHA256-based IDs:
- `work_{sha256(milestone_id + work_item)[:16]}`

This fixed the old cross-restart drift problem.

### 7.3 Clause nodes
Clause IDs are deterministic over:
- `contract_id`
- citation signature
- text snippet

Citation signature currently includes:
- `source_file`
- `field_name`
- `block_id`
- `para_start`
- `para_end`
- `page_estimate`

This gives stable clause node projection from the citation layer.

### 7.4 Validation warnings
Use:
- `warning_{warning.id}`

### 7.5 Invoice / payment nodes
Use:
- `pr_{request.id}`
- `pay_{payment.id}`

---

## 8. Payment State Model

The graph now computes milestone payment state explicitly.

Implemented by:
- `annotate_payment_states(...)` in [backend/kg/graph.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/kg/graph.py)

### 8.1 States
Current states:
- `no_invoice`
- `invoiced_unpaid`
- `partially_paid`
- `fully_paid`

### 8.2 Logic
For each milestone:
- collect outgoing invoice nodes via `TRIGGERS_PAYMENT`
- collect payments via `Invoice -> Payment` (`SETTLED_BY`)
- sum payment amounts
- compare to milestone amount where available

Rules:
- no invoices -> `no_invoice`
- invoices but no payments -> `invoiced_unpaid`
- payments exist and amount < milestone amount (or milestone amount missing) -> `partially_paid`
- payments >= milestone amount -> `fully_paid`

### 8.3 Where the state is used
- milestone nodes in the graph payload
- `accepted_not_paid` preset logic
- frontend milestone node coloring
- drawer payment-state display

### 8.4 Important limitation
This is still amount-based and milestone-level.

It does not yet model:
- invoice status transitions
- partial invoice approval vs full milestone completion
- overpayment / multiple invoice workflows beyond summed amount

But it is materially better than the old heuristic.

---

## 9. `accepted_not_paid` Semantics

This was previously weak.

Current implementation:
- returns milestones where:
  - `type == "Milestone"`
  - `status == "accepted"`
  - `payment_state != "fully_paid"`

So the preset now includes accepted milestones in these states:
- `no_invoice`
- `invoiced_unpaid`
- `partially_paid`

This is much closer to the business meaning of the label.

---

## 10. Warning and Conflict Semantics

### 10.1 High-risk warnings preset
The “high-risk” preset now returns:
- `ValidationWarning` nodes
not:
- fake clause nodes

Backend function:
- `high_risk_warnings(graph_data)`

### 10.2 Conflict edges
Conflict edges are derived from validation warnings that cite multiple clause snippets.

Mechanism:
- load `warning.citations_json`
- resolve those citations to projected clause-node IDs
- connect the cited clause nodes pairwise using `CONFLICTS_WITH`

Important limitation:
- only warnings with citations can produce conflict edges
- warnings without citations remain standalone warning nodes

---

## 11. Output Storage and Freshness

Graph artifact path:
- `settings.indexes_dir / "graph.json"`

### 11.1 Rebuild behavior
`GET /api/kg/graph`:
- rebuilds live from SQL state
- writes a fresh `graph.json`
- returns the rebuilt graph

### 11.2 Cached query endpoints
Preset/query endpoints mostly call `load_graph()`.

So the system is still hybrid:
- full graph endpoint = live rebuild
- preset endpoints = cached read of `graph.json`

This is still acceptable at current scale, but planners should know it is not fully live-consistent.

---

## 12. API Surface

Defined in [backend/api/kg.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/api/kg.py).

### 12.1 `GET /api/kg/graph`
- rebuilds and returns full graph

### 12.2 `GET /api/kg/query/accepted-not-paid`
- returns accepted milestones not fully paid

### 12.3 `GET /api/kg/query/high-risk-warnings`
- returns warning nodes with severity `error` or `warning`

### 12.4 `GET /api/kg/query/high-risk-clauses`
- compatibility alias
- currently returns the same warning nodes as `high-risk-warnings`

### 12.5 `GET /api/kg/query/payment-trail/{milestone_id}`
- returns a small payment subgraph around one milestone

### 12.6 SVG endpoints
Still exist:
- `/api/kg/svg`
- `/api/kg/svg/{contract_id}`

These are legacy output relative to the React Flow UI.

---

## 13. Frontend Consumption

Main page:
- [frontend/src/pages/GraphPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/GraphPage.jsx)

Renderer:
- [frontend/src/components/graph/GraphCanvas.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/graph/GraphCanvas.jsx)
- [frontend/src/components/graph/graphLayout.js](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/graph/graphLayout.js)

### 13.1 Data flow
On graph page load:
- fetch `contracts()` and `graph()`
- keep `fullGraph`
- derive current filtered `graph`

### 13.2 Contract filter
`filterByContract(...)` still performs a neighborhood-style filter around the selected contract.

This is still a UI-oriented scope filter, not a separate backend subgraph projection.

### 13.3 Presets
Current presets:
- accepted but not fully paid
- high-risk warnings
- milestone dependencies
- full graph

### 13.4 Selection / drawer behavior
The page computes:
- outgoing/incoming edges for the selected node
- connected neighborhood highlighting
- related clause nodes from local graph edges
- related warning nodes from local graph edges
- invoiced total from outgoing invoice edges

The drawer now has semantically cleaner sections:
- Relevant Clauses = real citation-backed clause nodes
- Validation Warnings = warning nodes

---

## 14. Frontend Visual Semantics

### 14.1 Node types
The frontend now distinguishes:
- `Contract`
- `Milestone`
- `WorkItem`
- `Invoice`
- `Payment`
- `Clause`
- `ValidationWarning`

### 14.2 Milestone coloring
Milestone cards are color-coded by `payment_state`:
- `no_invoice` = grey/slate
- `invoiced_unpaid` = amber
- `partially_paid` = blue
- `fully_paid` = green

### 14.3 Warning nodes
Warnings are rendered separately from clauses.

### 14.4 Edge styling
Frontend edge tones now roughly mean:
- payment edges = teal/greenish
- clause/support/governs edges = clause tone
- warning attachment edges = warning tone
- conflict edges = red dashed emphasis

---

## 15. Legacy SVG Path

`render_svg(...)` still exists in [backend/kg/graph.py](/Users/mulia/Desktop/Projects/Intern%20Project/backend/kg/graph.py).

It was minimally updated to understand:
- `ValidationWarning`
- `ATTACHED_TO`
- `CONFLICTS_WITH`

But it remains legacy/debug output, not the main UX surface.

---

## 16. What the KG Does Well Now

### 16.1 Better semantic honesty
The old `Clause == ValidationWarning` mismatch is fixed.

### 16.2 Real evidence nodes are now visible
The graph is now connected to the citation layer through real `Clause` nodes.

### 16.3 Payment state is materially more useful
Milestones now expose a meaningful payment-status model that the UI can read directly.

### 16.4 Conflict visualization exists
Validation inconsistencies can now surface as red `CONFLICTS_WITH` edges between cited evidence snippets.

### 16.5 Work item identity is stable
Work item nodes no longer drift across interpreter restarts.

---

## 17. Current Weaknesses / Remaining Debt

This section matters most for future planning.

### 17.1 Clause nodes are still snippet-level, not fully normalized clauses
They come from `Citation.text_snippet`, not a dedicated clause-extraction schema.

Consequences:
- multiple snippets from the same real document clause may appear as separate nodes
- clause hierarchy is not modeled
- clause titles / canonical numbering are not preserved as first-class graph structure

### 17.2 No dedicated extracted-clause table yet
The graph currently projects from `Citation` rows instead of a dedicated `ExtractedClause` table.

This is a pragmatic implementation choice, not the final data model.

### 17.3 Conflict edges are warning-driven, not semantic-logic-driven
Current `CONFLICTS_WITH` edges exist only when a validation warning cites enough evidence to connect clauses.

So conflict visibility is only as good as:
- validation coverage
- warning citation quality

### 17.4 Cached query endpoints still exist
Preset endpoints still use `load_graph()` rather than rebuilding live.

### 17.5 Contract filter remains UI-local
There is still no dedicated backend contract-subgraph endpoint.

### 17.6 Drawer relationship model is still adjacency-based
The drawer is still local-neighborhood driven rather than using graph-specific selectors.

### 17.7 `risk_tags` on clause nodes are placeholders
They currently exist as an empty list.
They are ready for future semantic tagging, but not populated.

---

## 18. Safe Next Extensions

If another planner is extending this system, the safest next directions are:

### 18.1 Add a dedicated extracted-clause table later
That would let the graph move from citation snippets toward canonical clause entities.

### 18.2 Add clause numbering / heading metadata
Useful fields would be:
- clause label
- canonical section number
- normalized clause family
- source block lineage

### 18.3 Make payment-state query endpoints live or freshness-aware
Either:
- rebuild on all graph queries
or
- formalize `graph.json` freshness policy

### 18.4 Add richer conflict types
Current `CONFLICTS_WITH` is generic.
Future edges could carry categories like:
- amount conflict
- percentage conflict
- installment-count conflict

### 18.5 Persist graph node positions if manual layout becomes important
React Flow now supports drag, but positions are not stored.

---

## 19. Planner Summary

If another planner needs the short version:

- backend now builds an operational contract graph plus citation-backed clause nodes plus validation warning nodes
- `ValidationWarning` is separate from `Clause`
- `Clause` nodes are projected from `Citation` rows, not from a dedicated clause table
- milestones now carry computed `payment_state`
- accepted-not-paid logic is now payment-state aware
- work item IDs are deterministic
- validation warnings can create `CONFLICTS_WITH` edges between cited clause nodes
- frontend graph page renders all of this with React Flow and colors milestones by payment state
- biggest remaining limitation is that clause nodes are still snippet-level evidence, not canonical normalized legal clauses

# UI / UX Modernization Plan

## Objective

Modernize the application in a way that improves clarity, visual hierarchy, and workflow speed without introducing gratuitous redesign churn.

Primary targets:

1. `Contract Query` page
2. `Payment Workflow` page
3. global sidebar and topbar shell
4. move `Regression Runner` entry into the top-right shell position currently occupied by the offline-only pipeline placeholder

This plan is intentionally structured around the current codebase:

- [Layout.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/Layout.jsx)
- [QueryPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/QueryPage.jsx)
- [WorkflowPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/WorkflowPage.jsx)
- [RegressionPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/RegressionPage.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

---

## Design Direction

### Product stance

The UI should feel like:

- an operator console for offline contract intelligence
- not a developer dashboard
- not a generic admin template

That means:

- tighter hierarchy
- fewer undifferentiated white boxes
- clearer task framing
- higher information density where useful
- stronger separation between navigation, context, and actions

### Visual language

Adopt a more deliberate shell:

- darker, more sculpted sidebar
- lighter content canvas
- clearer card tiers
- consistent 12px / 16px / 24px spacing rhythm
- stronger headline-to-body contrast
- fewer flat rectangles with identical borders

### Interaction model

The app should consistently answer:

1. Where am I?
2. What am I looking at?
3. What can I do next?

Current weak points:

- Query page is functional but visually generic
- Workflow page behaves like a long form attached to a kanban list
- Sidebar looks serviceable but not intentional
- Regression is buried as a full page nav item while the top-right shell has underused status real estate

---

## Information Architecture Changes

### 1. Shell / Navigation

#### Current

- left sidebar contains all primary routes
- top-right status shows only offline/local status
- regression runner exists as a normal sidebar item

#### Proposed

Sidebar becomes:

- core product navigation only
  - Overview
  - Contract Detail
  - Milestone
  - Payment Workflow
  - Contract Query
  - Wiki
  - Knowledge Graph
  - Health

Top-right shell becomes:

- `Regression Runner` launch area
- offline/local status compact indicator
- potentially a compact system health pill cluster

Reason:

- regression is an operator tool, not a primary browsing destination
- it fits better as an execution utility than a first-tier nav destination

#### Planned result

- remove `Regression Runner` from first-class sidebar prominence
- add a topbar utility button/card in the current offline placeholder zone
- keep regression page itself, but access it from top-right utility action

---

## Page-by-Page Plan

### A. Contract Query Page

File:
- [QueryPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/QueryPage.jsx)

#### Current problems

- left session rail is useful but visually flat
- query thread lacks strong turn separation and response hierarchy
- composer toolbar is crowded and low-status
- evidence cards feel appended rather than integrated
- page does not feel like a premium analysis workspace

#### Proposed redesign

##### 1. Split the page into 3 deliberate zones

- `Session rail`
  - narrower, more dashboard-like history stack
  - search or recent-session grouping later if needed
- `Conversation workspace`
  - main answer thread
  - larger reading width
  - better response cards
- `Action composer dock`
  - elevated, sticky lower composer
  - contract selector + topK + wiki persistence as structured controls

##### 2. Upgrade answer presentation

AI answers should render as:

- primary answer card
- compact metadata ribbon
- expandable evidence drawer/card group

User question should render as:

- smaller, right-aligned or visually lower-emphasis prompt card
- distinct tone from answer card

##### 3. Make evidence feel trustworthy

Evidence blocks should become:

- grouped, structured attachments
- clearer source label / clause label / snippet separation
- stronger action affordance for:
  - open source page
  - open project page

##### 4. Improve composer UX

Composer should become:

- persistent bottom dock
- stronger CTA hierarchy
- clearer advanced controls row

Target layout:

- row 1: contract scope, retrieval depth, wiki persistence
- row 2: query input + run button

##### 5. Add contextual empty states

Examples:

- no session yet
- no contract selected
- no evidence for answer
- loading previous session

#### Acceptance criteria

- query page reads like an analysis console, not a plain chat form
- evidence is easier to scan than current appended cards
- composer is clearly the primary action surface
- session history feels structured, not just stacked buttons

---

### B. Payment Workflow Page

File:
- [WorkflowPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/WorkflowPage.jsx)

#### Current problems

- board and form are coupled too tightly
- milestone progression is understandable but visually plain
- right sidecard mixes too many responsibilities
- acceptance, request, and payment actions feel like form fields rather than workflow steps
- the experience does not feel like a production operations view

#### Proposed redesign

##### 1. Reframe as a two-panel operations view

Left:

- milestone workflow board
- grouped by stage
- stronger stage headers with counts and amounts

Right:

- selected milestone inspector
- action modules, not one long mixed form

##### 2. Turn the right panel into step modules

Instead of one large form block, split into:

- `Acceptance`
- `Payment Request`
- `Payment Logging`
- `History / Existing Requests`

Each module should:

- show prerequisites
- show status
- show only the relevant inputs for that step

##### 3. Make financial summary more executive and less form-like

Financial summary should become a top summary strip or premium side summary:

- total contract
- unpaid balance
- requested
- paid

with stronger visual hierarchy and comparison styling

##### 4. Improve milestone stage readability

Each milestone row/card should show:

- name
- value
- state
- primary next action
- possibly acceptance / request / paid badges

This should look closer to:

- pipeline operations board
- not table rows with buttons

##### 5. Preserve directness

Do not over-animate or over-nest this page.

This is an operator flow. Speed matters more than visual novelty.

#### Acceptance criteria

- selected milestone actions are obvious
- the user understands what step is blocked and why
- payment state is clearer at a glance
- the page feels like workflow operations, not a mixed admin form

---

### C. Sidebar Overhaul

File:
- [Layout.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/Layout.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

#### Current problems

- structurally acceptable, visually conservative
- branding area is too quiet
- nav items do not have enough hierarchy or sophistication
- local-mode block feels like footer status, not a designed system panel

#### Proposed redesign

##### 1. Make sidebar more product-defining

Use:

- darker surface than main content
- sharper brand lockup
- stronger active-state treatment
- more vertical breathing room

##### 2. Segment nav into meaningful groups

Suggested grouping:

- `Workspace`
  - Overview
  - Contract Detail
  - Milestone
  - Payment Workflow
  - Contract Query
- `Knowledge`
  - Wiki
  - Graph
- `System`
  - Health

Regression moves out of this group and into topbar utility.

##### 3. Improve active item behavior

Active nav should feel intentional:

- stronger surface contrast
- icon emphasis
- left rail or pill treatment
- better hover feedback

##### 4. Rebuild footer utilities

Sidebar footer should include:

- language switch
- local/offline model status
- possibly compact system capability summary

This should feel like a structured footer module, not an afterthought

#### Acceptance criteria

- sidebar looks like a deliberate product shell
- nav grouping is easier to understand
- regression no longer competes with first-tier navigation

---

### D. Topbar Utility / Regression Placement

Files:
- [Layout.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/Layout.jsx)
- [RegressionPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/RegressionPage.jsx)

#### Requirement

Move `Regression Runner` to the top-right position of the current offline-only pipeline placeholder.

#### Proposed solution

Replace current single status chip with a compact utility cluster:

- primary utility button:
  - `Regression Runner`
- secondary status pill:
  - `Offline only`
- tertiary optional indicator:
  - model server reachable / unavailable

Behavior:

- clicking the regression utility button navigates to the regression page
- regression remains a page, but no longer occupies primary sidebar hierarchy

#### Acceptance criteria

- regression is available from every page
- it feels like an operational tool, not a primary content section
- offline status remains visible but smaller

---

## Execution Plan

### Phase 1 — Shell First

Files:

- [Layout.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/components/Layout.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

Scope:

- sidebar redesign
- nav grouping
- topbar utility redesign
- move regression trigger into top-right shell

Reason:

- this sets the visual system for the rest of the pages

### Phase 2 — Query Page Modernization

Files:

- [QueryPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/QueryPage.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

Scope:

- session rail redesign
- thread card redesign
- composer dock redesign
- evidence attachment redesign

### Phase 3 — Workflow Page Modernization

Files:

- [WorkflowPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/WorkflowPage.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

Scope:

- milestone board redesign
- right inspector redesign
- financial summary redesign
- action module separation

### Phase 4 — Regression Page Alignment

Files:

- [RegressionPage.jsx](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/pages/RegressionPage.jsx)
- [styles.css](/Users/mulia/Desktop/Projects/Intern%20Project/frontend/src/styles.css)

Scope:

- align visual style with new shell
- ensure launching from topbar feels coherent

---

## Constraints

1. Do not destabilize app routing
2. Keep current data flows and API calls intact
3. Prefer layout and component restructuring over inventing new backend dependencies
4. Avoid design bloat
5. Preserve mobile survivability even if desktop is the main target

---

## Risks

### 1. CSS sprawl

Current styling is centralized in one large file.

Mitigation:

- introduce page-scoped class namespaces
- avoid broad selector changes without a local wrapper

### 2. Over-designing workflow

The workflow page is operations-heavy.

Mitigation:

- optimize for speed and clarity
- not decoration

### 3. Topbar crowding

Regression relocation could clutter the header.

Mitigation:

- use compact utility layout
- keep offline status secondary

---

## Success Criteria

The redesign is successful if:

1. Query page feels like a modern analysis workspace
2. Workflow page feels like a real payment operations console
3. Sidebar becomes visually intentional and easier to scan
4. Regression runner is accessible globally without stealing primary nav prominence
5. Spacing and hierarchy are more consistent across the shell

---

## Recommended Execution Order

1. Shell and topbar utility refactor
2. Query page redesign
3. Workflow page redesign
4. Regression page visual alignment

This order is the least risky because it establishes the design system first, then applies it to the two highest-value task pages.

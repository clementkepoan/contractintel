# KG UX Conflict Edge Removal Plan

## Objective

Remove clause-to-clause conflict lines from the graph UI and add an explicit milestone exit path.

## Changes

1. Remove `CONFLICTS_WITH` edges from KG graph generation
   - warnings remain
   - clause evidence remains
   - clause-to-clause dotted red grouping edges are dropped

2. Filter `CONFLICTS_WITH` from the frontend renderer
   - immediate UX fix
   - avoids stale `graph.json` continuing to show old edges

3. Add `Back to contract view`
   - visible only when the page is in milestone focus
   - clears milestone focus without changing the selected contract

## Expected Result

- no dotted red clause-to-clause links
- milestone exploration remains focused
- user can return to contract scope explicitly without switching the dropdown

# Retrieval Fix Plan

## Objective

Improve retrieval quality first, especially for non-formal documents such as:

- `rfp`
- `construction_instruction`

without regressing retrieval on formal clause-structured contracts.

## Scope

This plan is limited to:

- chunk construction
- retrieval metadata
- family tagging
- parent expansion behavior

It does not change generation prompts or answer rendering.

## Steps

1. Add document-type-aware retrieval metadata.
   - carry `document_type` through chunk records, local index, and vector payloads

2. Split chunking strategy by document type.
   - keep clause-based chunking for formal contracts
   - add section-based chunking for `rfp` / `construction_instruction`

3. Improve non-formal labels.
   - replace fallback labels like `專案名稱` or `施工說明書` as dominant retrieval anchors
   - use section headings and heading paths instead

4. Narrow family tagging for non-formal documents.
   - assign at most the strongest `1–2` families
   - avoid broad legal-remedy families unless supported by explicit keywords

5. Reduce or disable parent expansion on non-formal documents.
   - avoid deepening already-collapsed parent sections

6. Reindex contracts and rerun retrieval-only regression.
   - primary targets: `01XX`, `03XX`
   - guardrails: `02XX`, `05XX`

## Success criteria

1. `01XX` top retrieval labels are no longer all `專案名稱`.
2. `03XX` top retrieval labels are no longer all `施工說明書`.
3. Query intent changes the retrieved section set for `01XX` and `03XX`.
4. `05XX` keeps strong retrieval on:
   - delay remedies
   - payment
   - force majeure / tariff


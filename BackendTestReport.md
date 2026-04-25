# Backend Test Report

## Scope

This report covers backend extraction, validation, ingestion, workflow enforcement, and retrieval behavior against the sample dataset in `Database/`.

## Test Case 1: Reference Document Handling

- Input: `Database/01XX專案.docx`
- Expected:
  - classified as reference/RFP
  - no milestones extracted
  - warning for missing total and missing milestones
- Actual:
  - classified as `rfp`
  - `0` milestones extracted
  - warnings emitted for missing total amount and missing milestones
- Result: PASS

## Test Case 2: Standard Contract Extraction

- Input: `Database/02XX專案.docx`
- Expected:
  - total amount `23,830,643`
  - `3` milestones
  - milestone percentages `30/40/30`
  - citations attached to extracted fields
- Actual:
  - total amount `23,830,643`
  - `3` milestones
  - percentages `30/40/30`
  - citations stored and returned through APIs
- Result: PASS

## Test Case 3: Inconsistent Installment Contract

- Input: `Database/04XX專案.docx`
- Expected:
  - extract installment rows from payment section
  - detect that the document declares six installments but only five payment rows are present in the visible clause
  - detect percentage-to-amount inconsistency on the final row
- Actual:
  - extracted `5` milestone/payment rows
  - emitted `installment_count_mismatch`
  - emitted `percentage_amount_inconsistency`
- Result: PASS

## Test Case 4: Split-Line Amount Extraction

- Input: `Database/05XX專案.docx`
- Expected:
  - handle milestone amounts split across adjacent lines
  - extract four milestone amounts successfully
- Actual:
  - extracted `4` milestones
  - extracted amounts `3,339,000`, `5,008,500`, `5,008,500`, `3,339,000`
- Result: PASS

## Test Case 5: Workflow Rule Enforcement

- Expected:
  - payment request rejected before passed acceptance exists
- Actual:
  - API returns error when a payment request is attempted without a valid acceptance record
- Result: PASS

## Test Case 6: Query Chat Memory

- Expected:
  - first query creates a chat session
  - follow-up query reuses the same session
  - user and assistant messages are persisted in order
- Actual:
  - `/api/query` returns `chat_session_id`
  - second query with the same `chat_session_id` returns the same session
  - `/api/chat/sessions/{id}/messages` returns human/ai/human/ai
- Result: PASS

## Automated Verification

- `pytest -q tests`
- Current status: `12 passed`

## Known Gaps

- `.doc` ingestion has not been verified locally because `soffice` is not installed in the current environment.
- Embedding retrieval is implemented, but the first model download is still required before hybrid retrieval can run fully offline.
- Work item extraction remains conservative for some contract formats.

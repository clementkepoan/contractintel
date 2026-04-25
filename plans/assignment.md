# Assignment Checklist

## Core Objective
- [ ] Convert engineering contracts/RFPs into searchable offline knowledge.
- [ ] Extract lump sum, milestones, milestone payment amounts, percentages, and work lists automatically.
- [ ] Provide a web interface for contract, acceptance, payment request, and payment tracking.

## Input Constraints
- [ ] Support `.doc` and `.docx` test data with version differences and inconsistent field names.
- [ ] Handle scattered clauses and mixed amount formats such as percentage, tax-included, and installment wording.

## Mandatory Rules
- [ ] Keep the entire workflow offline after setup.
- [ ] Avoid cloud LLM, embedding, OCR, and reranking APIs.
- [ ] Run embeddings, LLMs, vector search, and reranking locally.
- [ ] Attach citations to every extracted result with file name and paragraph/page/block location.
- [ ] Generate milestones and amounts through the document pipeline only.

## Required Functions
- [ ] Ingest documents and convert them to text.
- [ ] Chunk the text.
- [ ] Build indexes with BM25 and/or vectors.
- [ ] Extract contract information into the standard JSON format.
- [ ] Validate total amount versus milestone amounts.
- [ ] Show warnings and source clauses when values conflict.

## Required UI
- [ ] Contract Overview page with name, total amount, milestone summary, and status.
- [ ] Milestone page with work list, payment terms, acceptance criteria, and citations.
- [ ] Payment Request page with pending acceptance, accepted, payment requested, and payment made states.
- [ ] Query page with natural-language search and answer basis.

## Acceptance Flow
- [ ] Create acceptance records per milestone.
- [ ] Block payment requests until acceptance passes.
- [ ] Store payment request date, amount, and remarks.
- [ ] Calculate total contract amount, payment requested, paid, and unpaid in real time.

## Output Schema
- [ ] `contract_name`
- [ ] `total_amount`
- [ ] `currency`
- [ ] `milestones[]`
- [ ] `milestone_id`
- [ ] `name`
- [ ] `amount`
- [ ] `percentage`
- [ ] `work_items[]`
- [ ] `acceptance_criteria`
- [ ] `payment_condition`
- [ ] `status`
- [ ] `citations[]`
- [ ] `validation`

## Deliverables
- [ ] Executable source code with startup instructions.
- [ ] `README.md` with install, model, architecture, and limitations.
- [ ] Import example data and show output results.
- [ ] Screenshots or short video of the end-to-end flow.
- [ ] Test report with at least 3 cases.

## Bonus Goals
- [ ] LLM Wiki with `index.md`, `log.md`, `contracts/*.md`, and `milestones/*.md`.
- [ ] Knowledge graph for Contract, Milestone, WorkItem, Invoice, Payment, and Clause.
- [ ] Bidirectional Wiki-KG navigation with citation access.

## Fail Criteria
- [ ] Do not use cloud APIs.
- [ ] Do not lose citation traceability.
- [ ] Do not fail to generate milestones and payment data.
- [ ] Do not hide the acceptance/payment workflow.

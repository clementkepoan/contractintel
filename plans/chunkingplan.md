# Chunking and Retrieval Improvement Plan

## Guiding Principle
- Use LangChain-native primitives where they clearly improve the system.
- Keep custom implementations where the current file-backed architecture already fits better.

## Current Decision
- Implement now:
  1. Recover real BM25 scores.
  2. Add parent-child retrieval metadata.
  3. Add clause-family tagging.
  4. Add prohibition-term coverage.
  5. Add parent expansion after retrieval.
  6. Add clause-family-aware weighting and expansion triggers.
  7. Update evidence formatting for expanded parents.
- Defer for now:
  1. `EnsembleRetriever` migration.
  2. `MultiQueryRetriever` migration.
  3. `SKLearnVectorStore` fallback rewrite.

## Execution Steps
- [x] 1. Add `parent_chunk_id` and `clause_family` to chunk schema.
- [x] 2. Add clause-family detection helpers and keyword families.
- [x] 3. Extend clause/subclause chunk construction to populate parent metadata.
- [x] 4. Persist parent chunk lookup data in the local JSON index.
- [x] 5. Extend Qdrant payload metadata with `parent_chunk_id` and `clause_family`.
- [x] 6. Replace rank-derived BM25 scoring with real `BM25Okapi.get_scores()` scoring.
- [x] 7. Update hybrid fusion to combine RRF with normalized score contributions.
- [x] 8. Add parent expansion over retrieved child chunks using the local parent lookup map.
- [x] 9. Add prohibition-related terms to subclause detection and query expansion.
- [x] 10. Extend query intent detection for price-adjustment and force-majeure style questions.
- [x] 11. Add clause-family overlap boosting in source weighting.
- [x] 12. Update evidence formatting to mark parent-expanded clause context.
- [x] 13. Run compile/build checks.
- [x] 14. Re-index contracts after code changes.
- [ ] 15. Run regression queries on tariff / force-majeure / delayed-progress / milestone questions.
- [ ] 16. Evaluate whether `EnsembleRetriever` adds enough value to justify replacing the custom fusion layer.
- [ ] 17. Evaluate whether `MultiQueryRetriever` is worth the extra LangChain model-adapter complexity.

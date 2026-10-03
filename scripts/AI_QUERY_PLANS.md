# Validated analytical queries

The Ollama hybrid route now uses a schema-constrained planning request for complex deployment counts, comparisons, and percentages. Direct lookups remain model-free. Record explanations and workflow questions retain the existing tool/guidance path.

The backend validates plan shape, dates, explicit tenants/statuses/emergency flags, recognized periods, percentage subset rules, and inherited scope. It rejects unsupported aggregate filters and unrequested tenant/status restrictions. Invalid plans return a clarification rather than execute a broader query. These checks cover the supported vocabulary; they are not a guarantee of arbitrary natural-language interpretation.

PostgreSQL GROUP BY calculates totals and status/tenant breakdowns without loading every matching booking. Percentages and comparison differences are rendered from verified counts, without a second model response. Answers display the applied scopes. The response includes query_scope and evidence; the UI carries query_scope in history. Client-supplied scope is validated input and always queried again, never accepted as proof of a result.

Analytical plans support one count scope, 2-4 comparison scopes, or a numerator/denominator pair. Multi-status unions, exclusions, region/technology/requester/assignment filters, averages and predictions require further tool support. Existing explanation questions do not pass through this new numerical planner. Builtin and hosted providers retain their prior paths.

FAISS rebuilds reuse document embeddings by content hash/provider/model, using a bounded process-local cache of 4096 documents. The FAISS index is still rebuilt after a detected source change; the cache is lost on restart. Analytical queries skip embeddings and FAISS entirely.

Planning uses temperature 0, the configured context window, and a separate 1024-token planning budget. A valid complex analytical query normally needs one model call plus database queries. No latency improvement has been benchmarked.

Read-only live rehearsal against the synthetic sample dataset:

```powershell
Get-Content scripts/verify-ai-plans.py -Raw | docker compose exec -T app python -
Get-Content scripts/verify-ai-demo.py -Raw | docker compose exec -T app python -
```

Expected: EPCAT failed September 2026 = 1; EPCAT booked October 2026 = 2; failed September share = 2/6 = 33.33%. Follow-up comparison must preserve EPCAT and both periods.
Validation on October 3, 2026: 109 focused backend assistant/access tests passed; frontend type checking and 91 frontend tests passed. All 15 existing live demo checks and three new live analytical checks passed using qwen3:8b. Docker Compose rebuilt and started the app; /health/ready reports ready=true and database=ok.

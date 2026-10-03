# CPU deployment with separate app, database, and Ollama pods

The application and inference service can run independently. Set DATABASE_URL from the database connection secret on the app pod. Set AI_BASE_URL to the Ollama Kubernetes Service URL (for example http://ollama.inference.svc.cluster.local:11434, if that service/namespace exists). No database container needs to live in the Ollama pod. The app performs authorized database queries; Ollama receives approved record data and tools, not database credentials.

App pod environment for the CPU profile:

```text
AI_PROVIDER=ollama_rag
AI_MODEL=qwen3:8b
AI_EMBEDDING_MODEL=nomic-embed-text
AI_BASE_URL=http://ollama.inference.svc.cluster.local:11434
AI_CONTEXT_WINDOW=4096
AI_MAX_OUTPUT_TOKENS=512
AI_TIMEOUT_SECONDS=120
AI_NUM_THREADS=0
AI_KEEP_ALIVE=30m
AI_PLAN_CACHE_SECONDS=300
```

AI_NUM_THREADS=0 lets Ollama select threads. For a pod capped at four vCPUs, start benchmarking AI_NUM_THREADS=4, then compare lower/higher values under that same quota. Do not assume Azure vCPUs correspond to physical cores. No optimum thread count is claimed without measurements on the target machine.

Ollama pod environment:

```text
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=30m
```

Keep the model files on a persistent volume and make both configured models available before serving AI requests. Use a Kubernetes Service for the app-to-Ollama connection. Image rollout, persistence, resource requests/limits, and the external database secret belong to the actual cluster deployment; no live cluster was changed here. Use identical settings when testing the image on the Linux host.

The single loaded-model limit favors memory headroom. FAISS embedding requests can unload Qwen and cause a subsequent cold load. Exact schedule questions and supported aggregate grammar bypass FAISS, avoiding that model switch. The existing full Compose stack remains a local rehearsal setup. Its optional CPU override is:

```sh
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

The 4K profile trims retrieved text and older conversation messages on general reasoning requests. The normal profile retains the 8K setting. Keep the larger context if full conversation/document coverage matters and sufficient memory is allocated. Direct exact-record explanations use compact prompts; contextual questions retain the general reasoning path.

Implemented CPU improvements:

- Exact schedule references are fetched first and explained in one model call. All requested records must be verified; failed lookups retain the original retry path. No embeddings or large tool schemas are needed on successful exact-record requests.
- A conservative parser handles simple two-scope count comparisons and status percentages without invoking a model. Ambiguous or unsupported grammar goes to the validated AI planner rather than broadening the database query.
- Validated analytical plans are cached for up to five minutes of inactivity, at most 128 per app process. Cache keys include provider/model/context, date, known tenants, question and prior scope. Every answer still validates filters and queries the current database; cached plans are never cached facts. App replicas have independent caches.
- Chat/planning requests explicitly use CPU inference, configurable thread count, and a 30-minute keep-alive. One parallel request avoids simultaneous inference competing for limited CPU/RAM. Higher concurrency needs a load test on the target pod.

Measured on the current Windows-hosted Linux Docker containers, October 3, 2026 (not the target Azure box):

| Case | Earlier sample | Optimized sample |
|---|---:|---:|
| Direct count | 0.002-0.042 s | 0.002-0.043 s |
| Supported comparison | 13.892 s, warm model | 0.009 s, no model call |
| Supported percentage | 10.680 s, warm model | 0.004 s, no model call |
| Exact-record explanation | 43.844 s, tool loop | 5.748 s, then 2.401 s with warm prompt cache |

A new analytical grammar that still requires the model can remain slow: an intermediate cold comparison run took 24.291 s including 7.062 s model loading. These are individual local service measurements, not percentiles, concurrency results, or Azure latency promises.

Ollama reports qwen3:8b with 4096 context at 100% CPU, model size 5.9 GB; one idle container memory sample was 5.775 GiB. That is not a peak-memory measurement or proof that an 8 GB pod cannot run out of memory. The memory budget applies to the Ollama pod; app/database sizing is separate. Test cold loading, embedding/model switching, and realistic questions under the target limits. The 500 GB disk budget does not improve token-generation speed; CPU and memory bandwidth are the main remaining constraints.

118 focused backend assistant/access tests passed, including dropped-filter rejection, both-record verification, ambiguous-period fallback, CPU options and fresh database results after a cached-plan hit.

Rehearsal scripts:

```sh
docker compose exec -T app python - < scripts/benchmark-ai-latency.py
docker compose exec -T app python - < scripts/verify-ai-demo.py
docker compose exec -T app python - < scripts/verify-ai-plans.py
```

In Kubernetes, use the same scripts with kubectl exec -i against the app pod if the Python environment has the application available.

Runtime setting references: [Ollama FAQ](https://docs.ollama.com/faq), [chat API](https://docs.ollama.com/api/chat), [runtime option definitions](https://github.com/ollama/ollama/blob/main/api/types.go).
Final live verification with the CPU profile: all 15 existing demo checks and all three analytical checks passed. The app readiness endpoint reports ready=true and database=ok. The target Azure/Linux Kubernetes deployment has not been tested or applied.

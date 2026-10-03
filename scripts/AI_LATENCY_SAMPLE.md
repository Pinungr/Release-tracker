# Local assistant latency sample — October 3, 2026

Read-only calls inside the running app container, one example per analytical/reasoning case. These are local service times, not browser timings, percentiles, or concurrency results. Answers matched the synthetic sample dataset.

| Case | Time |
|---|---:|
| Direct count, first call | 0.042 s |
| Direct count, repeat | 0.002 s |
| Two-period comparison | 13.892 s |
| Failure percentage | 10.680 s |
| One-record explanation | 43.844 s |

Ollama reports qwen3:8b at 100% CPU, context 8192; Windows reports Radeon RX 7700 XT and integrated Radeon graphics. Native Ollama was not found by PATH or its usual per-user installation path. GPU acceleration has not been configured or tested.

Comparison: 102 generated tokens, 11.582 s generation; percentage: 97 tokens, 10.232 s generation. Explanation used two embedding requests and three chat requests; the first chat spent 28.455 s processing the prompt. The next candidates are verified GPU acceleration, preloading exact-record tools while skipping FAISS for exact identifiers, and smaller model prompts/tool sets. No projected speedup has been established.

Reproduce:

```powershell
Get-Content scripts/benchmark-ai-latency.py -Raw | docker compose exec -T app python -
```

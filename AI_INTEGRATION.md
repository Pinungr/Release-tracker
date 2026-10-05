# PDS Assistant / Future AI / MCP Integration

PDS exposes the same approved read-only schedule query service in three ways:

1. **PDS Assistant** — an in-app floating chat for authorized PDS users.
2. **Authenticated REST API** under `/api/assistant/...` for PDS/in-house clients using a normal PDS user JWT.
3. **MCP endpoint** at `/mcp` for Copilot, Codex/ChatGPT, Claude, and other MCP-capable hosts.

The optional local AI mode combines Qwen3 through Ollama, process-local FAISS
retrieval, and read-only database tools. Recognized lookups, counts, lists,
availability, and supported aggregate comparisons return database-backed answers
without calling a model. More complex questions use validated query plans or
verified record explanations. FAISS supplies supporting context; it does not
calculate counts or establish current statuses. The model never executes SQL or
receives database credentials. The local mode sends model requests to the
configured Ollama service, which can run in a separate pod.

## Deployment modes

Keep one shared `.env`. Its future-ready AI, corporate gateway, and MCP settings
remain available in all modes; the selected Compose file fixes the provider.

| Deployment | Command | Container provider | Services |
| --- | --- | --- | --- |
| Default lightweight | `docker compose up -d --build` | `builtin` | PDS, PostgreSQL |
| Optional local AI | `docker compose -f docker-compose.Ollama_hosted.yml up -d --build` | `ollama_rag` | PDS, PostgreSQL, Ollama, model pull |

The default does not start Ollama, pull its image, or download models. It uses
existing deterministic routing and read-only query services. Supported questions
remain available without any model endpoint. Group permissions and the master
AI Enable switch still control assistant access; MCP remains independently
configurable. No second chat UI or assistant implementation is introduced.

Changing `.env`'s `AI_PROVIDER` cannot switch either supplied Compose deployment:
the default always selects `builtin`, while the full-stack file always selects
`ollama_rag`. Standalone containers/pods continue to use the configured provider.

## Hybrid question routing

The assistant uses the read-only backend API directly for recognized counts,
filtered lists, user/group membership counts, schedule status / Change No. / Release Manager lookups, basic
summaries, and next-slot availability. These answers do not call the chat model,
embedding model, or FAISS, and remain available if AI configuration is incomplete.

In Ollama mode, a direct API error, unexpected null, or malformed result triggers the reasoning
path, which searches FAISS context and retries approved read-only tools. Valid zero
counts and empty result lists remain direct answers. If embeddings are unavailable,
the app agent can still use database tools. Failed or null tool results cannot
verify model-generated facts.

In Ollama mode, questions requiring explanation, comparison, semantic matching, or conversational
context use the configured local model. The database retrieval component builds a
process-local FAISS index from live records; the app agent supplies reviewed workflow
guidance and coordinates allow-listed backend API tools. Record facts must be
verified with a successful backend tool call. Generic workflow questions use the
application guide without embedding database records. Neither component writes data.
These are cooperating application components using the same configured chat model,
not two independently configured model servers.

`AI_PROVIDER=ollama_rag` enables this hybrid mode; `AI_MODEL` chooses the reasoning
model, `AI_EMBEDDING_MODEL` chooses the FAISS embedding model, and Compose connects
both to `AI_BASE_URL=http://ollama:11434`. `/api/assistant/access` reports
`intelligence_configured` separately from the always-available direct chat path.
This configuration flag does not perform a live model health check.
`AI_MAX_OUTPUT_TOKENS=512` bounds each local-model response; increase only if your
hardware can return longer responses within `AI_TIMEOUT_SECONDS`.
This deployment uses `AI_MODEL=qwen3:8b`, whose installed template correctly
honors the disabled-thinking request and produces structured tool calls. The
installed `qwen3:4b` and downloaded `qwen3:4b-instruct` templates failed live tool
verification on this Ollama runtime. Keep the verified 8B model unless a replacement
passes the same tool-calling checks.

## Access model

There is one global service switch and group-based authorization.

- **Release controls → AI Enable** is a button, not a settings page. It controls the global master switch.
- **Groups** is the source of truth for normal assistant/AI authorization. Open Release Managers, Management, or an individual tenant group and use its **AI Enable [Active/Off]** button.
- **AI Users** is a special override group. Membership grants access while the master switch is ON.
- The global OFF switch is authoritative.
- The protected PDS Owner may validate the assistant while the global switch is ON.

## Optional local AI: Qwen3 + FAISS RAG

Run `docker compose -f docker-compose.Ollama_hosted.yml up -d --build`. This opt-in Compose file pulls the Ollama image, starts its server, and downloads the configured chat and embedding models automatically. The app starts after both model pulls succeed. The first download may take several minutes; follow it with `docker compose -f docker-compose.Ollama_hosted.yml logs -f ollama-pull`. Model files persist in the `ollama-data` volume across restarts. No host Ollama installation is required.

```env
AI_PROVIDER=ollama_rag
AI_BASE_URL=http://ollama:11434
AI_MODEL=qwen3:8b
AI_EMBEDDING_MODEL=nomic-embed-text
AI_TIMEOUT_SECONDS=120
```

Ollama's API does not require an API key. The FAISS index and embeddings are held in app process memory only; the index is rebuilt when PDS schedule, tenant, or assignment data changes, and is not stored in PostgreSQL or on disk.

Example questions:

- "Summarize the purpose of PDS-027 in plain language."
- "How many failed NCAP deployments happened in September 2026?"
- "Who is the Release Manager assigned to PDS-027?"
- "How many tenants are configured?"
- "When is the next slot available?"

Next-slot questions use the authenticated `/api/assistant/availability/next-slot` operation. It checks the same board-derived bookable state used by PDS, including active bookings, configured capacity, holidays, automatic freezes, manual freezes, and unlock overrides. It searches the next 60 days; an empty schedule search is not treated as evidence that no slots are available.

Schedule-number questions about the Release Manager, Change No., or status are answered directly from the authenticated read-only schedule API, rather than relying on model-generated text. Model replies containing recognizable internal reasoning are rejected instead of shown in the chat.

The model's answers are always read-only. It cannot cancel, reschedule, assign, start, close, freeze, or modify a PDS record. PostgreSQL is accessed through parameterized, allow-listed query functions; the model never receives database credentials and cannot generate or execute arbitrary SQL.

### Built-in assistant (default Compose)

The default Compose file forces `AI_PROVIDER=builtin`, regardless of shared `.env` settings. Standalone deployments can select the same value explicitly. This deterministic mode does not require FAISS or a model and supports common structured PDS queries, but it does not provide natural-language generation or semantic retrieval.

## Future organisation AI gateway

For a standalone container or separate app pod, an approved organisation AI service can be selected through the existing environment configuration. The supplied Compose files force their own providers; using a gateway with Compose requires an explicit app-environment override:

```env
AI_PROVIDER=org_gateway
AI_API_KEY=<credential-issued-by-your-organisation>
AI_MODEL=<approved-model-or-deployment-name>
AI_BASE_URL=<approved-ai-gateway-base-url>
AI_API_PATH=/responses
AI_AUTH_HEADER=Authorization
AI_AUTH_SCHEME=Bearer
AI_TIMEOUT_SECONDS=120
```

The existing external adapter expects a Responses-compatible endpoint. The PDS UI, group permissions, REST endpoints, MCP tools and read-only database query layer do not need to change.

If the organisation provides a native Claude/Anthropic endpoint or another non-compatible protocol, add a provider adapter at that time; keep the `AI_*` environment contract and PDS tool layer unchanged.

## MCP controls for external assistants

MCP is independent from the in-app assistant:

```env
MCP_ENABLED=true
MCP_API_KEY=<generate-a-long-random-secret>
```

`MCP_API_KEY` authenticates a trusted MCP client to PDS. It is not an AI/model credential and must never be reused as `AI_API_KEY`.

Generate a strong MCP service key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If the PDS base URL is `https://pds.example.com`, the MCP URL is:

```text
https://pds.example.com/mcp
```

The connector sends:

```text
Authorization: Bearer <MCP_API_KEY>
```

## Available read-only tools

| Tool | Purpose |
| --- | --- |
| `get_schedule` | Find a schedule by PDS schedule number, including Change No. and assigned RM(s). |
| `search_schedules` | Filter by tenant, date range, status, Change No., or Schedule No. |
| `count_schedules` | Count schedules with status and normal/emergency breakdowns. |
| `deployment_summary` | Summarise a date range by status and tenant. |
| `tenant_summary` | Summarise one tenant and RM assignment counts. |
| `list_tenants` | List configured tenants and return the tenant count. |
| `next_available_slot` | Return the earliest bookable normal slot within the next 60 days. |

## Recommended POC `.env`

```env
ENVIRONMENT=development

MCP_ENABLED=true
MCP_API_KEY=<your-long-random-secret>

# Local Qwen3 with in-memory FAISS retrieval.
AI_PROVIDER=ollama_rag
AI_BASE_URL=http://ollama:11434
AI_MODEL=qwen3:8b
AI_EMBEDDING_MODEL=nomic-embed-text
AI_TIMEOUT_SECONDS=120

# Used only when AI_PROVIDER=org_gateway.
AI_API_KEY=
AI_API_PATH=/responses
AI_AUTH_HEADER=Authorization
AI_AUTH_SCHEME=Bearer
```

For this Ollama POC configuration, use the explicit full-stack file:

```bash
docker compose -f docker-compose.Ollama_hosted.yml up -d --build
```

The optional Compose file runs the app, PostgreSQL, and Ollama together. The app reaches Ollama at `http://ollama:11434`; `ollama-pull` downloads the models before the app starts. To change models, edit `AI_MODEL` / `AI_EMBEDDING_MODEL` and rerun the same full-stack command.

User counts are available at `/api/assistant/users/count?group=Management`. The `count_users` AI tool returns aggregate total/active/inactive counts from real group memberships, with no user credentials or personal details. Try "How many management users are there?"; prior schedule filters do not affect this direct lookup.

## Query validation and supported scope

Schedule searches, counts, and summaries now share status and emergency/normal
filters across the REST API and AI tools. Open maps to BOOKED and Closed maps to
COMPLETED. Tenant queries distinguish active, inactive and all configured tenants.
User group counts distinguish active and inactive accounts. Unknown explicit tenant
names cannot be replaced by all-tenant data. A model must use a relevant tool and
verify every requested schedule reference before comparing records. The same
verification gate now applies to the hosted gateway path (tested with mocks).

Simple count follow-ups such as "How many of those?" reuse the prior user question's
filters directly. Retrieved labels cannot select their tenant. Reasoning still uses
FAISS as context and backend tools as facts. `AI_CONTEXT_WINDOW=8192`, bounded
history, and bounded retrieval context reduce accidental prompt truncation.

Personal scheduling scope, per-tenant availability guarantees, document/holiday or
admin-role counts, and individual account listings are not supported by the current
assistant; these requests now explain the limitation. General slot availability is
not a guarantee that a particular user/tenant can book it. Sample data is synthetic.

## CPU deployment with separate app, database, and Ollama pods

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
docker compose -f docker-compose.Ollama_hosted.yml -f docker-compose.cpu.yml up -d --build
```

The 4K profile trims retrieved text and older conversation messages on general reasoning requests. The normal profile retains the 8K setting. Keep the larger context if full conversation/document coverage matters and sufficient memory is allocated. Direct exact-record explanations use compact prompts; contextual questions retain the general reasoning path.

Implemented CPU improvements:

- Exact schedule references are fetched first and explained in one model call. All requested records must be verified; failed lookups retain the original retry path. No embeddings or large tool schemas are needed on successful exact-record requests.
- A conservative parser handles simple two-scope count comparisons and status percentages without invoking a model. Ambiguous or unsupported grammar goes to the validated AI planner rather than broadening the database query.
- Validated analytical plans are cached for up to five minutes of inactivity, at most 128 per app process. Cache keys include provider/model/context, date, known tenants, question and prior scope. Every answer still validates filters and queries the current database; cached plans are never cached facts. App replicas have independent caches.
- Chat/planning requests explicitly use CPU inference, configurable thread count, and a 30-minute keep-alive. One parallel request avoids simultaneous inference competing for limited CPU/RAM. Higher concurrency needs a load test on the target pod.

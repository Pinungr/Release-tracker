# PDS Assistant / Future AI / MCP Integration

PDS exposes the same approved read-only schedule query service in three ways:

1. **PDS Assistant** — an in-app floating chat for authorized PDS users.
2. **Authenticated REST API** under `/api/assistant/...` for PDS/in-house clients using a normal PDS user JWT.
3. **MCP endpoint** at `/mcp` for Copilot, Codex/ChatGPT, Claude, and other MCP-capable hosts.

The default in-app assistant combines local Qwen3 through Ollama, process-local FAISS retrieval, and a dedicated read-only PDS backend API agent. Structured schedule lookups, supported counts, tenant lists, and summaries are fetched from the backend API first and humanized by Qwen3 when it is available. If Ollama is unreachable, the API's verified response is still returned with an explicit direct-response notice. Questions needing semantic document/context understanding use FAISS retrieval and Qwen3, with backend API tools required to verify factual PDS answers. That agent calls the same approved service operations as the authenticated `/api/assistant/*` endpoints in-process, avoiding a self-request over HTTP while keeping the application's backend operations as the source of truth. If Qwen cannot verify a factual answer, the chat fails closed instead of returning an unverified claim. FAISS supplies supporting context; it is not used to calculate counts or current statuses. PDS data is not sent to an external model provider.

## Hybrid question routing

The assistant uses the read-only backend API directly for recognized counts,
filtered lists, user/group membership counts, schedule status / Change No. / Release Manager lookups, basic
summaries, and next-slot availability. These answers do not call the chat model,
embedding model, or FAISS, and remain available if AI configuration is incomplete.

A direct API error, unexpected null, or malformed result triggers the reasoning
path, which searches FAISS context and retries approved read-only tools. Valid zero
counts and empty result lists remain direct answers. If embeddings are unavailable,
the app agent can still use database tools. Failed or null tool results cannot
verify model-generated facts.

Questions requiring explanation, comparison, semantic matching, or conversational
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

## Default local mode: Qwen3 + FAISS RAG

Run `docker compose up -d --build`. Compose pulls the Ollama image, starts its server, and downloads the configured chat and embedding models automatically. The app starts after both model pulls succeed. The first download may take several minutes; follow it with `docker compose logs -f ollama-pull`. Model files persist in the `ollama-data` volume across restarts. No host Ollama installation is required.

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

### Built-in rules fallback

To run without Ollama, use `AI_PROVIDER=builtin`. This deterministic mode does not require FAISS or a model and supports common structured PDS queries, but it does not provide natural-language generation or semantic retrieval.

## Future organisation AI gateway

When the organisation provides an approved AI service, switch only the environment configuration:

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

```

After changing `.env`:

```bash
docker compose up -d --build
```

Compose runs the app, PostgreSQL, and Ollama together. The app reaches Ollama at `http://ollama:11434`; `ollama-pull` downloads the models before the app starts. To change models, edit `AI_MODEL` / `AI_EMBEDDING_MODEL` and rerun `docker compose up -d --build`.

User counts are available at `/api/assistant/users/count?group=Management`. The `count_users` AI tool returns aggregate total/active/inactive counts from real group memberships, with no user credentials or personal details. Try "How many management users are there?"; prior schedule filters do not affect this direct lookup.

## Demo audit corrections (October 3, 2026)

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

See `scripts/AI_DEMO_CHECK.md` for the rehearsal questions and read-only live check.

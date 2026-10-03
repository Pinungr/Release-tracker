# PDS Assistant / Future AI / MCP Integration

PDS exposes the same approved read-only schedule query service in three ways:

1. **PDS Assistant** — an in-app floating chat for authorized PDS users.
2. **Authenticated REST API** under `/api/assistant/...` for PDS/in-house clients using a normal PDS user JWT.
3. **MCP endpoint** at `/mcp` for Copilot, Codex/ChatGPT, Claude, and other MCP-capable hosts.

The local POC no longer runs Ollama or downloads a local model. The default in-app assistant is a fast, deterministic read-only query layer that recognises common PDS questions and calls only the allow-listed SQLAlchemy query functions. No external AI key, model, API credits, or extra AI container is required.

## Access model

There is one global service switch and group-based authorization.

- **Release controls → AI Enable** is a button, not a settings page. It controls the global master switch.
- **Groups** is the source of truth for normal assistant/AI authorization. Open Release Managers, Management, or an individual tenant group and use its **AI Enable [Active/Off]** button.
- **AI Users** is a special override group. Membership grants access while the master switch is ON.
- The global OFF switch is authoritative.
- The protected PDS Owner may validate the assistant while the global switch is ON.

## Default local POC mode: built-in rules

Use:

```env
AI_PROVIDER=builtin
```

That is all the in-app assistant needs. No `AI_API_KEY`, `AI_MODEL`, or `AI_BASE_URL` is required.

Supported examples include:

- How many deployments happened in September 2026?
- How many NCAP schedules were there in September 2026?
- Show failed NCAP deployments between 2026-09-01 and 2026-09-30.
- How many emergency RADA deployments happened last month?
- What is the Change No. for PDS-027?
- Who is the Release Manager assigned to PDS-027?
- What is the status of PDS-027?
- How many tenants are configured?

The built-in assistant is intentionally narrower than a real LLM. For questions it does not recognise, it returns examples of supported queries instead of guessing.

It is always read-only. It cannot cancel, reschedule, assign, start, close, freeze, or modify a PDS record.

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

## Recommended POC `.env`

```env
ENVIRONMENT=development

MCP_ENABLED=true
MCP_API_KEY=<your-long-random-secret>

AI_PROVIDER=builtin

# Keep blank until an approved organisation AI gateway is available.
AI_API_KEY=
AI_MODEL=
AI_BASE_URL=
AI_API_PATH=/responses
AI_AUTH_HEADER=Authorization
AI_AUTH_SCHEME=Bearer
```

After changing `.env`:

```bash
docker compose up -d --build
```

Only `pds-app` and `pds-postgres` are required for the default local POC. There is no Ollama container or model volume.

# Management demo rehearsal

Audited October 3, 2026, against the local PostgreSQL sample database.

## Verified sample facts

| Question | Expected answer |
| --- | --- |
| How many schedules are there? | 12 |
| How many failed deployments in September 2026? | 2 |
| How many EPCAT deployments in September 2026? | 2 |
| How many open deployments in October 2026? | 6 Booked records |
| How many emergency deployments in October 2026? | 1 |
| How many normal deployments in October 2026? | 5 |
| Show emergency deployments in October 2026 | PDS-012 only |
| Deployment summary of failed schedules in September 2026 | 2 failed records |
| Show inactive tenants | None |
| How many management users are there? | 0 Management members |
| How many users are there? | 1 account |
| How many inactive users are there? | 0 |
| Compare PDS-002 and PDS-005 | Failed storage permissions; later successful refresh after correcting permissions |
| Show failed deployments in September 2026, then: How many of those are there? | 2, with the same September/status filters |

These are synthetic examples. Explain that October entries are scheduled records,
not evidence that future deployments have already happened. Management group
membership differs from Owner/administrator status.

## Corrections made

- Emergency/normal filtering applies to searches, counts and summaries.
- Status-filtered summaries retain the requested status; Open maps to Booked,
  Closed maps to Completed.
- Tenant activity and account activity filters are preserved.
- Unknown explicit tenants cannot be replaced by all-tenant counts.
- Unrelated tools cannot verify answers. Comparisons must verify every requested
  schedule reference. Hosted gateway verification is covered by mocked tests.
- Simple count follow-ups reuse explicit user filters instead of FAISS labels.
- Invalid tool argument types are rejected. Model context, history and retrieved
  context are bounded; CPU responses are limited to 512 output tokens.
- Future/current period counts say records are recorded rather than claiming
  future deployments already occurred.
- The group AI-toggle frontend test waits for the group to finish loading before
  clicking; production toggle behavior was unchanged.

## Scope and limits

95 backend assistant/access regression tests and all 91 frontend tests passed.
Live checks exercise direct answers, FAISS embeddings, model tool calls,
record comparisons and contextual follow-ups. The app readiness check confirms
PostgreSQL connectivity. This was an assistant integration audit, not a complete
security, performance or production certification of every application feature.

The current assistant cannot list individual accounts, filter schedules by the
current user's identity, count documents/holidays/admin roles, or guarantee
tenant-specific booking eligibility. It explains these limitations; use the
relevant application screens. General slot availability still requires the board
to enforce user permissions and tenant quota when actually booking.

MCP is disabled in the running configuration. External gateway behavior was
tested with mocks; no external gateway or connector was used live. Local AI uses
`qwen3:8b`, `nomic-embed-text`, and an 8192-token configured context window.
Open-ended model explanations remain variable and can take longer on CPU.

## Rehearse before presenting

Start a new chat and use the questions above. AI Enable is currently on; keep the
appropriate user/group access enabled for the demo account. If you modify the
sample dataset, update the expected counts before using this checklist.

Read-only verification from PowerShell:

```powershell
Get-Content scripts/verify-ai-demo.py -Raw | docker compose exec -T app python -
```

The script fails if expected counts or model evidence are wrong. It does not seed,
delete or alter records.

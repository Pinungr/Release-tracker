# AI sample records

The local PostgreSQL database contains 12 synthetic `AI-DEMO` deployments:
four each for NCAP, EPCAT and RADA. PDS-001 through PDS-006 are September
2026 history: three completed, two failed and one rolled back. PDS-007 through
PDS-012 are booked for October 11–12, 2026, including one emergency change.
Descriptions contain sample causes, fixes and validation steps for AI reasoning.
Ten records are assigned to the existing Owner; two remain unassigned. No new
login accounts or holidays are created. Records are marked `SAMPLE DATA`.

Try these questions in the PDS assistant:

- How many schedules are there? (12)
- How many failed deployments in September 2026? (2)
- How many emergency deployments in October 2026? (1)
- Show failed deployments in September 2026.
- Who is the Release Manager for PDS-001?
- Explain why PDS-002 failed.
- Compare PDS-002 and PDS-005.
- Explain the purpose of PDS-007.

To add missing samples again from PowerShell:

```powershell
Get-Content scripts/seed-ai-samples.py -Raw | docker compose exec -T app python -
```

The script skips existing samples; it does not reset the database. PostgreSQL
listens at `127.0.0.1:15432` using the PostgreSQL protocol; the app UI is the
place to ask assistant questions.
